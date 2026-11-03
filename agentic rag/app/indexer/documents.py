"""Product -> embedding-sized chunks with the payload the retriever filters on."""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from ..specs import normalize_specifications

# ~2,600 Vietnamese characters stay near 1,000 tokens, well under the
# 2,048-token input of gemini-embedding-001, while halving detail chunks.
CHUNK_MAX_CHARS = 2600
DETAIL_CHUNK_CHARS = 2400
DETAIL_OVERLAP_CHARS = 200

PRODUCT_TYPES = (
    ("ao_thun", ("ao thun", "ao phong", "t shirt", "t-shirt", "polo")),
    ("ao_so_mi", ("ao so mi",)),
    ("ao_khoac", ("ao khoac",)),
    ("balo", ("balo",)),
    ("tai_nghe", ("tai nghe", "earphone", "headphone")),
    ("loa", ("loa", "speaker")),
    ("ban_phim", ("ban phim", "keyboard")),
    ("chuot", ("chuot may tinh", "mouse")),
    ("may_tinh_bang", ("may tinh bang", "tablet", "ipad")),
    ("tui", ("tui xach", "tui deo", "cap laptop", "cap da", "tui")),
    ("quan", ("quan ", "quan short", "quan dui")),
    ("giay", ("giay ", "sneaker", "sandal", "dep ")),
    ("dong_ho", ("dong ho",)),
    ("laptop", ("laptop", "macbook")),
    ("dien_thoai", ("dien thoai", "smartphone", "iphone")),
    ("den", ("den ban", "den ngu", "den trang tri")),
    ("goi", ("goi ngu", "goi tua", "goi om")),
    ("chan", ("chan bong", "chan mong", "chan ga")),
    ("khan", ("khan tam", "khan mat", "khan lau")),
    ("binh", ("binh nuoc", "binh giu nhiet")),
    ("noi", ("noi com", "noi nau", "noi chien")),
    ("ghe", ("ghe van phong", "ghe an", "ghe gap")),
    ("sua_rua_mat", ("sua rua mat",)),
    ("do_boi", ("do boi",)),
    ("sach", ("sach ",)),
)
COLORS = {
    "den": "den", "trang": "trang", "do": "do", "vang": "vang", "hong": "hong",
    "tim": "tim", "cam": "cam", "nau": "nau", "xam": "xam", "ghi": "ghi",
    "be": "be", "bac": "bac", "xanh": "xanh",
}
SIZE_PATTERN = re.compile(r"\b(?:size|co)\s*(xs|s|m|l|xl|xxl|xxxl|\d{1,3}(?:\.\d+)?)\b", re.I)
VARIANT_SIZE_SUFFIX = re.compile(
    r"(?:(?:\s*[/,;|:-]\s*|\s+)(?:(?:size|cỡ|co)\s*)?"
    r"(xs|s|m|l|xl|xxl|xxxl|2xl|3xl)"
    r"|(?:\s*[/,;|:-]\s*|\s+(?:size|cỡ|co)\s*)(\d{1,3}(?:\.\d+)?))\s*$",
    re.I,
)


def plain_text(value, limit: int = 6000) -> str:
    text = re.sub(r"<[^>]*>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()[:limit]


def normalized_text(value) -> str:
    text = unicodedata.normalize("NFD", plain_text(value).casefold()).replace("đ", "d")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip()


def _tokens_in(text: str, mapping: dict[str, str]) -> list[str]:
    return list(
        dict.fromkeys(
            value
            for token, value in mapping.items()
            if re.search(rf"(?<!\w){re.escape(token)}(?!\w)", text)
        )
    )


def infer_product_type(value) -> str:
    original = plain_text(value).casefold()
    if re.search(r"(?<!\w)ba\s+lô(?!\w)", original):
        return "balo"
    if re.search(r"\b(?:tất(?! cả\b)|tât|tat(?! ca\b)|vớ|vo|socks?)\b", original):
        return "tat"
    text = normalized_text(value)
    for product_type, terms in PRODUCT_TYPES:
        if any(
            re.search(r"(?<!\w)" + re.escape(term.strip()) + r"(?!\w)", text)
            for term in terms
        ):
            return product_type
    return "khac"


def _price(item: dict, product: dict) -> float | None:
    try:
        return float(item.get("price", product.get("price", 0)) or 0)
    except (TypeError, ValueError):
        return None


def spec_payload(product: dict) -> list[dict]:
    """Canonical facts shared with the query side (app.specs)."""
    facts = normalize_specifications(product.get("specifications") or [])
    return [
        {
            **fact,
            "rawName": fact["rawName"][:200],
            "rawValue": fact["rawValue"][:500],
            "normalizedText": fact["normalizedText"][:700],
        }
        for fact in facts[:100]
    ]


def product_metadata(product: dict, category_name: str = "") -> dict:
    variants = product.get("variants") or []
    searchable = " ".join(
        [
            plain_text(product.get("name")),
            plain_text(product.get("description")),
            *(plain_text(item.get("name")) for item in variants),
        ]
    )
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
    prices = [
        price for item in (variants or [product]) if (price := _price(item, product)) is not None
    ]
    explicit_brand = plain_text(product.get("brand") or product.get("brandName"), 100)
    brand_match = re.search(
        r"(?:thương hiệu|brand)\s*[:\-]\s*([^.;|\n]{1,100})",
        " ".join([plain_text(product.get("description")), plain_text(product.get("detail"))]),
        re.I,
    )
    return {
        "productId": str(product["_id"]),
        "shopId": str(product.get("shopId") or ""),
        "categoryId": str(product.get("categoryId") or ""),
        "categoryName": category_name,
        "productType": infer_product_type(product.get("name", "")),
        "audience": list(dict.fromkeys(audience)),
        "brand": explicit_brand or (plain_text(brand_match.group(1), 100) if brand_match else ""),
        "colors": _tokens_in(normalized, COLORS),
        "sizes": list(dict.fromkeys(match.upper() for match in SIZE_PATTERN.findall(normalized))),
        "minPrice": min(prices, default=0.0),
        "maxPrice": max(prices, default=0.0),
        "specs": spec_payload(product),
    }


def variant_metadata(variant: dict, product: dict) -> dict:
    name = plain_text(variant.get("name", ""), 300)
    text = normalized_text(name)
    size_suffix = VARIANT_SIZE_SUFFIX.search(name)
    return {
        "colors": _tokens_in(text, COLORS),
        "sizes": list(
            dict.fromkeys(
                [
                    *(match.upper() for match in SIZE_PATTERN.findall(text)),
                    *([(size_suffix.group(1) or size_suffix.group(2)).upper()] if size_suffix else []),
                ]
            )
        ),
        "price": _price(variant, product) or 0.0,
    }


def split_text(text: str, max_chars: int, overlap: int = 0) -> list[str]:
    """Pack sentences into chunks of at most max_chars, carrying a word-aligned overlap."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    units = []
    for piece in re.split(r"(?<=[.!?;])\s+|\n+", text):
        piece = piece.strip()
        while len(piece) > max_chars:
            cut = piece.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            units.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if piece:
            units.append(piece)
    chunks, current = [], ""
    for unit in units:
        candidate = f"{current} {unit}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            tail = tail[tail.find(" ") + 1:] if " " in tail else ""
            current = f"{tail} {unit}".strip() if len(tail) + len(unit) < max_chars else unit
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def text_hash(text: str, model: str, dimensions: int) -> str:
    """Identity of one embedding; also the cache key, so a model change re-embeds."""
    return hashlib.sha256(f"{model}:{dimensions}:{text}".encode("utf-8")).hexdigest()


def point_id(product_id: str, key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"agentic:{product_id}:{key}"))


@dataclass(frozen=True)
class Chunk:
    point_id: str
    product_id: str
    text: str
    text_hash: str
    payload: dict
    payload_hash: str
    # Hash of the text whose embedding this point stores as its dense vector.
    # Equal to text_hash except for variant groups, which reuse the base one.
    dense_hash: str


def product_chunks(
    product: dict, model: str, dimensions: int, category_name: str = ""
) -> list[Chunk]:
    """Embedding-sized chunks: one base, specs, detail and one per variant color group.

    gemini-embedding-001 reads about 2048 tokens, so every chunk stays under
    CHUNK_MAX_CHARS and repeats the product name to be retrievable alone.
    Variant-group points carry their own payload (colors, sizes, prices) and
    BM25 vector, but reuse the base chunk's dense vector: their text is the
    product name plus variant names, which adds no meaning worth a quota call.
    """
    base = product_metadata(product, category_name)
    name = plain_text(product.get("name"), 300)
    title = f"Tên sản phẩm: {name}"
    description_parts = split_text(
        plain_text(product.get("description"), 2500), DETAIL_CHUNK_CHARS
    )
    detail = plain_text(product.get("detail"), 6000)
    specification_text = "; ".join(
        f"{plain_text(item.get('name'), 200)}: {plain_text(item.get('value'), 500)}"
        for item in product.get("specifications", [])[:100]
        if isinstance(item, dict)
    )
    records: list[tuple[str, str, dict]] = [
        (
            "base",
            "\n".join(
                part
                for part in (
                    title,
                    f"Thương hiệu: {base['brand']}" if base["brand"] else "",
                    f"Danh mục: {category_name}" if category_name else "",
                    f"Mô tả: {description_parts[0]}" if description_parts else "",
                )
                if part
            ),
            {"chunkType": "base"},
        )
    ]
    spec_prefix = f"{title}\nThông số: "
    for index, part in enumerate(
        split_text(specification_text, CHUNK_MAX_CHARS - len(spec_prefix))
    ):
        records.append((f"specs:{index}", spec_prefix + part, {"chunkType": "specs"}))
    detail_prefix = f"{title}\nChi tiết: "
    detail_source = " ".join([*description_parts[1:], detail]).strip()
    for index, part in enumerate(
        split_text(
            detail_source,
            min(DETAIL_CHUNK_CHARS, CHUNK_MAX_CHARS - len(detail_prefix)),
            DETAIL_OVERLAP_CHARS,
        )
    ):
        records.append((f"detail:{index}", detail_prefix + part, {"chunkType": "detail"}))

    groups: dict[tuple, dict] = {}
    for index, variant in enumerate(product.get("variants") or []):
        meta = variant_metadata(variant, product)
        group = groups.setdefault(
            tuple(sorted(meta["colors"])), {"names": set(), "ids": [], "sizes": set(), "prices": []}
        )
        variant_name = plain_text(variant.get("name"), 300)
        group["names"].add(VARIANT_SIZE_SUFFIX.sub("", variant_name).strip(" /,;|:-") or variant_name)
        group["ids"].append(str(variant.get("_id") or index))
        group["sizes"].update(meta["sizes"])
        group["prices"].append(meta["price"])
    for colors, group in sorted(groups.items()):
        group_key = "|".join(colors) or "unclassified"
        text = "\n".join(
            part
            for part in (
                title,
                f"Màu: {', '.join(colors)}" if colors else "",
                "Biến thể: " + "; ".join(sorted(group["names"])),
            )
            if part
        )
        records.append(
            (
                f"variant_group:{group_key}",
                text,
                {
                    "chunkType": "variant_group",
                    "colors": list(colors),
                    "sizes": sorted(group["sizes"]),
                    "minPrice": min(group["prices"]),
                    "maxPrice": max(group["prices"]),
                    "variantIds": group["ids"],
                    "variantGroup": group_key,
                },
            )
        )

    chunks = []
    base_hash = text_hash(records[0][1], model, dimensions)
    for key, text, extra in records:
        digest = text_hash(text, model, dimensions)
        dense = base_hash if extra["chunkType"] == "variant_group" else digest
        payload = {**base, **extra, "kind": "text", "text": text, "textHash": digest,
                   "denseHash": dense, "embeddingModel": model}
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        payload["payloadHash"] = payload_hash
        chunks.append(
            Chunk(
                point_id=point_id(base["productId"], key),
                product_id=base["productId"],
                text=text,
                text_hash=digest,
                payload=payload,
                payload_hash=payload_hash,
                dense_hash=dense,
            )
        )
    return chunks
