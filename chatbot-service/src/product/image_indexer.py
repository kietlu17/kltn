"""Reconcile MinIO/catalog images into an independent visual collection."""
import asyncio
import hashlib
import json
import logging
import os
import sqlite3
from pathlib import Path

from qdrant_client import models

from .catalog import image_records, point_id, product_document
from ..core.settings import Settings
from ..infrastructure.clients import CatalogAPI
from .visual import VisualCatalog

log = logging.getLogger(__name__)


class ImageIndexer:
    def __init__(self, settings, api, visual):
        self.settings, self.api, self.visual = settings, api, visual
        Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(settings.data_dir) / "visual-index.sqlite"))
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (id TEXT PRIMARY KEY, vector TEXT)")

    async def reconcile(self):
        products = await self.api.all_products()
        await self.visual.ensure(512)
        existing = await self.visual.product_ids()
        desired = {str(p["_id"]) for p in products}
        for pid in existing - desired:
            await self.visual.delete_product(pid)
        indexed, failed = 0, 0
        for product in products:
            pid = str(product["_id"])
            records = image_records(product, self.settings.max_images)
            # Keep expected IDs even when a download fails; old valid vectors
            # survive transient errors. Removed URLs are still purged.
            ids = [point_id(pid, "pixel:" + r["url"] + ":" + r["variantId"]) for r in records]
            await self.visual.delete_product(pid, keep=ids or None)
            for record, point in zip(records, ids):
                try:
                    image = await self.api.image(record["url"])
                    digest = hashlib.sha256((self.visual.identity + image).encode()).hexdigest()
                    cached = self.db.execute("SELECT vector FROM cache WHERE id=?", (digest,)).fetchone()
                    vector = json.loads(cached[0]) if cached else await self.visual.embed(image)
                    await self.visual.upsert([models.PointStruct(id=point, vector=vector, payload={
                        **product_document(product).metadata, "kind": "image", "imageUrl": record["url"],
                        "variantId": record["variantId"], "contentHash": digest,
                    })])
                    if not cached:
                        self.db.execute("INSERT OR REPLACE INTO cache VALUES (?,?)", (digest, json.dumps(vector)))
                        self.db.commit()
                    indexed += 1
                except ValueError as exc:
                    failed += 1
                    log.warning(
                        "Skipping unsupported image for product %s (%s): %s",
                        pid,
                        record["url"],
                        exc,
                    )
                except Exception:
                    failed += 1
                    log.exception("Could not index image for product %s", pid)
        log.info("Visual reconciliation: products=%d images=%d failed=%d", len(products), indexed, failed)
        return {"products": len(products), "images": indexed, "failed": failed}


async def main():
    settings = Settings()
    api, visual = CatalogAPI(settings), VisualCatalog(settings)
    worker = ImageIndexer(settings, api, visual)
    retry_seconds = max(1, int(os.getenv("CHATBOT_INDEX_RETRY_SECONDS", "15")))
    while True:
        reconciled = False
        try:
            await worker.reconcile()
            reconciled = True
        except Exception:
            log.exception(
                "Visual reconciliation failed; retrying in %ss",
                retry_seconds,
            )
        if os.getenv("CHATBOT_INDEX_ONCE") == "true":
            break
        delay = max(10, settings.sync_seconds) if reconciled else retry_seconds
        await asyncio.sleep(delay)
    worker.db.close()
    await api.close()
    await visual.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
