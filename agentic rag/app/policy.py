from __future__ import annotations

import hashlib
import logging
import math
import time

from qdrant_client import AsyncQdrantClient

from .config import AgenticSettings
from .sparse import document_sparse_vector, query_sparse_vector

log = logging.getLogger(__name__)
_KEYWORD_INDEX_SECONDS = 3600


class PolicyRetriever:
    """Read-only adapter for the policy collection maintained by chatbot-service."""

    def __init__(self, settings: AgenticSettings, models_gateway, client=None):
        self.models = models_gateway
        self.client = client or AsyncQdrantClient(
            url=settings.qdrant_url, timeout=settings.request_timeout
        )
        identity = (
            f"v1:policy:{settings.embedding_model}:{settings.embedding_dimensions}"
        )
        self.collection = f"policies_{hashlib.sha256(identity.encode()).hexdigest()[:12]}"
        self._keyword_index: tuple[float, list, dict[int, float]] | None = None

    async def retrieve(self, question: str, limit: int = 6) -> tuple[list[dict], list[dict]]:
        if not await self.client.collection_exists(self.collection):
            return [], []
        try:
            vector = await self.models.embed_query(question)
        except Exception as error:
            # The policy collection has no sparse vector: rank an in-memory
            # BM25 index instead of failing the question.
            log.warning("Policy embedding failed, using keyword search: %s: %s",
                        type(error).__name__, str(error)[:200])
            points = await self._keyword_search(question, limit)
        else:
            response = await self.client.query_points(
                self.collection,
                query=vector,
                with_payload=True,
                limit=limit,
                score_threshold=0.3,
            )
            points = response.points
        context: list[dict] = []
        sources: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for point in points:
            payload = dict(point.payload or {})
            title = str(payload.get("title") or "").strip()
            text = str(payload.get("text") or "").strip()
            url = str(payload.get("sourceUrl") or "").strip()
            if not text:
                continue
            key = (title, url)
            number = next(
                (item["number"] for item in sources if (item["title"], item["url"]) == key),
                None,
            )
            if number is None:
                number = len(sources) + 1
                sources.append({"number": number, "title": title, "url": url})
                seen.add(key)
            context.append(
                {"number": number, "title": title, "text": text[:3000], "url": url}
            )
        return context, sources

    async def _keyword_search(self, question: str, limit: int) -> list:
        now = time.monotonic()
        if not self._keyword_index or self._keyword_index[0] <= now:
            points, offset = [], None
            while True:
                batch, offset = await self.client.scroll(
                    self.collection, limit=1000, offset=offset,
                    with_payload=True, with_vectors=False,
                )
                points.extend(batch)
                if offset is None:
                    break
            vectors = []
            document_frequency: dict[int, int] = {}
            for point in points:
                payload = point.payload or {}
                sparse = document_sparse_vector(
                    f"{payload.get('title') or ''} {payload.get('text') or ''}"
                )
                weights = dict(zip(sparse["indices"], sparse["values"]))
                vectors.append((point, weights))
                for index in weights:
                    document_frequency[index] = document_frequency.get(index, 0) + 1
            total = max(len(points), 1)
            idf = {
                index: math.log(1 + (total - count + 0.5) / (count + 0.5))
                for index, count in document_frequency.items()
            }
            self._keyword_index = (now + _KEYWORD_INDEX_SECONDS, vectors, idf)
        _expires, vectors, idf = self._keyword_index
        query = query_sparse_vector(question)["indices"]
        scored = [
            (sum(weights.get(index, 0.0) * idf.get(index, 0.0) for index in query), point)
            for point, weights in vectors
        ]
        scored = [item for item in scored if item[0] > 0]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [point for _score, point in scored[:limit]]

    async def health(self) -> dict:
        exists = await self.client.collection_exists(self.collection)
        count = 0
        if exists:
            count = (await self.client.count(self.collection)).count
        return {"exists": exists, "collection": self.collection, "points": count}

    async def close(self):
        await self.client.close()
