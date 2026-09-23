import hashlib
import html
import json
import os
import re
from uuid import NAMESPACE_URL, uuid5

from langchain_core.documents import Document
from qdrant_client import AsyncQdrantClient, models


def plain_text(value, limit=6000):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))).strip()[:limit]


def product_document(product: dict) -> Document:
    text = "\n".join([
        f"Tên: {plain_text(product.get('name'))}",
        f"Mô tả: {plain_text(product.get('description'), 2500)}",
        f"Chi tiết: {plain_text(product.get('detail'), 6000)}",
        "Biến thể: " + "; ".join(plain_text(v.get("name"), 100) for v in product.get("variants", [])[:50]),
    ])
    return Document(page_content=text, metadata={
        "productId": str(product["_id"]), "shopId": str(product.get("shopId", "")),
        "categoryId": str(product.get("categoryId") or ""),
    })


def image_records(product: dict, limit: int) -> list[dict]:
    records = [{"url": url, "variantId": ""} for url in product.get("images", []) if url]
    records += [{"url": v["imageUrl"], "variantId": str(v.get("_id", ""))}
                for v in product.get("variants", []) if v.get("imageUrl")]
    seen = set()
    result = []
    for item in records:
        key = (item["url"], item["variantId"])
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result[:limit]


def content_hash(product: dict, max_images: int) -> str:
    data = {"document": product_document(product).model_dump(), "images": image_records(product, max_images)}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def point_id(product_id: str, key="text") -> str:
    return str(uuid5(NAMESPACE_URL, f"catalog:{product_id}:{key}"))


class VectorCatalog:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
        self.collection = settings.collection

    async def ensure(self, dimensions: int):
        if not await self.client.collection_exists(self.collection):
            await self.client.create_collection(self.collection, vectors_config=models.VectorParams(
                size=dimensions, distance=models.Distance.COSINE,
            ))
            for field in ("productId", "kind", "categoryId", "shopId"):
                await self.client.create_payload_index(self.collection, field, models.PayloadSchemaType.KEYWORD)
        else:
            info = await self.client.get_collection(self.collection)
            if info.config.params.vectors.size != dimensions:
                raise RuntimeError("Embedding dimension mismatch: use a new collection version")

    async def upsert(self, points: list[models.PointStruct]):
        await self.client.upsert(self.collection, points=points, wait=True)

    async def delete_product(self, product_id: str, keep: list[str] | None = None):
        selector = models.Filter(must=[models.FieldCondition(key="productId", match=models.MatchValue(value=product_id))])
        if keep:
            selector.must_not = [models.HasIdCondition(has_id=keep)]
        await self.client.delete(self.collection, points_selector=models.FilterSelector(filter=selector), wait=True)

    async def product_ids(self) -> set[str]:
        result, offset = set(), None
        while True:
            points, offset = await self.client.scroll(self.collection, limit=256, offset=offset,
                                                     with_payload=["productId"], with_vectors=False)
            result.update(p.payload["productId"] for p in points)
            if offset is None:
                return result

    async def query(self, vector, *, kind=None, exclude=None, category=None, offset=0, limit=80):
        must = []
        for key, value in (("kind", kind), ("categoryId", category)):
            if value:
                must.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))
        query_filter = models.Filter(must=must)
        if exclude:
            query_filter.must_not = [models.FieldCondition(key="productId", match=models.MatchValue(value=exclude))]
        result = await self.client.query_points(self.collection, query=vector, query_filter=query_filter,
                                               with_payload=True, limit=limit, offset=offset,
                                               score_threshold=float(os.getenv(
                                                   "CHATBOT_SIMILAR_MIN_SCORE" if exclude else "CHATBOT_MIN_SCORE",
                                                   "0.5" if exclude else "0.35")))
        return result.points

    async def source_visuals(self, product_id):
        points, _ = await self.client.scroll(self.collection, limit=3, with_vectors=False,
            scroll_filter=models.Filter(must=[
                models.FieldCondition(key="productId", match=models.MatchValue(value=product_id)),
                models.FieldCondition(key="kind", match=models.MatchValue(value="image_description")),
            ]))
        return [p.payload["text"] for p in points]

    async def close(self):
        await self.client.close()


def eligible_cards(products, stock, ids, plan, exclude=None):
    by_id = {str(p["_id"]): p for p in products}
    cards = []
    for product_id in ids:
        product = by_id.get(product_id)
        if not product or product_id == exclude or product.get("moderationStatus") != "approved":
            continue
        if plan.get("shop_id") and str(product.get("shopId")) != plan["shop_id"]:
            continue
        offers = product.get("variants") or [product]
        matching = []
        for offer in offers:
            variant_id = str(offer.get("_id", "")) if product.get("variants") else ""
            available = stock.get((product_id, variant_id))
            # No inventory row is unknown, never assert that this offer is available.
            if available is None or float(available) <= 0:
                continue
            price = float(offer.get("price", product.get("price", 0)))
            if plan.get("min_price") is not None and price < plan["min_price"]:
                continue
            if plan.get("max_price") is not None and price > plan["max_price"]:
                continue
            terms = [plain_text(t).casefold() for t in plan.get("variant_terms", [])]
            offer_name = plain_text(offer.get("name", "")).casefold()
            if terms and not all(re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", offer_name) for t in terms):
                continue
            matching.append({"id": variant_id or None, "name": offer.get("name", ""), "price": price,
                             "availableStock": available, "imageUrl": offer.get("imageUrl", "")})
        if not matching:
            continue
        best = min(matching, key=lambda v: v["price"])
        cards.append({
            "id": product_id, "name": product["name"], "price": best["price"],
            "imageUrl": best["imageUrl"] or next(iter(product.get("images", [])), ""),
            "shopId": str(product.get("shopId", "")), "url": f"/product/{product_id}",
            "sold": max(0, int(product.get("sold", 0) or 0)),
            "description": plain_text(product.get("description"), 800),
            "detail": plain_text(product.get("detail"), 1600), "variants": matching[:20],
        })
    return cards
