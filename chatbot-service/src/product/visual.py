"""Direct image vector space, deliberately separate from Qwen text embeddings."""
import hashlib
import math
import os

import httpx
from qdrant_client import models

from .catalog import VectorCatalog

IMAGE_MODEL = "openai/clip-vit-base-patch32"
IMAGE_REVISION = "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"


def image_identity():
    return f"clip-image-v1:{os.getenv('CHATBOT_IMAGE_MODEL', IMAGE_MODEL)}:{os.getenv('CHATBOT_IMAGE_REVISION', IMAGE_REVISION)}"


class VisualCatalog(VectorCatalog):
    def __init__(self, settings, client=None):
        super().__init__(settings, client)
        self.identity = image_identity()
        self.collection = "catalog_images_" + hashlib.sha256(self.identity.encode()).hexdigest()[:12]
        self.encoder = httpx.AsyncClient(base_url=os.getenv("CHATBOT_IMAGE_EMBED_URL", "http://image-embedding:3022"), timeout=120)

    async def exists(self):
        return await self.client.collection_exists(self.collection)

    async def embed(self, image):
        response = await self.encoder.post("/embed", json={"image": image})
        response.raise_for_status()
        body = response.json()
        if body.get("identity") != self.identity:
            raise RuntimeError("Image embedding model/version mismatch")
        vector = body["embedding"]
        if len(vector) != 512 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vector):
            raise RuntimeError("Invalid image embedding")
        return vector

    async def query(self, vector, *, exclude=None, category=None):
        must = [models.FieldCondition(key="categoryId", match=models.MatchValue(value=category))] if category else []
        exclude_filter = [models.FieldCondition(key="productId", match=models.MatchValue(value=exclude))] if exclude else []
        result = await self.client.query_points(self.collection, query=vector,
            query_filter=models.Filter(must=must, must_not=exclude_filter), limit=80, with_payload=True,
            score_threshold=float(os.getenv("CHATBOT_IMAGE_MIN_SCORE", "0.65")))
        return result.points

    async def source_vectors(self, product_id):
        if not await self.exists():
            return []
        points, _ = await self.client.scroll(self.collection, limit=3, with_vectors=True,
            scroll_filter=models.Filter(must=[models.FieldCondition(key="productId", match=models.MatchValue(value=product_id))]))
        return [p.vector for p in points]

    async def close(self):
        await self.encoder.aclose()
        await super().close()
