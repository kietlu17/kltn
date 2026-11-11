"""Search by photo over the CLIP image collection.

Product photos are embedded by the local model server (CLIP ViT-B/32, 512-d)
into ``catalog_images_<hash>``; this module embeds the shopper's photo the same
way and returns the closest products, best image per product.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import math
import re

import httpx
from qdrant_client import AsyncQdrantClient, models

from .config import AgenticSettings

_DATA_URL = re.compile(r"^data:image/(?:jpeg|jpg|png|webp);base64,", re.I)
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class InvalidImage(ValueError):
    pass


def image_payload(image: str) -> str:
    """Bare base64 from a data URL or base64 string, size-checked."""
    encoded = _DATA_URL.sub("", image.strip())
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise InvalidImage("Ảnh không hợp lệ.") from error
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise InvalidImage("Ảnh trống hoặc lớn hơn 5 MB.")
    return encoded


class VisualSearch:
    def __init__(
        self,
        settings: AgenticSettings,
        client: AsyncQdrantClient | None = None,
        encoder: httpx.AsyncClient | None = None,
    ):
        self.settings = settings
        # Must match the indexer's identity, or vectors from another model
        # would be compared with this one.
        self.identity = f"clip-image-v1:{settings.image_model}:{settings.image_revision}"
        self.collection = "catalog_images_" + hashlib.sha256(self.identity.encode()).hexdigest()[:12]
        self.client = client or AsyncQdrantClient(url=settings.qdrant_url, timeout=settings.request_timeout)
        self.encoder = encoder or httpx.AsyncClient(
            base_url=settings.model_server_url, timeout=settings.image_timeout
        )

    async def embed(self, image: str) -> list[float]:
        response = await self.encoder.post("/embed", json={"image": image_payload(image)})
        if response.status_code == 400:
            raise InvalidImage("Không đọc được ảnh, bạn thử ảnh JPG/PNG khác nhé.")
        response.raise_for_status()
        body = response.json()
        if body.get("identity") != self.identity:
            raise RuntimeError("Image embedding model/version mismatch")
        vector = body.get("embedding") or []
        if len(vector) != 512 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vector):
            raise RuntimeError("Invalid image embedding")
        return vector

    async def search(self, image: str, limit: int) -> list[dict]:
        """Hits shaped like text retrieval hits: one per product, best image."""
        if not await self.client.collection_exists(self.collection):
            return []
        vector = await self.embed(image)
        response = await self.client.query_points_groups(
            self.collection,
            query=vector,
            group_by="productId",
            group_size=1,
            limit=limit,
            score_threshold=self.settings.image_min_score,
            with_payload=["productId", "variantId", "imageUrl"],
        )
        hits = []
        for group in response.groups:
            best = group.hits[0]
            hits.append({
                "productId": str(group.id),
                "vectorScore": round(float(best.score), 4),
                "sources": ["image"],
                "variantId": (best.payload or {}).get("variantId") or None,
            })
        return hits

    async def health(self) -> dict:
        exists = await self.client.collection_exists(self.collection)
        products = 0
        if exists:
            facet = await self.client.facet(self.collection, key="productId", limit=100000, exact=False)
            products = len(facet.hits)
        return {"exists": exists, "collection": self.collection, "products": products}

    async def close(self):
        await self.encoder.aclose()
        await self.client.close()
