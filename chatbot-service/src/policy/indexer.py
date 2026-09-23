"""Periodic ingestion worker for local customer-service policy PDFs."""
import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
from pathlib import Path

from ..core.settings import Settings
from ..infrastructure.models import ModelClients
from .catalog import PolicyCatalog
from .pdf_loader import load_policy_pdf

log = logging.getLogger(__name__)


class PolicyEmbeddingCache:
    def __init__(self, data_dir):
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(data_dir) / "policy-index.sqlite"))
        self.db.execute("CREATE TABLE IF NOT EXISTS embeddings (id TEXT PRIMARY KEY, vector TEXT)")

    def get(self, key):
        row = self.db.execute("SELECT vector FROM embeddings WHERE id=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_many(self, values):
        self.db.executemany(
            "INSERT OR REPLACE INTO embeddings VALUES (?,?)",
            [(key, json.dumps(vector, separators=(",", ":"))) for key, vector in values],
        )
        self.db.commit()

    def close(self):
        self.db.close()


def _retry_wait(error, attempt):
    message = str(error)
    match = re.search(r"retry(?:Delay)?(?: in|['\": ]+)\s*['\"]?(\d+(?:\.\d+)?)s", message, re.I)
    server_delay = float(match.group(1)) + 2 if match else 0
    return min(300, max(server_delay, 2 ** attempt * 2))


async def reconcile(models, catalog, paths, cache=None):
    pdf_paths = []
    for configured_path in paths:
        path = Path(configured_path)
        if path.is_dir():
            pdf_paths.extend(sorted(path.rglob("*.pdf")))
        elif path.is_file() and path.suffix.casefold() == ".pdf":
            pdf_paths.append(path)
        else:
            raise ValueError(f"Policy PDF path not found: {path}")
    if not pdf_paths:
        raise ValueError("No local policy PDF files were found")
    documents, texts = [], []
    for path in pdf_paths:
        chunks = load_policy_pdf(path)
        source_url = chunks[0]["sourceUrl"]
        documents.append((path, source_url, chunks))
        texts.extend(f"{chunk['title']}\n{chunk['text']}" for chunk in chunks)

    batch_size = max(1, int(os.getenv("CHATBOT_POLICY_EMBED_BATCH_SIZE", "50")))
    batch_retries = max(1, int(os.getenv("CHATBOT_POLICY_EMBED_RETRIES", "10")))
    batch_delay = max(0.0, float(os.getenv("CHATBOT_POLICY_EMBED_DELAY_SECONDS", "0.5")))
    keys = [hashlib.sha256(f"{catalog.collection}:{text}".encode()).hexdigest() for text in texts]
    vectors = [cache.get(key) if cache else None for key in keys]
    pending = [index for index, vector in enumerate(vectors) if vector is None]
    spans, cursor = [], 0
    for _, _, chunks in documents:
        spans.append((cursor, cursor + len(chunks)))
        cursor += len(chunks)
    indexed, total = set(), 0

    async def flush_complete_sources():
        nonlocal total
        for document_index, ((path, source_url, chunks), (start, end)) in enumerate(zip(documents, spans)):
            if document_index in indexed or any(vector is None for vector in vectors[start:end]):
                continue
            total += await catalog.replace_source(source_url, chunks, vectors[start:end])
            indexed.add(document_index)
            log.info("Indexed local policy PDF=%s source=%s chunks=%d", path, source_url, len(chunks))

    log.info("Policy embeddings: chunks=%d cached=%d pending=%d", len(texts), len(texts) - len(pending), len(pending))
    await flush_complete_sources()
    for batch_start in range(0, len(pending), batch_size):
        indices = pending[batch_start:batch_start + batch_size]
        batch_texts = [texts[index] for index in indices]
        for attempt in range(batch_retries):
            try:
                batch_vectors = await models.embed_documents(batch_texts)
                break
            except Exception as error:
                if attempt + 1 == batch_retries:
                    raise
                wait_seconds = _retry_wait(error, attempt)
                log.warning(
                    "Policy embedding batch start=%d failed; retry=%d/%d in %.1fs: %s",
                    batch_start, attempt + 1, batch_retries, wait_seconds, error,
                )
                await asyncio.sleep(wait_seconds)
        if len(batch_vectors) != len(indices):
            raise RuntimeError("Policy embedding batch returned an unexpected vector count")
        for index, vector in zip(indices, batch_vectors):
            vectors[index] = vector
        if cache:
            cache.put_many((keys[index], vectors[index]) for index in indices)
        log.info(
            "Policy embedding progress: %d/%d chunks",
            len(texts) - sum(vector is None for vector in vectors), len(texts),
        )
        await flush_complete_sources()
        if batch_delay:
            await asyncio.sleep(batch_delay)
    if any(vector is None for vector in vectors):
        raise RuntimeError("Policy embedding count does not match PDF chunk count")

    await flush_complete_sources()
    return total


async def main():
    settings = Settings()
    models, catalog = ModelClients(settings), PolicyCatalog(settings)
    cache = PolicyEmbeddingCache(settings.data_dir)
    paths = [path.strip() for path in os.getenv(
        "CHATBOT_POLICY_PDF_PATHS", "/policies/shopee-help"
    ).split(",") if path.strip()]
    retry_seconds = max(5, int(os.getenv("CHATBOT_POLICY_RETRY_SECONDS", "60")))
    sync_seconds = max(300, int(os.getenv("CHATBOT_POLICY_SYNC_SECONDS", "86400")))
    try:
        while True:
            delay = sync_seconds
            try:
                count = await reconcile(models, catalog, paths, cache)
                log.info("Policy reconciliation complete: chunks=%d", count)
            except Exception:
                delay = retry_seconds
                log.exception("Policy reconciliation failed; retrying in %ss", delay)
            if os.getenv("CHATBOT_INDEX_ONCE") == "true":
                break
            await asyncio.sleep(delay)
    finally:
        cache.close()
        await models.close()
        await catalog.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
