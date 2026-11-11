"""Second-stage ranking.

Hybrid search (dense + BM25, fused by RRF) is a fast first stage that scores
query and product independently. Two second stages refine its short list:

* the multilingual cross-encoder on the local model server reads query and
  candidate together. Its probability is blended with the hybrid rank, which
  keeps the first-stage signal when the small model is unsure about
  Vietnamese product titles, and an adaptive cut-off decides how many
  candidates are worth showing instead of always padding to top-k;
* the LLM judge (``ProductAgent._judge`` -> ``rank_candidates``) grades the
  cross-encoder's short list against the customer's need and decides the
  final top-k when the chat model is available (AGENTIC_RERANK_MODE=llm).

Any failure keeps the previous order.
"""

from __future__ import annotations

import logging
import math
import re

import httpx

from .config import AgenticSettings

log = logging.getLogger(__name__)
_MAX_DOCUMENT_CHARS = 480


def _clean(value) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", str(value or ""))).strip()


def _price_label(product: dict) -> str:
    prices = [
        float(variant.get("price") or 0)
        for variant in product.get("variants", []) or []
        if variant.get("price")
    ] or ([float(product["price"])] if product.get("price") else [])
    if not prices:
        return ""
    low, high = min(prices), max(prices)
    text = lambda value: f"{value:,.0f}".replace(",", ".") + "đ"  # noqa: E731
    return f"giá {text(low)}" if low == high else f"giá {text(low)} - {text(high)}"


def product_document(product: dict, limit: int = _MAX_DOCUMENT_CHARS) -> str:
    """Name first: it is the strongest signal and must survive truncation.

    Category, brand, price, key specifications and variant names follow, so
    the second stage can tell "ốp lưng iPhone" from "iPhone" and "16GB RAM"
    from "16GB storage" without reading the whole description.
    """
    parts = [_clean(product.get("name"))]
    for key in ("categoryName", "brand"):
        if product.get(key):
            parts.append(_clean(product[key]))
    if price := _price_label(product):
        parts.append(price)
    specs = [
        f"{_clean(item.get('name') or item.get('key'))}: {_clean(item.get('value'))}"
        for item in (product.get("specifications") or [])[:6]
        if isinstance(item, dict) and item.get("value")
    ]
    if specs:
        parts.append("; ".join(specs))
    variants = [
        _clean(variant.get("name"))
        for variant in (product.get("variants") or [])[:6]
        if variant.get("name") and _clean(variant.get("name")) != parts[0]
    ]
    if variants:
        parts.append("biến thể: " + ", ".join(variants))
    description = _clean(product.get("description"))
    if description:
        parts.append(description)
    return " | ".join(part for part in parts if part)[:limit]


def _sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-max(min(value, 30), -30)))


def adaptive_top_k(products: list[dict], limit: int, cutoff: float, minimum: int = 1) -> list[dict]:
    """Keep at most ``limit`` products, dropping those the cross-encoder
    scored far below the best one. Without scores, or when even the best
    candidate looks irrelevant (the model is then unreliable rather than
    decisive), the first ``limit`` are kept."""
    head = products[:limit]
    probabilities = [item.get("rerankProb") for item in head]
    if not head or any(value is None for value in probabilities):
        return head
    best = max(probabilities)
    if best < 0.2:
        return head
    kept = [item for item in head if item["rerankProb"] >= best * cutoff]
    return kept if len(kept) >= minimum else head[:minimum]


class CrossEncoderReranker:
    def __init__(self, settings: AgenticSettings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(
            base_url=settings.model_server_url, timeout=settings.rerank_timeout
        )

    async def rerank(self, query: str, products: list[dict]) -> list[dict]:
        """Products ordered by a blend of cross-encoder probability and hybrid
        rank; the input order on failure."""
        if not self.settings.rerank_enabled or len(products) < 2 or not query.strip():
            return products
        candidates = products[: self.settings.rerank_candidates]
        try:
            response = await self.client.post(
                "/rerank",
                json={"query": query, "documents": [product_document(item) for item in candidates]},
                timeout=self.settings.rerank_timeout,
            )
            response.raise_for_status()
            scores = response.json()["scores"]
            if len(scores) != len(candidates):
                raise ValueError("score count mismatch")
        except Exception as error:
            log.warning("Re-rank skipped, keeping hybrid order: %s: %s", type(error).__name__, error)
            return products
        weight = getattr(self.settings, "rerank_weight", 0.75)
        count = len(candidates)
        ranked = []
        for index, (score, product) in enumerate(zip(scores, candidates)):
            probability = _sigmoid(float(score))
            first_stage = 1 - index / count
            blended = weight * probability + (1 - weight) * first_stage
            ranked.append((blended, index, {
                **product,
                "rerankScore": round(float(score), 4),
                "rerankProb": round(probability, 4),
            }))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in ranked] + products[count:]

    async def close(self):
        await self.client.aclose()
