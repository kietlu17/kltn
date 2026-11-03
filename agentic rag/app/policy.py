from __future__ import annotations

import hashlib

from qdrant_client import AsyncQdrantClient

from .config import AgenticSettings


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

    async def retrieve(self, question: str, limit: int = 6) -> tuple[list[dict], list[dict]]:
        if not await self.client.collection_exists(self.collection):
            return [], []
        vector = await self.models.embed_query(question)
        response = await self.client.query_points(
            self.collection,
            query=vector,
            with_payload=True,
            limit=limit,
            score_threshold=0.3,
        )
        context: list[dict] = []
        sources: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for point in response.points:
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

    async def health(self) -> dict:
        exists = await self.client.collection_exists(self.collection)
        count = 0
        if exists:
            count = (await self.client.count(self.collection)).count
        return {"exists": exists, "collection": self.collection, "points": count}

    async def close(self):
        await self.client.close()
