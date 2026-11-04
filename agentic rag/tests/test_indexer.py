import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from qdrant_client import AsyncQdrantClient

from app.config import AgenticSettings
from app.indexer.cache import EmbeddingCache
from app.indexer.documents import CHUNK_MAX_CHARS, product_chunks
from app.indexer.runner import (
    ApiKeySource,
    CatalogIndexer,
    CatalogVectorStore,
    IndexerSettings,
    classify_error,
)
from app.retrieval import StructuredProductRetriever
from app.schemas import SearchFilters

DIMENSIONS = 4


def make_product(index: int, **overrides) -> dict:
    return {
        "_id": f"{index:024x}",
        "name": f"Loa bluetooth mẫu {index}" if index % 2 else f"Áo thun đỏ mẫu {index}",
        "description": f"Mô tả sản phẩm số {index}.",
        "detail": f"Chi tiết riêng của sản phẩm {index}.",
        "price": 100000 + index,
        "categoryId": "c" * 24,
        "shopId": "s" * 24,
        "moderationStatus": "approved",
        "specifications": [{"name": "Pin", "value": f"{1000 + index} mAh"}],
        "variants": [],
        **overrides,
    }


class FakeMarketplace:
    def __init__(self, products):
        self.products = products

    async def all_products(self):
        return list(self.products)

    async def categories(self):
        return [{"id": "c" * 24, "name": "Điện tử"}]


class FakeEmbedder:
    """Deterministic vectors; records every provider call."""

    def __init__(self, keys):
        self.keys = keys
        self.calls: list[int] = []
        self.failures: list[Exception] = []

    @property
    def key_suffix(self):
        return ""

    async def embed(self, texts):
        if self.failures:
            raise self.failures.pop(0)
        self.calls.append(len(texts))
        return [[1.0, float(len(text) % 7), 0.5, 0.25] for text in texts]


class IndexerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = AgenticSettings(
            gemini_api_key="env-key", embedding_dimensions=DIMENSIONS, data_dir=self.temp.name
        )
        self.key_file = Path(self.temp.name) / "gemini_api_key"
        self.options = IndexerSettings(
            batch_size=50, mode="once", interval=60, batch_interval=0,
            request_size=10, request_interval=0, retry_wait=60, max_batches=0, key_file=str(self.key_file),
        )
        self.client = AsyncQdrantClient(location=":memory:")
        self.products = [make_product(index) for index in range(1, 61)]
        self.cache = EmbeddingCache(Path(self.temp.name) / "cache.sqlite")
        self.indexer = self._indexer()

    def _indexer(self, **option_overrides):
        options = IndexerSettings(**{**self.options.__dict__, **option_overrides})
        embedder = getattr(self, "embedder", None) or FakeEmbedder(
            ApiKeySource(str(self.key_file), "env-key")
        )
        self.embedder = embedder
        return CatalogIndexer(
            self.settings,
            options,
            FakeMarketplace(self.products),
            CatalogVectorStore(self.client, self.settings.collection),
            self.cache,
            embedder,
            Path(self.temp.name) / "status.json",
        )

    async def asyncTearDown(self):
        self.cache.close()
        await self.client.close()
        self.temp.cleanup()

    def unique_texts(self):
        return {
            chunk.dense_hash
            for product in self.products
            for chunk in product_chunks(product, self.settings.embedding_model, DIMENSIONS, "Điện tử")
        }

    async def test_first_sync_embeds_in_batches_of_50_and_second_spends_nothing(self):
        total = len(self.unique_texts())
        await self.indexer.sync()
        self.assertEqual(sum(self.embedder.calls), total)
        self.assertTrue(all(size <= 10 for size in self.embedder.calls))
        self.assertEqual(self.embedder.calls[0], 10)

        self.embedder.calls.clear()
        summary = await self.indexer.sync()
        self.assertEqual(self.embedder.calls, [])
        self.assertEqual(summary.up_to_date, summary.total_chunks)
        status = json.loads((Path(self.temp.name) / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["state"], "up_to_date")

    async def test_price_change_updates_payload_without_embedding(self):
        await self.indexer.sync()
        self.embedder.calls.clear()
        self.products[0] = {**self.products[0], "price": 999999}
        summary = await self.indexer.sync()
        self.assertEqual(self.embedder.calls, [])
        self.assertGreater(summary.payload_only, 0)
        points, _ = await self.client.scroll(self.settings.collection, limit=500, with_payload=True)
        prices = {
            point.payload["maxPrice"] for point in points
            if point.payload["productId"] == self.products[0]["_id"]
        }
        self.assertEqual(prices, {999999})

    async def test_stopped_run_resumes_with_only_the_remaining_texts(self):
        total = len(self.unique_texts())
        partial = self._indexer(max_batches=1)
        await partial.sync()
        self.assertEqual(self.embedder.calls, [10] * 5)
        status = json.loads((Path(self.temp.name) / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["state"], "partial")
        self.assertEqual(status["remainingTexts"], total - 50)

        await self._indexer().sync()
        self.assertEqual(sum(self.embedder.calls), total)

    async def test_cache_rebuilds_a_lost_collection_without_quota(self):
        await self.indexer.sync()
        self.embedder.calls.clear()
        await self.client.delete_collection(self.settings.collection)
        summary = await self.indexer.sync()
        self.assertEqual(self.embedder.calls, [])
        self.assertEqual(summary.from_cache, summary.total_chunks)

    async def test_removed_and_shortened_products_lose_their_points(self):
        await self.indexer.sync()
        removed_id = self.products.pop()["_id"]
        self.products[0] = {**self.products[0], "detail": ""}
        await self.indexer.sync()
        points, _ = await self.client.scroll(self.settings.collection, limit=1000, with_payload=True)
        product_ids = {point.payload["productId"] for point in points}
        self.assertNotIn(removed_id, product_ids)
        chunk_types = {
            point.payload["chunkType"] for point in points
            if point.payload["productId"] == self.products[0]["_id"]
        }
        self.assertNotIn("detail", chunk_types)

    async def test_quota_pause_resumes_when_the_api_key_changes(self):
        self.embedder.failures = [RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded per day")]
        task = asyncio.create_task(self.indexer.sync())
        for _ in range(100):
            await asyncio.sleep(0.05)
            status_path = Path(self.temp.name) / "status.json"
            if status_path.exists() and "waiting_quota" in status_path.read_text(encoding="utf-8"):
                break
        self.key_file.write_text("new-key\n", encoding="utf-8")
        # The key watcher polls every 10s; speed the test up by waking it.
        self.indexer._sleep = lambda _seconds: asyncio.sleep(0, result=False)
        await asyncio.wait_for(task, timeout=15)
        self.assertEqual(sum(self.embedder.calls), len(self.unique_texts()))

    async def test_failed_part_of_a_batch_is_retried_while_the_rest_is_kept(self):
        total = len(self.unique_texts())
        embedder = self.embedder
        original = embedder.embed
        attempts = []

        async def flaky(texts):
            attempts.append(len(texts))
            if len(attempts) == 2:
                raise RuntimeError("503 UNAVAILABLE")
            return await original(texts)

        embedder.embed = flaky
        indexer = self._indexer(retry_wait=1)
        await indexer.sync()
        # 1 failed request out of the first batch, retried once; nothing re-sent twice.
        self.assertEqual(sum(embedder.calls), total)
        self.assertEqual(len(attempts), len(embedder.calls) + 1)
        self.assertEqual(self.cache.count(), total)
        status = json.loads((Path(self.temp.name) / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["state"], "up_to_date")

    async def test_stop_request_finishes_cleanly_between_batches(self):
        self.indexer.stop_event.set()
        await self.indexer.sync()
        self.assertEqual(self.embedder.calls, [])
        status = json.loads((Path(self.temp.name) / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["state"], "stopped")

    async def test_dry_run_plan_neither_creates_collection_nor_embeds(self):
        summary, _ = await self.indexer.plan(dry_run=True)
        self.assertFalse(await self.client.collection_exists(self.settings.collection))
        self.assertEqual(summary.texts_to_embed, len(self.unique_texts()))
        self.assertEqual(self.embedder.calls, [])

    async def test_variant_groups_reuse_the_base_vector_without_embedding(self):
        self.products = [
            make_product(index, variants=[
                {"_id": f"v{index}a", "name": "Đỏ / M", "price": 1},
                {"_id": f"v{index}b", "name": "Đen / L", "price": 2},
                {"_id": f"v{index}c", "name": "Trắng / XL", "price": 3},
            ])
            for index in range(1, 4)
        ]
        indexer = self._indexer()
        await indexer.sync()
        texts_without_variants = {
            chunk.text_hash
            for product in self.products
            for chunk in product_chunks(product, self.settings.embedding_model, DIMENSIONS, "Điện tử")
            if chunk.payload["chunkType"] != "variant_group"
        }
        self.assertEqual(sum(self.embedder.calls), len(texts_without_variants))
        points, _ = await self.client.scroll(
            self.settings.collection, limit=100, with_payload=True, with_vectors=True
        )
        product_points = [p for p in points if p.payload["productId"] == self.products[0]["_id"]]
        base = next(p for p in product_points if p.payload["chunkType"] == "base")
        groups = [p for p in product_points if p.payload["chunkType"] == "variant_group"]
        self.assertEqual(len(groups), 3)
        for group in groups:
            self.assertEqual(group.vector[""], base.vector[""])
            self.assertNotEqual(group.vector["bm25"], base.vector["bm25"])

    async def test_retriever_finds_indexed_products_through_hybrid_search(self):
        await self.indexer.sync()

        class QueryModels:
            async def embed_query(self, _query):
                return [1.0, 0.0, 0.5, 0.25]

        retriever = StructuredProductRetriever(self.settings, QueryModels(), client=self.client)
        hits = await retriever.search("loa bluetooth", SearchFilters(), limit=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["sources"], ["hybrid"])
        self.assertEqual(len({hit["productId"] for hit in hits}), len(hits))
        health = await retriever.health()
        self.assertTrue(health["hybridReady"])
        self.assertEqual(health["products"], len(self.products))

    async def test_embedding_outage_falls_back_to_bm25(self):
        await self.indexer.sync()

        class QuotaModels:
            async def embed_query(self, _query):
                raise RuntimeError("429 RESOURCE_EXHAUSTED: embed per day")

        retriever = StructuredProductRetriever(self.settings, QuotaModels(), client=self.client)
        hits = await retriever.search("loa bluetooth", SearchFilters(), limit=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["sources"], ["bm25"])


class DocumentTests(unittest.TestCase):
    def test_long_products_split_into_bounded_self_describing_chunks(self):
        product = make_product(
            7,
            name="Laptop Văn Phòng X14",
            description="Mỏng nhẹ. " * 300,
            detail="Màn hình sắc nét, bàn phím êm. " * 300,
            specifications=[{"name": f"Thông số {i}", "value": "giá trị " * 20} for i in range(40)],
            variants=[
                {"_id": "v1", "name": "Đen / L", "price": 1},
                {"_id": "v2", "name": "Đen / XL", "price": 2},
            ],
        )
        chunks = product_chunks(product, "gemini-embedding-001", 768)
        types = [chunk.payload["chunkType"] for chunk in chunks]
        self.assertEqual(types.count("base"), 1)
        self.assertGreater(types.count("specs"), 1)
        self.assertGreater(types.count("detail"), 1)
        self.assertEqual(types.count("variant_group"), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk.text), CHUNK_MAX_CHARS)
            self.assertTrue(chunk.text.startswith("Tên sản phẩm: Laptop Văn Phòng X14"))
        self.assertTrue(any("Thông số 39" in chunk.text for chunk in chunks))

    def test_text_hash_changes_with_embedding_model(self):
        product = make_product(1)
        first = product_chunks(product, "gemini-embedding-001", 768)[0]
        other = product_chunks(product, "gemini-embedding-002", 768)[0]
        self.assertNotEqual(first.text_hash, other.text_hash)
        self.assertEqual(first.point_id, other.point_id)

    def test_error_classification(self):
        self.assertEqual(classify_error(RuntimeError("429 RESOURCE_EXHAUSTED")), "quota")
        self.assertEqual(classify_error(RuntimeError("API key not valid")), "auth")
        self.assertEqual(classify_error(RuntimeError("503 UNAVAILABLE")), "transient")
        self.assertEqual(classify_error(ValueError("bad")), "fatal")


class ApiKeySourceTests(unittest.TestCase):
    def test_key_file_overrides_environment_and_is_reread(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "key"
            source = ApiKeySource(str(path), "env-key")
            self.assertEqual(source.current(), "env-key")
            path.write_text("file-key-1\n", encoding="utf-8")
            self.assertEqual(source.current(), "file-key-1")
            path.write_text("file-key-2", encoding="utf-8")
            self.assertEqual(source.current(), "file-key-2")


if __name__ == "__main__":
    unittest.main()
