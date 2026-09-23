"""One worker: Kafka wakeups + periodic full reconciliation, idempotent Qdrant writes."""
import asyncio
import hashlib
import json
import logging
import os
import sqlite3
from pathlib import Path

from aiokafka import AIOKafkaConsumer
from qdrant_client import models

from .catalog import VectorCatalog, content_hash, image_records, point_id, product_document
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

    async def index_text(self, product):
        document = product_document(product)
        embedding = (await self.models.embed_documents([document.page_content]))[0]
        await self.vectors.ensure(len(embedding))
        await self.vectors.upsert([models.PointStruct(
            id=point_id(document.metadata["productId"]), vector=embedding,
            payload={**document.metadata, "kind": "text", "text": document.page_content},
        )])

    async def index_product(self, product):
        document = product_document(product)
        product_id = document.metadata["productId"]
        records = [("text", document.page_content, {"kind": "text"})]
        complete = True
        for image in image_records(product, self.settings.max_images):
            try:
                caption = await self.caption(image["url"])
                key = "image:" + image["url"] + ":" + image["variantId"]
                records.append((key, caption, {"kind": "image_description", "imageUrl": image["url"],
                                               "variantId": image["variantId"]}))
            except Exception:
                complete = False
                log.exception("Could not index an image for product %s; will retry", product_id)
        embeddings = await self.models.embed_documents([record[1] for record in records])
        await self.vectors.ensure(len(embeddings[0]))
        points = [models.PointStruct(id=point_id(product_id, key), vector=vector,
                                    payload={**document.metadata, **metadata, "text": text})
                  for (key, text, metadata), vector in zip(records, embeddings)]
        await self.vectors.upsert(points)
        # Remove stale image/variant records, including after a product loses images.
        await self.vectors.delete_product(product_id, keep=[str(p.id) for p in points])
        if complete:
            self.db.execute("INSERT OR REPLACE INTO manifest VALUES (?,?,?)",
                            (self.settings.collection, product_id, content_hash(product, self.settings.max_images)))
            self.db.commit()

    async def reconcile(self):
        products = await self.api.all_products()  # Fail before deleting if any page is unavailable.
        probe = await self.models.embed_documents(["kiểm tra chỉ mục sản phẩm"])
        await self.vectors.ensure(len(probe[0]))
        existing = await self.vectors.product_ids()
        desired = {str(p["_id"]) for p in products}
        # Purge first so slow image processing does not delay moderation/deletion removal.
        for product_id in existing - desired:
            await self.vectors.delete_product(product_id)
            self.db.execute("DELETE FROM manifest WHERE namespace=? AND id=?", (self.settings.collection, product_id))
        self.db.commit()
        changed, failed = 0, 0
        pending = []
        for product in products:
            product_id = str(product["_id"])
            fingerprint = content_hash(product, self.settings.max_images)
            cached = self.db.execute("SELECT hash FROM manifest WHERE namespace=? AND id=?",
                                     (self.settings.collection, product_id)).fetchone()
            if product_id in existing and cached and cached[0] == fingerprint:
                continue
            try:
                await self.index_text(product)
                pending.append(product)
            except Exception:
                failed += 1
                log.exception("Could not index product %s; will retry", product_id)
        log.info("Text catalog ready; processing images for %d changed products", len(pending))
        for product in pending:
            try:
                await self.index_product(product)
                changed += 1
            except Exception:
                failed += 1
                log.exception("Could not finish image indexing for %s; will retry", product["_id"])
        log.info("Catalog reconciliation: products=%d updated=%d deleted=%d failed=%d",
                 len(products), changed, len(existing - desired), failed)
        return {"products": len(products), "updated": changed, "deleted": len(existing - desired), "failed": failed}


async def kafka_wakeups(wakeup: asyncio.Event):
    broker = os.getenv("KAFKA_BROKER")
    if not broker:
        return
    while True:
        consumer = AIOKafkaConsumer(
            "product.created", "product.updated", bootstrap_servers=broker,
            group_id="chatbot-catalog-indexer", auto_offset_reset="latest",
        )
        try:
            await consumer.start()
            async for _ in consumer:
                # Events are hints; reconciliation reads authoritative data and retries independently.
                wakeup.set()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Kafka unavailable; periodic reconciliation remains active")
        finally:
            await consumer.stop()
        await asyncio.sleep(15)


async def main():
    settings = Settings()
    api, models, vectors = CatalogAPI(settings), ModelClients(settings), VectorCatalog(settings)
    indexer = CatalogIndexer(settings, api, models, vectors)
    retry_seconds = max(1, int(os.getenv("CHATBOT_INDEX_RETRY_SECONDS", "15")))
    wakeup = asyncio.Event()
    kafka_task = asyncio.create_task(kafka_wakeups(wakeup))
    try:
        while True:
            wakeup.clear()
            reconciled = False
            try:
                await indexer.reconcile()
                reconciled = True
            except Exception:
                log.exception(
                    "Reconciliation failed; preserving index and retrying in %ss",
                    retry_seconds,
                )
            if os.getenv("CHATBOT_INDEX_ONCE") == "true":
                break
            try:
                timeout = max(10, settings.sync_seconds) if reconciled else retry_seconds
                await asyncio.wait_for(wakeup.wait(), timeout=timeout)
                if reconciled:
                    await asyncio.sleep(3)  # Coalesce bursts of product events.
            except asyncio.TimeoutError:
                pass
    finally:
        kafka_task.cancel()
        await asyncio.gather(kafka_task, return_exceptions=True)
        indexer.db.close()
        await api.close()
        await models.close()
        await vectors.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
