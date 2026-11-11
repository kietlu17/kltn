"""Resumable, quota-aware catalog embedding.

Every cycle diffs the live catalog against Qdrant and the local embedding
cache, then embeds only texts that were never embedded before, in batches of
INDEXER_BATCH_SIZE. Each batch is cached and upserted before the next one, so
stopping the container loses at most the batch in flight.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from qdrant_client import AsyncQdrantClient, models

from ..config import AgenticSettings, _bounded_float, _bounded_int
from ..sparse import SPARSE_VECTOR_NAME, document_sparse_vector
from .cache import EmbeddingCache
from .documents import Chunk, product_chunks
from ..taxonomy import category_paths

log = logging.getLogger("agentic.indexer")


@dataclass(frozen=True)
class IndexerSettings:
    batch_size: int = field(default_factory=lambda: _bounded_int("INDEXER_BATCH_SIZE", 50, 1, 100))
    mode: str = field(default_factory=lambda: os.getenv("INDEXER_MODE", "watch").strip().lower())
    interval: float = field(
        default_factory=lambda: _bounded_float("INDEXER_INTERVAL_SECONDS", 900, 30, 86400)
    )
    batch_interval: float = field(
        default_factory=lambda: _bounded_float("INDEXER_BATCH_INTERVAL_SECONDS", 0, 0, 600)
    )
    # A batch is sent as several small requests spaced out in time, so a
    # per-minute limit rejects only part of it instead of the whole batch.
    request_size: int = field(default_factory=lambda: _bounded_int("INDEXER_REQUEST_SIZE", 10, 1, 100))
    request_interval: float = field(
        default_factory=lambda: _bounded_float("INDEXER_REQUEST_INTERVAL_SECONDS", 12, 0, 600)
    )
    # Texts whose request failed are retried together after this pause.
    retry_wait: float = field(
        default_factory=lambda: _bounded_float("INDEXER_RETRY_SECONDS", 60, 1, 86400)
    )
    # 0 = unlimited; otherwise the most provider batches one cycle may spend.
    max_batches: int = field(default_factory=lambda: _bounded_int("INDEXER_MAX_BATCHES", 0, 0, 1_000_000))
    key_file: str = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY_FILE", "/secrets/gemini_api_key").strip()
    )
    # 0 = unlimited; otherwise texts each key may embed per quota day before
    # the next key in the key file takes over.
    key_request_limit: int = field(
        default_factory=lambda: _bounded_int("INDEXER_KEY_REQUEST_LIMIT", 0, 0, 10_000_000)
    )


class QuotaSpent(RuntimeError):
    """Every configured key used its INDEXER_KEY_REQUEST_LIMIT for today."""


def _quota_day() -> str:
    # Gemini daily quotas reset at midnight Pacific time (UTC-8 in winter).
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() - 8 * 3600))


class ApiKeySource:
    """Reads the keys on every batch so they can be swapped without a restart.

    The key file holds one key per line ("GEMINI_API_KEY=" prefixes and blank
    lines are ignored) and wins over the GEMINI_API_KEY environment variable.
    With several keys and INDEXER_KEY_REQUEST_LIMIT, each key embeds at most
    that many texts per quota day; the next key takes over when it is used up
    or the provider rejects it with a quota error. Usage is persisted by key
    fingerprint (never the key itself) so a restart does not reset it.
    """

    def __init__(
        self,
        key_file: str,
        env_key: str,
        *,
        request_limit: int = 0,
        usage_file: str | Path | None = None,
    ):
        self.key_file = Path(key_file) if key_file else None
        self.env_key = env_key.strip()
        self.request_limit = max(0, int(request_limit))
        self.usage_file = Path(usage_file) if usage_file else None
        self._usage = self._load_usage()

    @staticmethod
    def fingerprint(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()[:12]

    def keys(self) -> list[str]:
        if self.key_file and self.key_file.is_file():
            # utf-8-sig: Windows PowerShell writes a BOM that would corrupt the key.
            lines = self.key_file.read_text(encoding="utf-8-sig").splitlines()
            keys = [
                re.sub(r"^\s*(?:export\s+)?GEMINI_API_KEY\s*=\s*", "", line).strip().strip("\"'")
                for line in lines
                if line.strip() and not line.lstrip().startswith("#")
            ]
            keys = list(dict.fromkeys(key for key in keys if key))
            if keys:
                return keys
        return [self.env_key] if self.env_key else []

    def _load_usage(self) -> dict:
        if self.usage_file and self.usage_file.is_file():
            try:
                return json.loads(self.usage_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
        return {}

    def _entry(self, key: str) -> dict:
        entry = self._usage.get(self.fingerprint(key)) or {}
        if entry.get("day") != _quota_day():
            entry = {"day": _quota_day(), "requests": 0, "exhausted": False}
            self._usage[self.fingerprint(key)] = entry
        return entry

    def _save(self):
        if not self.usage_file:
            return
        self.usage_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.usage_file.with_suffix(".tmp")
        temp.write_text(json.dumps(self._usage, indent=2), encoding="utf-8")
        temp.replace(self.usage_file)

    def remaining(self, key: str) -> int | None:
        """Texts the key may still embed today; None when unlimited."""
        entry = self._entry(key)
        if entry.get("exhausted"):
            return 0
        if not self.request_limit:
            return None
        return max(self.request_limit - int(entry.get("requests") or 0), 0)

    def current(self, needed: int = 1) -> str:
        """The first key that can still take `needed` texts today ("" if none)."""
        keys = self.keys()
        for key in keys:
            left = self.remaining(key)
            if left is None or left >= needed:
                return key
        return "" if len(keys) > 1 or self.request_limit else (keys[0] if keys else "")

    def record(self, key: str, count: int):
        entry = self._entry(key)
        entry["requests"] = int(entry.get("requests") or 0) + count
        self._save()

    def mark_exhausted(self, key: str):
        self._entry(key)["exhausted"] = True
        self._save()

    def summary(self) -> list[dict]:
        return [
            {
                "key": f"…{key[-4:]}",
                "requestsToday": int(self._entry(key).get("requests") or 0),
                "limit": self.request_limit or None,
                "exhausted": bool(self._entry(key).get("exhausted")),
            }
            for key in self.keys()
        ]


class MissingApiKey(RuntimeError):
    pass


class GeminiDocumentEmbedder:
    def __init__(self, settings: AgenticSettings, keys: ApiKeySource):
        self.settings = settings
        self.keys = keys
        self._key = ""
        self._client: GoogleGenerativeAIEmbeddings | None = None

    @property
    def key_suffix(self) -> str:
        return f"…{self._key[-4:]}" if self._key else ""

    def _client_for_current_key(self, needed: int = 1) -> GoogleGenerativeAIEmbeddings:
        key = self.keys.current(needed)
        if not key and self.keys.keys():
            raise QuotaSpent(
                "RESOURCE_EXHAUSTED: every Gemini key reached INDEXER_KEY_REQUEST_LIMIT for today"
            )
        if not key:
            raise MissingApiKey("No Gemini API key in the key file or GEMINI_API_KEY")
        if key != self._key or self._client is None:
            self._key = key
            self._client = GoogleGenerativeAIEmbeddings(
                model=f"models/{self.settings.embedding_model}",
                google_api_key=key,
                output_dimensionality=self.settings.embedding_dimensions,
                request_options={"timeout": self.settings.model_timeout},
            )
            log.info("Using Gemini API key %s", self.key_suffix)
        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        client = self._client_for_current_key(len(texts))
        key = self._key
        try:
            vectors = await client.aembed_documents(texts, batch_size=len(texts))
        except Exception as error:
            if classify_error(error) == "quota" and len(self.keys.keys()) > 1:
                # This key is spent for today; the next batch uses the next one.
                self.keys.mark_exhausted(key)
                log.warning("Gemini key %s hit its quota; switching key", self.key_suffix)
            raise
        # Every text of a batch counts against the key's quota.
        self.keys.record(key, len(texts))
        if len(vectors) != len(texts):
            raise RuntimeError("Embedding batch returned an unexpected vector count")
        normalized = []
        for vector in vectors:
            if len(vector) != self.settings.embedding_dimensions or not all(
                math.isfinite(value) for value in vector
            ):
                raise RuntimeError("Embedding has the wrong dimension or invalid values")
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            normalized.append([value / norm for value in vector])
        return normalized


def classify_error(error: Exception) -> str:
    message = str(error)
    # Quota first: a 429 message may mention "api_key" in its quota details.
    if isinstance(error, QuotaSpent) or re.search(r"\b429\b|RESOURCE_EXHAUSTED|quota", message, re.I):
        return "quota"
    if isinstance(error, MissingApiKey) or re.search(
        r"API[_ ]?key|PERMISSION_DENIED|UNAUTHENTICATED|\b40[13]\b", message, re.I
    ):
        return "auth"
    if isinstance(error, (asyncio.TimeoutError, TimeoutError)) or re.search(
        r"\b50[034]\b|UNAVAILABLE|DEADLINE|timed? ?out|Connect", message, re.I
    ):
        return "transient"
    return "fatal"


class CatalogVectorStore:
    """The agentic catalog collection: unnamed dense vector + BM25 sparse vector."""

    KEYWORD_FIELDS = (
        "productId", "kind", "chunkType", "categoryId", "shopId", "productType",
        "audience", "brand", "colors", "sizes", "textHash", "specs[].key", "specs[].unit",
    )
    FLOAT_FIELDS = ("minPrice", "maxPrice", "specs[].numericValue")

    def __init__(self, client: AsyncQdrantClient, collection: str):
        self.client = client
        self.collection = collection

    async def ensure(self, dimensions: int):
        if not await self.client.collection_exists(self.collection):
            await self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(size=dimensions, distance=models.Distance.COSINE),
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
                quantization_config=models.ScalarQuantization(
                    scalar=models.ScalarQuantizationConfig(
                        type=models.ScalarType.INT8, always_ram=True
                    )
                ),
            )
            for name in self.KEYWORD_FIELDS:
                await self.client.create_payload_index(
                    self.collection, name, models.PayloadSchemaType.KEYWORD
                )
            for name in self.FLOAT_FIELDS:
                await self.client.create_payload_index(
                    self.collection, name, models.PayloadSchemaType.FLOAT
                )
            await self.client.create_payload_index(
                self.collection,
                "text",
                models.TextIndexParams(
                    type=models.TextIndexType.TEXT,
                    tokenizer=models.TokenizerType.WORD,
                    lowercase=True,
                    ascii_folding=True,
                ),
            )
            return
        info = await self.client.get_collection(self.collection)
        if getattr(info.config.params.vectors, "size", None) != dimensions:
            raise RuntimeError("Embedding dimension mismatch: use a new collection name")
        if SPARSE_VECTOR_NAME not in (info.config.params.sparse_vectors or {}):
            raise RuntimeError(f"Collection {self.collection} has no '{SPARSE_VECTOR_NAME}' vector")

    async def stored(self) -> dict[str, dict]:
        """point id -> {productId, textHash, denseHash, payloadHash} in one paginated scroll."""
        result: dict[str, dict] = {}
        offset = None
        while True:
            points, offset = await self.client.scroll(
                self.collection,
                limit=1000,
                offset=offset,
                with_vectors=False,
                with_payload=["productId", "textHash", "denseHash", "payloadHash"],
            )
            for point in points:
                result[str(point.id)] = dict(point.payload or {})
            if offset is None:
                return result

    async def upsert(self, chunks: list[Chunk], vectors: dict[str, list[float]]):
        for start in range(0, len(chunks), 256):
            await self.client.upsert(
                self.collection,
                points=[
                    models.PointStruct(
                        id=chunk.point_id,
                        vector={
                            "": vectors[chunk.dense_hash],
                            SPARSE_VECTOR_NAME: models.SparseVector(
                                **document_sparse_vector(chunk.text)
                            ),
                        },
                        payload=chunk.payload,
                    )
                    for chunk in chunks[start:start + 256]
                ],
                wait=True,
            )

    async def overwrite_payloads(self, chunks: list[Chunk]):
        """Price/stock/facet changes reuse the stored vector: no embedding quota."""
        for start in range(0, len(chunks), 100):
            await self.client.batch_update_points(
                self.collection,
                update_operations=[
                    models.OverwritePayloadOperation(
                        overwrite_payload=models.SetPayload(
                            payload=chunk.payload, points=[chunk.point_id]
                        )
                    )
                    for chunk in chunks[start:start + 100]
                ],
                wait=True,
            )

    async def delete(self, point_ids: list[str]):
        for start in range(0, len(point_ids), 1000):
            await self.client.delete(
                self.collection,
                points_selector=models.PointIdsList(points=point_ids[start:start + 1000]),
                wait=True,
            )


@dataclass
class IndexPlan:
    catalog_products: int = 0
    total_chunks: int = 0
    up_to_date: int = 0
    payload_only: int = 0
    from_cache: int = 0
    texts_to_embed: int = 0
    removed_products: int = 0
    stale_chunks: int = 0

    def batches(self, batch_size: int) -> int:
        return math.ceil(self.texts_to_embed / batch_size)


class CatalogIndexer:
    def __init__(
        self,
        settings: AgenticSettings,
        indexer_settings: IndexerSettings,
        marketplace,
        store: CatalogVectorStore,
        cache: EmbeddingCache,
        embedder: GeminiDocumentEmbedder,
        status_path: str | Path,
    ):
        self.settings = settings
        self.options = indexer_settings
        self.marketplace = marketplace
        self.store = store
        self.cache = cache
        self.embedder = embedder
        self.status_path = Path(status_path)
        self.stop_event = asyncio.Event()
        self.status: dict = {"state": "starting", "collection": store.collection}
        self._next_request_at = 0.0

    # -- status ---------------------------------------------------------------

    def _write_status(self, state: str | None = None, **fields):
        if state:
            self.status["state"] = state
        self.status.update(fields)
        self.status["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.status["apiKey"] = self.embedder.key_suffix
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.status_path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.status, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.status_path)

    async def _sleep(self, seconds: float) -> bool:
        """Interruptible wait; True when a stop was requested."""
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=max(seconds, 0))
            return True
        except asyncio.TimeoutError:
            return False

    # -- planning -------------------------------------------------------------

    async def _desired_chunks(self) -> tuple[list[dict], dict[str, Chunk]]:
        products = await self.marketplace.all_products()
        try:
            # Full path ("Thời trang › Nữ › Áo thun nữ"): the base chunk and the
            # payload name the whole branch, not an ambiguous leaf ("Áo Thun").
            categories = category_paths(await self.marketplace.categories())
        except Exception:
            categories = {}
        desired: dict[str, Chunk] = {}
        for product in products:
            for chunk in product_chunks(
                product,
                self.settings.embedding_model,
                self.settings.embedding_dimensions,
                categories.get(str(product.get("categoryId") or ""), ""),
            ):
                desired[chunk.point_id] = chunk
        return products, desired

    async def plan(self, *, dry_run: bool = False) -> tuple[IndexPlan, dict]:
        products, desired = await self._desired_chunks()
        if dry_run and not await self.store.client.collection_exists(self.store.collection):
            stored = {}
        else:
            await self.store.ensure(self.settings.embedding_dimensions)
            stored = await self.store.stored()
        product_ids = {str(product["_id"]) for product in products}
        removed = [
            point_id for point_id, payload in stored.items()
            if str(payload.get("productId") or "") not in product_ids
        ]
        payload_only, need_vector = [], []
        up_to_date = 0
        for point_id, chunk in desired.items():
            previous = stored.get(point_id)
            if previous and previous.get("payloadHash") == chunk.payload_hash:
                up_to_date += 1
            elif (
                previous
                and previous.get("textHash") == chunk.text_hash
                and previous.get("denseHash") == chunk.dense_hash
            ):
                payload_only.append(chunk)
            else:
                need_vector.append(chunk)
        cached = self.cache.get_many(list({chunk.dense_hash for chunk in need_vector}))
        from_cache = [chunk for chunk in need_vector if chunk.dense_hash in cached]
        texts = {chunk.text_hash: chunk.text for chunk in desired.values()}
        pending: dict[str, list[Chunk]] = {}
        for chunk in need_vector:
            if chunk.dense_hash not in cached:
                # Identical texts (shared descriptions, duplicate listings) and
                # variant groups sharing their base vector embed once.
                pending.setdefault(chunk.dense_hash, []).append(chunk)
        removed_ids = set(removed)
        stale = [
            point_id for point_id in stored
            if point_id not in desired and point_id not in removed_ids
        ]
        summary = IndexPlan(
            catalog_products=len(products),
            total_chunks=len(desired),
            up_to_date=up_to_date,
            payload_only=len(payload_only),
            from_cache=len(from_cache),
            texts_to_embed=len(pending),
            removed_products=len({stored[point_id].get("productId") for point_id in removed}),
            stale_chunks=len(stale),
        )
        work = {
            "removed": removed,
            "payload_only": payload_only,
            "from_cache": from_cache,
            "cached": cached,
            "pending": pending,
            "texts": texts,
            "stale": stale,
        }
        return summary, work

    # -- embedding ------------------------------------------------------------

    async def _pace(self) -> bool:
        """Space provider requests INDEXER_REQUEST_INTERVAL_SECONDS apart; True on stop."""
        wait = self._next_request_at - time.monotonic()
        if wait > 0 and await self._sleep(wait):
            return True
        self._next_request_at = time.monotonic() + self.options.request_interval
        return self.stop_event.is_set()

    async def _embed_batch(self, batch: list[str], work: dict, already: int, total: int) -> int:
        """Embed one batch as paced requests of INDEXER_REQUEST_SIZE texts.

        Every request that succeeds is cached and upserted at once; the texts of
        failed requests are retried together after INDEXER_RETRY_SECONDS until
        the whole batch is done. Returns how many texts were embedded, which is
        less than len(batch) only when a stop was requested.
        """
        pending: dict[str, list[Chunk]] = work["pending"]
        remaining = list(batch)
        done = 0
        size = self.options.request_size
        while remaining:
            failed: list[str] = []
            last_error: Exception | None = None
            for start in range(0, len(remaining), size):
                part = remaining[start:start + size]
                if last_error is not None and classify_error(last_error) in {"quota", "auth"}:
                    # The provider is refusing: hold the rest back instead of
                    # sending requests that would be rejected too.
                    failed.extend(part)
                    continue
                if await self._pace():
                    return done
                try:
                    vectors = await self.embedder.embed([work["texts"][digest] for digest in part])
                except Exception as error:
                    if classify_error(error) == "fatal":
                        raise
                    failed.extend(part)
                    last_error = error
                    continue
                by_hash = dict(zip(part, vectors))
                # Cache first: the quota is spent, keep the result even if Qdrant fails.
                self.cache.put_many(by_hash)
                await self.store.upsert([chunk for digest in part for chunk in pending[digest]], by_hash)
                done += len(part)
                self._write_status(
                    "embedding",
                    embeddedThisCycle=already + done,
                    remainingTexts=total - already - done,
                    lastBatchAt=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    lastError="",
                )
            remaining = failed
            if remaining and await self._wait_before_retry(last_error, len(remaining)):
                return done
        return done

    async def _wait_before_retry(self, error: Exception, count: int) -> bool:
        """Pause before resending failed texts; True when a stop was requested."""
        kind = classify_error(error)
        if kind == "auth":
            self._write_status("waiting_api_key", lastError=str(error)[:300])
            log.warning("Gemini API key missing or rejected; %d texts wait for a new key", count)
            return await self._wait_for_key_change(None)
        wait = self.options.retry_wait
        self._write_status(
            "waiting_quota" if kind == "quota" else "waiting_retry",
            lastError=str(error)[:300],
            resumeAt=time.strftime("%H:%M:%S", time.localtime(time.time() + wait)),
        )
        log.warning(
            "%d texts failed (%s); retrying them in %.0fs (or when the key changes)", count, kind, wait
        )
        return await self._wait_for_key_change(wait)

    async def _wait_for_key_change(self, timeout: float | None) -> bool:
        """Wait until the key changes, the timeout ends or a stop arrives (True)."""
        initial = self.embedder.keys.current()
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            step = 10.0 if deadline is None else min(10.0, deadline - time.monotonic())
            if step <= 0:
                return False
            if await self._sleep(step):
                return True
            if self.embedder.keys.current() != initial:
                log.info("Gemini API key changed; resuming")
                return False

    # -- one cycle ------------------------------------------------------------

    async def sync(self) -> IndexPlan:
        self._write_status("planning", lastError="")
        summary, work = await self.plan()
        self._write_status(
            "applying",
            plan=asdict(summary),
            plannedBatches=summary.batches(self.options.batch_size),
            embeddedThisCycle=0,
            remainingTexts=summary.texts_to_embed,
        )
        log.info("Index plan: %s", asdict(summary))
        # Products gone from the catalog (deleted, unapproved) leave search now.
        await self.store.delete(work["removed"])
        await self.store.overwrite_payloads(work["payload_only"])
        await self.store.upsert(work["from_cache"], work["cached"])

        pending: dict[str, list[Chunk]] = work["pending"]
        hashes = list(pending)
        embedded = 0
        batches = 0
        for start in range(0, len(hashes), self.options.batch_size):
            if self.stop_event.is_set():
                break
            if self.options.max_batches and batches >= self.options.max_batches:
                log.info("INDEXER_MAX_BATCHES=%d reached for this cycle", self.options.max_batches)
                break
            batch = hashes[start:start + self.options.batch_size]
            self._write_status("embedding")
            done = await self._embed_batch(batch, work, embedded, len(hashes))
            embedded += done
            if done < len(batch):
                break
            batches += 1
            log.info("Embedded batch %d: %d texts, %d remaining", batches, len(batch), len(hashes) - embedded)
            if self.options.batch_interval and await self._sleep(self.options.batch_interval):
                break

        complete = embedded == len(hashes)
        if complete:
            # Superseded chunks are removed only once their replacements exist.
            await self.store.delete(work["stale"])
        self._write_status(
            "up_to_date" if complete else "stopped" if self.stop_event.is_set() else "partial",
            remainingTexts=len(hashes) - embedded,
            cachedVectors=self.cache.count(),
        )
        return summary

    async def run(self, mode: str | None = None):
        mode = mode or self.options.mode
        while not self.stop_event.is_set():
            try:
                await self.sync()
            except Exception as error:
                log.exception("Indexing cycle failed")
                self._write_status("error", lastError=f"{type(error).__name__}: {error}"[:300])
                if mode == "once":
                    raise
            if mode == "once":
                return
            self._write_status(
                nextRunAt=time.strftime(
                    "%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() + self.options.interval)
                )
            )
            if await self._sleep(self.options.interval):
                break
        self._write_status("stopped")
