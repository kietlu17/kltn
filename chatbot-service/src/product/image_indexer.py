"""Event-driven MinIO/catalog image indexing with an explicit repair mode."""
import asyncio
import hashlib
import json
import logging
import os
import sqlite3
from pathlib import Path

from qdrant_client import models

from .catalog import image_records, point_id, product_document
from .events import consume_product_events
from ..core.settings import Settings
from ..infrastructure.clients import CatalogAPI
from .visual import VisualCatalog

log = logging.getLogger(__name__)


class ImageIndexer:
    def __init__(self, settings, api, visual):
        self.settings, self.api, self.visual = settings, api, visual
        Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(settings.data_dir) / "visual-index.sqlite"), timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (id TEXT PRIMARY KEY, vector TEXT)")

    def _image_set_hash(self, product):
        records = image_records(product, self.settings.max_images)
        serialized = json.dumps(records, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(f"{self.visual.identity}:{serialized}".encode()).hexdigest()

    async def _stored_payload(self, product_id):
        if not await self.visual.exists():
            return None
        points, _ = await self.visual.client.scroll(
            self.visual.collection,
            limit=1,
            with_payload=True,
            with_vectors=False,
            scroll_filter=models.Filter(must=[
                models.FieldCondition(key="productId", match=models.MatchValue(value=product_id))
            ]),
        )
        return points[0].payload if points else None

    async def index_product(self, product):
        pid = str(product["_id"])
        records = image_records(product, self.settings.max_images)
        image_set_hash = self._image_set_hash(product)
        ids = [point_id(pid, "pixel:" + record["url"] + ":" + record["variantId"]) for record in records]
        if not records:
            await self.visual.delete_product(pid)
            return {"images": 0, "failed": 0}

        points, failed = [], 0
        for record, point in zip(records, ids):
            try:
                image = await self.api.image(record["url"])
                digest = hashlib.sha256((self.visual.identity + image).encode()).hexdigest()
                cached = self.db.execute("SELECT vector FROM cache WHERE id=?", (digest,)).fetchone()
                vector = json.loads(cached[0]) if cached else await self.visual.embed(image)
                points.append(models.PointStruct(id=point, vector=vector, payload={
                    **product_document(product).metadata,
                    "kind": "image",
                    "imageUrl": record["url"],
                    "variantId": record["variantId"],
                    "contentHash": digest,
                    "imageSetHash": image_set_hash,
                }))
                if not cached:
                    self.db.execute("INSERT OR REPLACE INTO cache VALUES (?,?)", (digest, json.dumps(vector)))
                    self.db.commit()
            except ValueError as exc:
                failed += 1
                log.warning("Skipping unsupported image for product %s (%s): %s", pid, record["url"], exc)
            except Exception:
                failed += 1
                log.exception("Could not index image for product %s", pid)
        if points:
            await self.visual.upsert(points)
            self.db.commit()
        # Preserve an old valid point when a transient download failed. Removed URLs
        # are still purged because they are absent from the expected id set.
        await self.visual.delete_product(pid, keep=ids or None)
        return {"images": len(points), "failed": failed}

    async def process_events(self, events):
        await self.visual.ensure(512)
        indexed = deleted = skipped = failed = 0
        for topic, product_id in events:
            if topic == "product.deleted":
                await self.visual.delete_product(product_id)
                deleted += 1
                continue
            product = await self.api.product(product_id)
            if product is None:
                await self.visual.delete_product(product_id)
                deleted += 1
                continue
            stored = await self._stored_payload(product_id)
            fingerprint = self._image_set_hash(product)
            if stored and (topic == "product.created" or stored.get("imageSetHash") == fingerprint):
                skipped += 1
                continue
            result = await self.index_product(product)
            indexed += result["images"]
            failed += result["failed"]
        log.info("Visual event batch: events=%d images=%d deleted=%d skipped=%d failed=%d",
                 len(events), indexed, deleted, skipped, failed)
        return {"events": len(events), "images": indexed, "deleted": deleted,
                "skipped": skipped, "failed": failed}

    async def reconcile(self):
        products = await self.api.all_products()
        shop_id = os.getenv("CHATBOT_INDEX_SHOP_ID", "").strip()
        if shop_id:
            products = [item for item in products if str(item.get("shopId")) == shop_id]
        await self.visual.ensure(512)
        if not shop_id:
            existing = await self.visual.product_ids()
            desired = {str(p["_id"]) for p in products}
            for pid in existing - desired:
                await self.visual.delete_product(pid)
        indexed, failed = 0, 0
        for product in products:
            pid = str(product["_id"])
            stored = await self._stored_payload(pid)
            if stored and (not stored.get("imageSetHash") or
                           stored.get("imageSetHash") == self._image_set_hash(product)):
                continue
            result = await self.index_product(product)
            indexed += result["images"]
            failed += result["failed"]
        log.info("Visual reconciliation: products=%d images=%d failed=%d", len(products), indexed, failed)
        return {"products": len(products), "images": indexed, "failed": failed}


async def main():
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings()
    api, visual = CatalogAPI(settings), VisualCatalog(settings)
    worker = ImageIndexer(settings, api, visual)
    try:
        if os.getenv("CHATBOT_INDEX_ONCE") == "true":
            await worker.reconcile()
        else:
            await visual.ensure(512)
            await consume_product_events("chatbot-visual-indexer", worker.process_events)
    finally:
        worker.db.close()
        await api.close()
        await visual.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
