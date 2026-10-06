import hashlib
import html
import json
import os
import re
import unicodedata
from uuid import NAMESPACE_URL, uuid5

from langchain_core.documents import Document
from qdrant_client import AsyncQdrantClient, models


def plain_text(value, limit=6000):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))).strip()[:limit]


def normalized_text(value) -> str:
    text = unicodedata.normalize("NFD", plain_text(value).casefold()).replace("đ", "d")
    return re.sub(r"\s+", " ", "".join(char for char in text if not unicodedata.combining(char))).strip()


PRODUCT_TYPES = (
    ("ao_thun", ("ao thun", "ao phong", "t shirt", "t-shirt", "polo")),
    ("ao_so_mi", ("ao so mi",)),
    ("ao_khoac", ("ao khoac",)),
    ("balo", ("balo",)),
    ("tai_nghe", ("tai nghe", "earphone", "headphone")),
    ("tui", ("tui xach", "tui deo", "cap laptop", "cap da")),
    ("quan", ("quan ", "quan short", "quan dui")),
    ("giay", ("giay ", "sneaker", "sandal", "dep ")),
    ("dong_ho", ("dong ho",)),
    ("laptop", ("laptop", "macbook")),
    ("dien_thoai", ("dien thoai", "smartphone")),
    ("do_boi", ("do boi",)),
    ("sach", ("sach ",)),
)
COLORS = {
    "den": "den", "trang": "trang", "do": "do", "vang": "vang", "hong": "hong",
    "tim": "tim", "cam": "cam", "nau": "nau", "xam": "xam", "ghi": "ghi",
    "be": "be", "bac": "bac", "xanh": "xanh",
}
SIZE_PATTERN = re.compile(r"\b(?:size|co)\s*(xs|s|m|l|xl|xxl|xxxl|\d{1,3}(?:\.\d+)?)\b", re.I)


def _tokens_in(text: str, mapping: dict[str, str]) -> list[str]:
    return list(dict.fromkeys(value for token, value in mapping.items()
                              if re.search(rf"(?<!\w){re.escape(token)}(?!\w)", text)))


def infer_product_type(value) -> str:
    original = plain_text(value).casefold()
    if re.search(r"(?<!\w)ba\s+lô(?!\w)", original):
        return "balo"
    text = normalized_text(value)
    for product_type, terms in PRODUCT_TYPES:
        if any(term in text for term in terms):
            return product_type
    return "khac"


def product_metadata(product: dict) -> dict:
    variants = product.get("variants") or []
    searchable = " ".join([plain_text(product.get("name")), plain_text(product.get("description")),
                            *(plain_text(item.get("name")) for item in variants)])
    normalized = normalized_text(searchable)
    audience = []
    if re.search(r"(?<!\w)(nam|men)(?!\w)", normalized):
        audience.append("nam")
    if re.search(r"(?<!\w)(nu|women)(?!\w)", normalized):
        audience.append("nu")
    if "tre em" in normalized or "kid" in normalized:
        audience.append("tre_em")
    if "unisex" in normalized or not audience:
        audience.append("unisex")

    colors = _tokens_in(normalized, COLORS)
    sizes = [match.upper() for match in SIZE_PATTERN.findall(normalized)]
    prices = []
    for item in variants or [product]:
        try:
            prices.append(float(item.get("price", product.get("price", 0)) or 0))
        except (TypeError, ValueError):
            pass
    explicit_brand = plain_text(product.get("brand") or product.get("brandName"), 100)
    brand_match = re.search(r"(?:thương hiệu|brand)\s*[:\-]\s*([^.;|\n]{1,100})",
                            " ".join([plain_text(product.get("description")), plain_text(product.get("detail"))]), re.I)
    brand = explicit_brand or (plain_text(brand_match.group(1), 100) if brand_match else "")
    return {
        "productType": infer_product_type(product.get("name", "")),
        "audience": list(dict.fromkeys(audience)),
        "brand": brand,
        "colors": colors,
        "sizes": list(dict.fromkeys(sizes)),
        "minPrice": min(prices, default=0.0),
        "maxPrice": max(prices, default=0.0),
    }


def metadata_hash(product: dict) -> str:
    data = {
        "base": product_metadata(product),
        "variants": [variant_metadata(item, product) for item in product.get("variants", [])],
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def variant_metadata(variant: dict, product: dict) -> dict:
    text = normalized_text(variant.get("name", ""))
    try:
        price = float(variant.get("price", product.get("price", 0)) or 0)
    except (TypeError, ValueError):
        price = 0.0
    return {
        "variantId": str(variant.get("_id", "")),
        "colors": _tokens_in(text, COLORS),
        "sizes": list(dict.fromkeys(match.upper() for match in SIZE_PATTERN.findall(text))),
        "price": price,
    }


def product_document(product: dict) -> Document:
    text = "\n".join([
        f"Tên: {plain_text(product.get('name'))}",
        f"Mô tả: {plain_text(product.get('description'), 2500)}",
        f"Chi tiết: {plain_text(product.get('detail'), 6000)}",
        "Biến thể: " + "; ".join(plain_text(v.get("name"), 100) for v in product.get("variants", [])[:50]),
    ])
    return Document(page_content=text, metadata={
        "productId": str(product["_id"]), "shopId": str(product.get("shopId", "")),
        "categoryId": str(product.get("categoryId") or ""), **product_metadata(product),
    })


def product_documents(product: dict) -> list[tuple[str, Document]]:
    """Create stable, independently searchable chunks for one product."""
    base = product_document(product).metadata
    chunks = [("title", Document(page_content=f"Tên sản phẩm: {plain_text(product.get('name'))}",
                                  metadata={**base, "kind": "text", "chunkType": "title"}))]
    description = plain_text(product.get("description"), 2500)
    detail = plain_text(product.get("detail"), 6000)
    description_text = "\n".join(part for part in (
        f"Mô tả: {description}" if description else "",
        f"Chi tiết: {detail}" if detail else "",
    ) if part)
    if description_text:
        chunks.append(("description", Document(
            page_content=description_text,
            metadata={**base, "kind": "text", "chunkType": "description"},
        )))
    for index, variant in enumerate(product.get("variants", [])):
        variant_id = str(variant.get("_id") or index)
        variant_meta = variant_metadata(variant, product)
        text = f"Biến thể của {plain_text(product.get('name'))}: {plain_text(variant.get('name'), 300)}"
        chunks.append((f"variant:{variant_id}", Document(
            page_content=text,
            metadata={**base, **variant_meta, "kind": "text", "chunkType": "variant"},
        )))
    return chunks


def query_metadata(plan: dict) -> dict:
    query = normalized_text(plan.get("query", ""))
    product_type = infer_product_type(query)
    audiences = []
    if re.search(r"(?<!\w)nam(?!\w)", query):
        audiences = ["nam", "unisex"]
    elif re.search(r"(?<!\w)nu(?!\w)", query):
        audiences = ["nu", "unisex"]
    terms = " ".join(normalized_text(term) for term in plan.get("variant_terms", []))
    return {
        "product_type": None if product_type == "khac" else product_type,
        "audiences": audiences,
        "colors": _tokens_in(terms, COLORS),
        "sizes": list(dict.fromkeys(match.upper() for match in SIZE_PATTERN.findall(
            " ".join(f"size {term}" for term in plan.get("variant_terms", []))
        ))),
        "min_price": plan.get("min_price"),
        "max_price": plan.get("max_price"),
    }


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
    # Filter metadata (especially prices) can change without changing embedding text.
    data = {"document": product_document(product).page_content, "images": image_records(product, max_images)}
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
        else:
            info = await self.client.get_collection(self.collection)
            if info.config.params.vectors.size != dimensions:
                raise RuntimeError("Embedding dimension mismatch: use a new collection version")
        for field in ("productId", "kind", "chunkType", "categoryId", "shopId", "productType",
                      "audience", "brand", "colors", "sizes", "variantId"):
            await self.client.create_payload_index(self.collection, field, models.PayloadSchemaType.KEYWORD)
        for field in ("minPrice", "maxPrice", "price"):
            await self.client.create_payload_index(self.collection, field, models.PayloadSchemaType.FLOAT)

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

    async def query(self, vector, *, kind=None, exclude=None, category=None, metadata=None, offset=0, limit=80):
        must = []
        for key, value in (("kind", kind), ("categoryId", category)):
            if value:
                must.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))
        metadata = metadata or {}
        for key, value in (("productType", metadata.get("product_type")),
                           ("colors", metadata.get("colors")), ("sizes", metadata.get("sizes"))):
            if value:
                match = models.MatchAny(any=value) if isinstance(value, list) else models.MatchValue(value=value)
                must.append(models.FieldCondition(key=key, match=match))
        if metadata.get("audiences"):
            must.append(models.FieldCondition(key="audience", match=models.MatchAny(any=metadata["audiences"])))
        if metadata.get("max_price") is not None:
            must.append(models.FieldCondition(key="minPrice", range=models.Range(lte=metadata["max_price"])))
        if metadata.get("min_price") is not None:
            must.append(models.FieldCondition(key="maxPrice", range=models.Range(gte=metadata["min_price"])))
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
