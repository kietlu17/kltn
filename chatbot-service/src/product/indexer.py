"""Event-driven product text/caption indexing with an explicit repair mode."""
import asyncio
import hashlib
import logging
import os
import re
import sqlite3
import time
from pathlib import Path

from qdrant_client import models

from .catalog import (
    VectorCatalog,
    content_hash,
    image_records,
    metadata_hash,
    point_id,
    product_document,
    product_documents,
    product_metadata,
    variant_metadata,
)
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
        self._last_embedding_batch_at = 0.0
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
        for key in ("title", "text"):
            points = await self.vectors.client.retrieve(
                self.settings.collection,
                ids=[point_id(product_id, key)],
                with_payload=True,
                with_vectors=False,
            )
            if points:
                return points[0].payload
        return None

    async def _prepare(self, product):
        document = product_document(product)
        product_id = document.metadata["productId"]
        fingerprint = content_hash(product, self.settings.max_images)
        records = [(key, chunk.page_content, chunk.metadata) for key, chunk in product_documents(product)]
        for image in image_records(product, min(self.settings.max_images, self.settings.max_caption_images)):
            try:
                caption = await self.caption(image["url"])
            except ValueError as error:
                log.warning("Skipping unsupported image for product %s: %s", product_id, error)
                continue
            key = "image:" + image["url"] + ":" + image["variantId"]
            records.append((key, caption, {
                **document.metadata,
                "kind": "image_description",
                "chunkType": "image",
                "imageUrl": image["url"],
                "variantId": image["variantId"],
            }))
        return document, fingerprint, records

    async def update_metadata(self, product):
        """Refresh filterable payload without spending embedding quota."""
        product_id = str(product["_id"])
        base = {**product_metadata(product), "metadataHash": metadata_hash(product)}
        selector = models.Filter(must=[
            models.FieldCondition(key="productId", match=models.MatchValue(value=product_id)),
        ])
        await self.vectors.client.set_payload(self.settings.collection, base, selector, wait=True)
        for index, variant in enumerate(product.get("variants", [])):
            variant_id = str(variant.get("_id") or index)
            variant_selector = models.Filter(must=[
                models.FieldCondition(key="productId", match=models.MatchValue(value=product_id)),
                models.FieldCondition(key="variantId", match=models.MatchValue(value=variant_id)),
            ])
            await self.vectors.client.set_payload(
                self.settings.collection,
                variant_metadata(variant, product),
                variant_selector,
                wait=True,
            )

    async def _embed_in_batches(self, texts):
        """Stay below provider per-minute content quotas and honor 429 retry hints."""
        batch_size = max(1, min(100, int(os.getenv("CHATBOT_EMBED_BATCH_SIZE", "70"))))
        interval = max(0.0, float(os.getenv("CHATBOT_EMBED_BATCH_INTERVAL_SECONDS", "0")))
        retries = max(1, int(os.getenv("CHATBOT_EMBED_RATE_LIMIT_RETRIES", "5")))
        vectors = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            for attempt in range(retries):
                remaining = interval - (time.monotonic() - self._last_embedding_batch_at)
                if remaining > 0:
                    log.info("Embedding rate limit: waiting %.1fs before the next %d chunks",
                             remaining, len(batch))
                    await asyncio.sleep(remaining)
                try:
                    vectors.extend(await self.models.embed_documents(batch))
                    self._last_embedding_batch_at = time.monotonic()
                    break
                except Exception as error:
                    message = str(error)
                    if "429" not in message and "RESOURCE_EXHAUSTED" not in message:
                        raise
                    if attempt + 1 == retries:
                        raise
                    hinted = re.search(r"retry in\s+([\d.]+)s|retryDelay['\"]?\s*:\s*['\"]?(\d+)s", message, re.I)
                    delay = max(float(next(value for value in hinted.groups() if value)) + 1 if hinted else 0,
                                interval * (attempt + 1))
                    log.warning("Embedding quota reached; retrying %d documents in %.1fs", len(batch), delay)
                    await asyncio.sleep(delay)
        return vectors

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
        embeddings = await self._embed_in_batches([record[3] for record in flattened])
        if len(embeddings) != len(flattened):
            raise RuntimeError("Product embedding batch returned an unexpected vector count")

        by_product = {}
        metadata_hashes = {str(product["_id"]): metadata_hash(product) for product in products}
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
                    "metadataHash": metadata_hashes[product_id],
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
        changed, metadata_changed, deleted, skipped = [], [], 0, 0
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
            if stored and not stored.get("chunkType"):
                # Legacy combined point remains searchable until this product's
                # new chunks have all been embedded and atomically upserted.
                await self.update_metadata(product)
                changed.append(product)
                continue
            if stored and stored.get("contentHash") == fingerprint:
                if stored.get("metadataHash") != metadata_hash(product):
                    metadata_changed.append(product)
                else:
                    skipped += 1
                continue
            changed.append(product)
        for product in metadata_changed:
            await self.update_metadata(product)
        updated = await self.index_products(changed)
        log.info(
            "Product event batch: events=%d embedded=%d metadata_updated=%d deleted=%d skipped=%d",
            len(events), updated, len(metadata_changed), deleted, skipped,
        )
        return {"events": len(events), "updated": updated, "metadataUpdated": len(metadata_changed),
                "deleted": deleted, "skipped": skipped}

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
        pending, metadata_pending = [], []
        for product in products:
            product_id = str(product["_id"])
            fingerprint = content_hash(product, self.settings.max_images)
            stored = await self._stored_payload(product_id)
            if stored and not stored.get("chunkType"):
                # Phase 1 is quota-free and completes for the whole catalog before
                # phase 2 begins embedding product chunks batch by batch.
                await self.update_metadata(product)
                pending.append(product)
                continue
            if stored and stored.get("contentHash") == fingerprint:
                if stored.get("metadataHash") != metadata_hash(product):
                    metadata_pending.append(product)
                continue
            pending.append(product)
        for product in metadata_pending:
            await self.update_metadata(product)
        if os.getenv("CHATBOT_METADATA_ONLY", "false").lower() == "true":
            log.info("Catalog metadata pass: products=%d metadata_updated=%d deleted=%d",
                     len(products), len(metadata_pending), len(existing - desired))
            return {"products": len(products), "updated": 0, "metadataUpdated": len(metadata_pending),
                    "deleted": len(existing - desired), "failed": 0}
        batch_size = max(1, int(os.getenv("CHATBOT_EVENT_BATCH_SIZE", "20")))
        changed = 0
        for start in range(0, len(pending), batch_size):
            changed += await self.index_products(pending[start:start + batch_size])
        log.info("Catalog repair: products=%d embedded=%d metadata_updated=%d deleted=%d",
                 len(products), changed, len(metadata_pending), len(existing - desired))
        return {"products": len(products), "updated": changed, "metadataUpdated": len(metadata_pending),
                "deleted": len(existing - desired), "failed": 0}


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
