"""Event-driven product text/caption indexing with an explicit repair mode."""
import asyncio
import hashlib
import logging
import os
import sqlite3
from pathlib import Path

from qdrant_client import models

from .catalog import VectorCatalog, content_hash, image_records, point_id, product_document
from .events import consume_product_events
from ..core.settings import Settings
from ..infrastructure.clients import CatalogAPI
from ..infrastructure.models import ModelClients

log = logging.getLogger(__name__)


class CatalogIndexer:
    def __init__(self, settings, api, models, vectors):
        self.settings, self.api, self.models, self.vectors = settings, api, models, vectors
        Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(settings.data_dir) / "index.sqlite"))
        self.db.execute("CREATE TABLE IF NOT EXISTS manifest (namespace TEXT, id TEXT, hash TEXT, PRIMARY KEY(namespace,id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS captions (id TEXT PRIMARY KEY, text TEXT)")

    async def caption(self, url):
        image = await self.api.image(url)
        key = hashlib.sha256((self.settings.gemini_model + ":langchain-v1:" + image).encode()).hexdigest()
        cached = self.db.execute("SELECT text FROM captions WHERE id=?", (key,)).fetchone()
        if cached:
            return cached[0]
        text = await self.models.describe(image)
        self.db.execute("INSERT OR REPLACE INTO captions VALUES (?,?)", (key, text))
        self.db.commit()
        return text

    async def _stored_payload(self, product_id):
        if not await self.vectors.client.collection_exists(self.settings.collection):
            return None
        points = await self.vectors.client.retrieve(
            self.settings.collection,
            ids=[point_id(product_id)],
            with_payload=True,
            with_vectors=False,
        )
        return points[0].payload if points else None

    async def _prepare(self, product):
        document = product_document(product)
        product_id = document.metadata["productId"]
        fingerprint = content_hash(product, self.settings.max_images)
        records = [("text", document.page_content, {"kind": "text"})]
        for image in image_records(product, min(self.settings.max_images, self.settings.max_caption_images)):
            try:
                caption = await self.caption(image["url"])
            except ValueError as error:
                log.warning("Skipping unsupported image for product %s: %s", product_id, error)
                continue
            key = "image:" + image["url"] + ":" + image["variantId"]
            records.append((key, caption, {
                "kind": "image_description",
                "imageUrl": image["url"],
                "variantId": image["variantId"],
            }))
        return document, fingerprint, records

    async def index_products(self, products):
        """Embed all records for the changed products in one provider batch."""
        if not products:
            return 0
        prepared = [await self._prepare(product) for product in products]
        flattened = [
            (document, fingerprint, key, text, metadata)
            for document, fingerprint, records in prepared
            for key, text, metadata in records
        ]
        await self.vectors.ensure(self.settings.embedding_dimensions)
        embeddings = await self.models.embed_documents([record[3] for record in flattened])
        if len(embeddings) != len(flattened):
            raise RuntimeError("Product embedding batch returned an unexpected vector count")

        by_product = {}
        for (document, fingerprint, key, text, metadata), vector in zip(flattened, embeddings):
            product_id = document.metadata["productId"]
            point = models.PointStruct(
                id=point_id(product_id, key),
                vector=vector,
                payload={
                    **document.metadata,
                    **metadata,
                    "text": text,
                    "contentHash": fingerprint,
                    "embeddingModel": self.settings.embedding_model,
                },
            )
            by_product.setdefault(product_id, []).append(point)

        await self.vectors.upsert([point for points in by_product.values() for point in points])
        for product_id, points in by_product.items():
            await self.vectors.delete_product(product_id, keep=[str(point.id) for point in points])
            self.db.execute(
                "INSERT OR REPLACE INTO manifest VALUES (?,?,?)",
                (self.settings.collection, product_id, points[0].payload["contentHash"]),
            )
        self.db.commit()
        return len(by_product)

    async def index_product(self, product):
        return await self.index_products([product])

    async def process_events(self, events):
        changed, deleted, skipped = [], 0, 0
        for topic, product_id in events:
            if topic == "product.deleted":
                await self.vectors.delete_product(product_id)
                deleted += 1
                continue
            product = await self.api.product(product_id)
            if product is None:
                await self.vectors.delete_product(product_id)
                deleted += 1
                continue
            stored = await self._stored_payload(product_id)
            fingerprint = content_hash(product, self.settings.max_images)
            # Existing vectors are authoritative for duplicate create events. Updated
            # events without a hash migrate that one product to the new payload format.
            if stored and (topic == "product.created" or stored.get("contentHash") == fingerprint):
                skipped += 1
                continue
            changed.append(product)
        updated = await self.index_products(changed)
        log.info(
            "Product event batch: events=%d updated=%d deleted=%d skipped=%d",
            len(events), updated, deleted, skipped,
        )
        return {"events": len(events), "updated": updated, "deleted": deleted, "skipped": skipped}

    async def reconcile(self):
        products = await self.api.all_products()  # Fail before deleting if any page is unavailable.
        await self.vectors.ensure(self.settings.embedding_dimensions)
        existing = await self.vectors.product_ids()
        desired = {str(p["_id"]) for p in products}
        # Purge first so slow image processing does not delay moderation/deletion removal.
        for product_id in existing - desired:
            await self.vectors.delete_product(product_id)
            self.db.execute("DELETE FROM manifest WHERE namespace=? AND id=?", (self.settings.collection, product_id))
        self.db.commit()
        pending = []
        for product in products:
            product_id = str(product["_id"])
            fingerprint = content_hash(product, self.settings.max_images)
            stored = await self._stored_payload(product_id)
            # Trust legacy Qdrant vectors that predate contentHash. Future update
            # events migrate only the affected product.
            if stored and (not stored.get("contentHash") or stored.get("contentHash") == fingerprint):
                continue
            pending.append(product)
        batch_size = max(1, int(os.getenv("CHATBOT_EVENT_BATCH_SIZE", "20")))
        changed = 0
        for start in range(0, len(pending), batch_size):
            changed += await self.index_products(pending[start:start + batch_size])
        log.info("Catalog repair: products=%d updated=%d deleted=%d",
                 len(products), changed, len(existing - desired))
        return {"products": len(products), "updated": changed, "deleted": len(existing - desired), "failed": 0}


async def main():
    settings = Settings()
    api, models, vectors = CatalogAPI(settings), ModelClients(settings), VectorCatalog(settings)
    indexer = CatalogIndexer(settings, api, models, vectors)
    try:
        if os.getenv("CHATBOT_INDEX_ONCE") == "true":
            await indexer.reconcile()
        else:
            await vectors.ensure(settings.embedding_dimensions)
            await consume_product_events("chatbot-catalog-indexer", indexer.process_events)
    finally:
        indexer.db.close()
        await api.close()
        await models.close()
        await vectors.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
