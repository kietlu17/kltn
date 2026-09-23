"""Independent Qdrant collection for customer-service policy documents."""
import hashlib
import os
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import AsyncQdrantClient, models


class PolicyCatalog:
    def __init__(self, settings, client=None):
        self.client = client or AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
        fingerprint = hashlib.sha256(
            f"v1:policy:{settings.embedding_model}:{settings.embedding_dimensions}".encode()
        ).hexdigest()[:12]
        self.collection = f"policies_{fingerprint}"
        self.dimensions = settings.embedding_dimensions

    async def ensure(self):
        if not await self.client.collection_exists(self.collection):
            await self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(size=self.dimensions, distance=models.Distance.COSINE),
            )
            for field in ("sourceUrl", "articleId"):
                await self.client.create_payload_index(
                    self.collection, field, models.PayloadSchemaType.KEYWORD
                )

    async def replace_source(self, source_url, chunks, vectors):
        await self.ensure()
        await self.client.delete(
            self.collection,
            points_selector=models.FilterSelector(filter=models.Filter(must=[
                models.FieldCondition(key="sourceUrl", match=models.MatchValue(value=source_url))
            ])),
            wait=True,
        )
        points = []
        for chunk, vector in zip(chunks, vectors):
            point = str(uuid5(NAMESPACE_URL, f"policy:{source_url}:{chunk['index']}:{chunk['hash']}"))
            points.append(models.PointStruct(id=point, vector=vector, payload=chunk))
        if points:
            await self.client.upsert(self.collection, points=points, wait=True)
        return len(points)

    async def query(self, vector, limit=6):
        if not await self.client.collection_exists(self.collection):
            return []
        result = await self.client.query_points(
            self.collection,
            query=vector,
            limit=limit,
            with_payload=True,
            score_threshold=float(os.getenv("CHATBOT_POLICY_MIN_SCORE", "0.3")),
        )
        return result.points

    async def count(self):
        if not await self.client.collection_exists(self.collection):
            return 0
        return (await self.client.count(self.collection)).count

    async def close(self):
        await self.client.close()
