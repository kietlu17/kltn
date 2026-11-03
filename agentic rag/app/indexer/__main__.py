"""python -m app.indexer [run|once|plan|status]

run     sync, then re-sync every INDEXER_INTERVAL_SECONDS (container default)
once    sync once and exit
plan    dry run: show what would be embedded, spends no quota
status  print the last status written by a running worker
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from dataclasses import asdict
from pathlib import Path

from qdrant_client import AsyncQdrantClient

from ..config import AgenticSettings
from ..marketplace import MarketplaceClient
from .cache import EmbeddingCache
from .runner import (
    ApiKeySource,
    CatalogIndexer,
    CatalogVectorStore,
    GeminiDocumentEmbedder,
    IndexerSettings,
)


def _build(settings: AgenticSettings, options: IndexerSettings) -> CatalogIndexer:
    data_dir = Path(settings.data_dir)
    return CatalogIndexer(
        settings,
        options,
        MarketplaceClient(settings),
        CatalogVectorStore(
            AsyncQdrantClient(url=settings.qdrant_url, timeout=settings.request_timeout),
            settings.collection,
        ),
        EmbeddingCache(data_dir / "embedding_cache.sqlite"),
        GeminiDocumentEmbedder(settings, ApiKeySource(options.key_file, settings.gemini_api_key)),
        data_dir / "indexer_status.json",
    )


async def _main(command: str) -> int:
    settings = AgenticSettings()
    options = IndexerSettings()
    if command == "status":
        path = Path(settings.data_dir) / "indexer_status.json"
        print(path.read_text(encoding="utf-8") if path.exists() else '{"state": "never_run"}')
        return 0
    indexer = _build(settings, options)
    loop = asyncio.get_running_loop()
    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        try:
            # docker stop sends SIGTERM: finish the batch in flight, then exit.
            loop.add_signal_handler(sig, indexer.stop_event.set)
        except (NotImplementedError, RuntimeError, TypeError):
            pass
    try:
        if command == "plan":
            summary, _work = await indexer.plan(dry_run=True)
            print(json.dumps(
                {**asdict(summary), "batches": summary.batches(options.batch_size),
                 "batchSize": options.batch_size, "collection": settings.collection},
                ensure_ascii=False, indent=2,
            ))
            return 0
        await indexer.run("once" if command == "once" else options.mode)
        return 0
    finally:
        await indexer.marketplace.close()
        await indexer.store.client.close()
        indexer.cache.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # One line per HTTP request would bury the batch progress.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command not in {"run", "once", "plan", "status"}:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(_main(command)))


if __name__ == "__main__":
    main()
