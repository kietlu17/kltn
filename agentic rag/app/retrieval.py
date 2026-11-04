from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata

from qdrant_client import AsyncQdrantClient, models

from .config import AgenticSettings
from .schemas import SearchFilters
from .sparse import SPARSE_VECTOR_NAME, query_sparse_vector
from .specs import normalize_constraint

log = logging.getLogger(__name__)

_DYNAMIC_FACETS = {
    "product_type": "productType",
    "audience": "audience",
    "brand": "brand",
    "colors": "colors",
    "sizes": "sizes",
}
_FACET_CACHE_SECONDS = 300
_FACET_LIMIT = 1000


def _taxonomy_key(value: object) -> str:
    """Create a catalog-agnostic comparison key for a facet value."""
    text = unicodedata.normalize("NFD", str(value).casefold()).replace("\u0111", "d")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _resolve_facet_value(value: object, available: list[str]) -> str | None:
    requested = _taxonomy_key(value)
    if not requested:
        return None
    by_key = {
        _taxonomy_key(candidate): candidate
        for candidate in available
        if _taxonomy_key(candidate)
    }
    return by_key.get(requested)


def _search_terms(value: str) -> list[str]:
    text = unicodedata.normalize("NFD", value.casefold()).replace("đ", "d")
    text = "".join(char for char in text if not unicodedata.combining(char))
    stop = {
        "toi", "muon", "tim", "cho", "xem", "mot", "vai", "san", "pham", "co",
        "the", "nao", "giup", "minh", "ban", "oi", "va", "hoac", "duoc",
        "gia", "mac", "mat", "dat", "re", "nhat", "loai", "hang", "cao",
        "thap", "hien", "tai", "cua", "bao", "nhieu", "tien", "la", "ma",
    }
    return list(
        dict.fromkeys(
            token
            for token in re.findall(r"[a-z0-9]{2,}", text)
            if token not in stop
        )
    )[:12]


class StructuredProductRetriever:
    """Read-only filter-then-score retrieval over the existing product collection."""

    def __init__(
        self,
        settings: AgenticSettings,
        models_gateway,
        client: AsyncQdrantClient | None = None,
    ):
        self.settings = settings
        self.models = models_gateway
        self.collection = settings.collection
        self.client = client or AsyncQdrantClient(
            url=settings.qdrant_url, timeout=settings.request_timeout
        )
        self._facet_cache: dict[str, tuple[float, list[str]]] = {}
        self._hybrid: bool | None = None

    async def _hybrid_ready(self) -> bool:
        """True when the collection carries the BM25 sparse vector (v5+)."""
        if self._hybrid is None:
            info = await self.client.get_collection(self.collection)
            sparse = getattr(info.config.params, "sparse_vectors", None) or {}
            self._hybrid = SPARSE_VECTOR_NAME in sparse
        return self._hybrid

    async def category_product_counts(self) -> dict[str, int]:
        """Products per category id (one base chunk per product), cached."""
        cached = self._facet_cache.get("__category_counts__")
        now = time.monotonic()
        if cached and cached[0] > now:
            return cached[1]
        try:
            response = await self.client.facet(
                self.collection,
                key="categoryId",
                facet_filter=models.Filter(
                    must=[models.FieldCondition(key="chunkType", match=models.MatchValue(value="base"))]
                ),
                limit=_FACET_LIMIT,
                exact=False,
            )
        except Exception:
            return {}
        counts = {str(hit.value): int(hit.count) for hit in response.hits}
        self._facet_cache["__category_counts__"] = (now + _FACET_CACHE_SECONDS, counts)
        return counts

    async def _facet_values(self, key: str) -> list[str] | None:
        cached = self._facet_cache.get(key)
        now = time.monotonic()
        if cached and cached[0] > now:
            return cached[1]
        try:
            response = await self.client.facet(
                self.collection,
                key=key,
                facet_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="kind", match=models.MatchValue(value="text")
                        )
                    ]
                ),
                limit=_FACET_LIMIT,
                exact=False,
            )
        except Exception:
            # A facet lookup is an optimization. Preserve the caller's exact
            # constraint if the catalog cannot expose its vocabulary.
            return None
        values = [
            str(hit.value)
            for hit in response.hits
            if isinstance(hit.value, (str, int, float)) and str(hit.value).strip()
        ]
        self._facet_cache[key] = (now + _FACET_CACHE_SECONDS, values)
        return values

    async def _resolve_catalog_filters(self, filters: SearchFilters) -> SearchFilters:
        """Ground LLM-proposed facets in the collection's live vocabulary.

        Unknown values are omitted from Qdrant's exact filter and remain part
        of the semantic query. This avoids false zero-result searches without
        maintaining a platform-wide, hard-coded taxonomy.
        """
        resolved = filters.model_copy(deep=True)
        if resolved.category_id and not re.fullmatch(
            r"[a-fA-F0-9]{24}", resolved.category_id
        ):
            resolved.category_id = None

        requested = {
            field: getattr(filters, field)
            for field in _DYNAMIC_FACETS
            if getattr(filters, field)
        }
        if not requested:
            return resolved

        fields = list(requested)
        vocabularies = await asyncio.gather(
            *(self._facet_values(_DYNAMIC_FACETS[field]) for field in fields)
        )
        for field, available in zip(fields, vocabularies):
            if available is None:
                continue
            value = requested[field]
            if isinstance(value, list):
                grounded = [
                    match
                    for item in value
                    if (match := _resolve_facet_value(item, available)) is not None
                ]
                setattr(resolved, field, list(dict.fromkeys(grounded)))
            else:
                setattr(resolved, field, _resolve_facet_value(value, available))
        return resolved

    async def _infer_product_type(self, query: str) -> str | None:
        """Infer a product type only from the collection's live vocabulary."""
        available = await self._facet_values("productType")
        if not available:
            return None
        query_key = _taxonomy_key(query)
        matches = [
            value
            for value in available
            if (key := _taxonomy_key(value))
            and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", query_key)
        ]
        return max(matches, key=lambda value: len(_taxonomy_key(value)), default=None)

    @staticmethod
    def _build_filter(filters: SearchFilters) -> models.Filter:
        must: list = [
            models.FieldCondition(
                key="kind", match=models.MatchValue(value="text")
            )
        ]
        category_ids = filters.category_ids or (
            [filters.category_id] if filters.category_id else []
        )
        if category_ids:
            must.append(
                models.FieldCondition(
                    key="categoryId", match=models.MatchAny(any=category_ids)
                )
            )
        keyword_values = (
            ("productType", filters.product_type),
            ("brand", filters.brand),
            ("colors", filters.colors),
            ("sizes", filters.sizes),
        )
        for key, value in keyword_values:
            if not value:
                continue
            match = (
                models.MatchAny(any=value)
                if isinstance(value, list)
                else models.MatchValue(value=value)
            )
            must.append(models.FieldCondition(key=key, match=match))
        if filters.audience:
            must.append(
                models.FieldCondition(
                    key="audience",
                    match=models.MatchAny(any=[filters.audience, "unisex"]),
                )
            )
        if filters.max_price is not None:
            must.append(
                models.FieldCondition(
                    key="minPrice", range=models.Range(lte=filters.max_price)
                )
            )
        if filters.min_price is not None:
            must.append(
                models.FieldCondition(
                    key="maxPrice", range=models.Range(gte=filters.min_price)
                )
            )
        for raw_constraint in filters.spec_constraints:
            constraint = normalize_constraint(raw_constraint)
            if constraint.strength != "hard" or not isinstance(
                constraint.value, (int, float)
            ):
                continue
            value = float(constraint.value)
            if constraint.operator == "eq":
                tolerance = max(abs(value) * 0.01, 1e-9)
                number_range = models.Range(gte=value - tolerance, lte=value + tolerance)
            elif constraint.operator == "lt":
                number_range = models.Range(lt=value)
            elif constraint.operator == "lte":
                number_range = models.Range(lte=value)
            elif constraint.operator == "gt":
                number_range = models.Range(gt=value)
            elif constraint.operator == "gte":
                number_range = models.Range(gte=value)
            else:
                continue
            must.append(
                models.NestedCondition(
                    nested=models.Nested(
                        key="specs",
                        filter=models.Filter(
                            must=[
                                models.FieldCondition(
                                    key="key",
                                    match=models.MatchValue(value=constraint.key),
                                ),
                                models.FieldCondition(
                                    key="numericValue", range=number_range
                                ),
                            ]
                        ),
                    )
                )
            )
        must_not: list = []
        if filters.exclude_product_ids:
            must_not.append(
                models.FieldCondition(
                    key="productId",
                    match=models.MatchAny(any=filters.exclude_product_ids),
                )
            )
        return models.Filter(must=must, must_not=must_not)

    async def product_context(self, product_id: str) -> dict:
        """Aggregate indexed facets for an anchor product across all chunks."""
        if not re.fullmatch(r"[a-fA-F0-9]{24}", product_id):
            return {}
        points, _ = await self.client.scroll(
            self.collection,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="kind", match=models.MatchValue(value="text")
                    ),
                    models.FieldCondition(
                        key="productId", match=models.MatchValue(value=product_id)
                    ),
                ]
            ),
            with_payload=True,
            with_vectors=False,
            limit=100,
        )
        payloads = [dict(point.payload or {}) for point in points]
        if not payloads:
            return {}

        def first_value(key: str):
            return next((payload.get(key) for payload in payloads if payload.get(key)), None)

        def all_values(key: str) -> list[str]:
            values: list[str] = []
            for payload in payloads:
                raw = payload.get(key)
                items = raw if isinstance(raw, list) else [raw]
                values.extend(str(item) for item in items if item not in (None, ""))
            return list(dict.fromkeys(values))

        min_prices = [
            float(payload["minPrice"])
            for payload in payloads
            if isinstance(payload.get("minPrice"), (int, float))
        ]
        max_prices = [
            float(payload["maxPrice"])
            for payload in payloads
            if isinstance(payload.get("maxPrice"), (int, float))
        ]
        texts = list(
            dict.fromkeys(
                str(payload.get("text") or "").strip()
                for payload in payloads
                if str(payload.get("text") or "").strip()
            )
        )
        product_type = first_value("productType")
        if _taxonomy_key(product_type or "") in {"", "khac", "other"}:
            # Infer from product-title lines only. Descriptions often mention
            # related devices (for example a speaker controlled by a phone),
            # which must not redefine the anchor's product type.
            title_text = " ".join(text.splitlines()[0] for text in texts)
            inferred_type = await self._infer_product_type(title_text)
            if inferred_type and _taxonomy_key(inferred_type) not in {"khac", "other"}:
                product_type = inferred_type
        return {
            "productId": product_id,
            "categoryId": first_value("categoryId"),
            "productType": product_type,
            "audience": all_values("audience"),
            "brand": first_value("brand"),
            "colors": all_values("colors"),
            "sizes": all_values("sizes"),
            "minPrice": min(min_prices) if min_prices else None,
            "maxPrice": max(max_prices) if max_prices else None,
            "text": "\n".join(texts[:8]),
        }

    @staticmethod
    def _group_hits(groups: list, source: str) -> list[dict]:
        """One hit per product; the best chunks are kept as evidence."""
        hits: list[dict] = []
        for group in groups:
            points = list(group.hits or [])
            if not points:
                continue
            best = points[0]
            hits.append(
                {
                    "productId": str(group.id),
                    "score": float(best.score),
                    "vectorScore": float(best.score),
                    "payload": dict(best.payload or {}),
                    "evidence": [
                        str((point.payload or {}).get("text") or "")[:500]
                        for point in points
                    ],
                    "sources": [source],
                }
            )
        return hits

    @staticmethod
    def _ordered_hits(points: list, limit: int) -> list[dict]:
        hits: list[dict] = []
        seen: set[str] = set()
        for point in points:
            payload = dict(point.payload or {})
            product_id = str(payload.get("productId") or "")
            if not product_id or product_id in seen:
                continue
            seen.add(product_id)
            hits.append(
                {
                    "productId": product_id,
                    "score": None,
                    "vectorScore": None,
                    "payload": payload,
                    "sources": ["price_order"],
                }
            )
            if len(hits) >= limit:
                break
        return hits

    async def search(
        self,
        query: str,
        filters: SearchFilters,
        limit: int | None = None,
        sort_by: str = "relevance",
    ) -> list[dict]:
        limit = limit or self.settings.retrieval_limit
        # Embedding and facet grounding are independent; overlap their latency.
        vector_task = (
            asyncio.create_task(self.models.embed_query(query))
            if sort_by == "relevance"
            else None
        )
        try:
            grounded_filters = await self._resolve_catalog_filters(filters)
        except BaseException:
            if vector_task:
                vector_task.cancel()
            raise
        if sort_by != "relevance" and not grounded_filters.product_type:
            inferred_type = await self._infer_product_type(query)
            if inferred_type:
                grounded_filters.product_type = inferred_type
        query_filter = self._build_filter(grounded_filters)
        terms = _search_terms(query)
        if sort_by in {"price_asc", "price_desc"}:
            ordered_filter = models.Filter(
                must=list(query_filter.must or []),
                must_not=list(query_filter.must_not or []),
            )
            has_structured_scope = bool(
                grounded_filters.product_type
                or grounded_filters.category_id
                or grounded_filters.category_ids
                or grounded_filters.category_path
            )
            if terms and not has_structured_scope:
                ordered_filter.must.append(
                    models.FieldCondition(
                        key="text",
                        match=models.MatchTextAny(text_any=" ".join(terms)),
                    )
                )
            price_key = "maxPrice" if sort_by == "price_desc" else "minPrice"
            direction = (
                models.Direction.DESC
                if sort_by == "price_desc"
                else models.Direction.ASC
            )
            ordered_points, _ = await self.client.scroll(
                self.collection,
                scroll_filter=ordered_filter,
                order_by=models.OrderBy(key=price_key, direction=direction),
                with_payload=True,
                with_vectors=False,
                limit=min(max(limit * 3, 50), 200),
            )
            return self._ordered_hits(ordered_points, limit)
        try:
            vector = await vector_task
        except Exception as error:
            # Embedding quota, timeout or turn budget: keyword search still
            # finds products, a failed turn finds none.
            log.warning("Query embedding failed, searching BM25 only: %s: %s",
                        type(error).__name__, str(error)[:200])
            vector = None
        group_args = {
            "group_by": "productId",
            "group_size": 2,
            "limit": limit,
            "with_payload": True,
        }
        sparse = query_sparse_vector(query)
        hybrid_ready = sparse["indices"] and await self._hybrid_ready()
        if vector is None:
            if not hybrid_ready:
                return []
            response = await self.client.query_points_groups(
                self.collection,
                query=models.SparseVector(**sparse),
                using=SPARSE_VECTOR_NAME,
                query_filter=query_filter,
                **group_args,
            )
            return self._group_hits(response.groups, "bm25")
        if hybrid_ready:
            # Dense and BM25 candidates are fused server-side with RRF, then
            # grouped so every product occupies one slot regardless of how
            # many of its chunks matched.
            prefetch_limit = max(limit * 4, 100)
            response = await self.client.query_points_groups(
                self.collection,
                prefetch=[
                    models.Prefetch(
                        query=vector,
                        filter=query_filter,
                        limit=prefetch_limit,
                        score_threshold=self.settings.min_score,
                    ),
                    models.Prefetch(
                        query=models.SparseVector(**sparse),
                        using=SPARSE_VECTOR_NAME,
                        filter=query_filter,
                        limit=prefetch_limit,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                **group_args,
            )
            return self._group_hits(response.groups, "hybrid")
        response = await self.client.query_points_groups(
            self.collection,
            query=vector,
            query_filter=query_filter,
            score_threshold=self.settings.min_score,
            **group_args,
        )
        return self._group_hits(response.groups, "dense")

    async def health(self) -> dict:
        exists = await self.client.collection_exists(self.collection)
        dimensions = None
        points = 0
        products = 0
        spec_coverage = 0.0
        baseline_products = 0
        hybrid = False
        if exists:
            info = await self.client.get_collection(self.collection)
            vectors = info.config.params.vectors
            dimensions = getattr(vectors, "size", None)
            points = int(info.points_count or 0)
            hybrid = SPARSE_VECTOR_NAME in (
                getattr(info.config.params, "sparse_vectors", None) or {}
            )
            self._hybrid = hybrid
            products = await self._product_count(self.collection)
            sample, _ = await self.client.scroll(
                self.collection,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="kind", match=models.MatchValue(value="text")
                        )
                    ]
                ),
                with_payload=["specs"],
                with_vectors=False,
                limit=256,
            )
            if sample:
                spec_coverage = sum(
                    bool((point.payload or {}).get("specs")) for point in sample
                ) / len(sample)
        collections = await self.client.get_collections()
        previous_catalogs = [
            item.name
            for item in collections.collections
            if item.name.startswith("catalog_")
            and not item.name.startswith("catalog_images_")
            and item.name != self.collection
        ]
        if previous_catalogs:
            baseline_products = max(
                await asyncio.gather(
                    *(self._product_count(name) for name in previous_catalogs)
                )
            )
        # Compare products, not points: chunking changes points per product.
        catalog_coverage = (
            min(products / baseline_products, 1.0)
            if baseline_products
            else float(products > 0)
        )
        return {
            "exists": exists,
            "collection": self.collection,
            "dimensions": dimensions,
            "expectedDimensions": self.settings.embedding_dimensions,
            "dimensionMatches": dimensions == self.settings.embedding_dimensions,
            "points": points,
            "products": products,
            "baselineProducts": baseline_products,
            "catalogCoverage": round(catalog_coverage, 4),
            "catalogComplete": bool(products > 0 and catalog_coverage >= 0.95),
            "hybridReady": hybrid,
            "semanticSchemaVersion": "v5-chunked" if hybrid else "v4-semantic-specs",
            "specCoverage": round(spec_coverage, 4),
        }

    async def _product_count(self, collection: str) -> int:
        """Count products by their single overview (v5) or base (v4) chunk."""
        result = await self.client.count(
            collection,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="chunkType", match=models.MatchAny(any=["overview", "base"])
                    )
                ]
            ),
            exact=True,
        )
        return int(result.count)

    async def close(self):
        await self.client.close()

