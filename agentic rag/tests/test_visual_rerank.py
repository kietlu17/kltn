import base64
import unittest
from types import SimpleNamespace

import httpx
from qdrant_client import AsyncQdrantClient, models

from app.config import AgenticSettings
from app.agents import ProductAgent
from app.graph import _image_search_turn
from app.rerank import CrossEncoderReranker
from app.schemas import AgentPlan, ChatRequest, SearchFilters
from app.visual import InvalidImage, VisualSearch, image_payload

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG fake image bytes").decode()


def settings(**overrides):
    return AgenticSettings(gemini_api_key="test", **overrides)


def transport(handler):
    return httpx.AsyncClient(base_url="http://models.test", transport=httpx.MockTransport(handler))


class RerankTests(unittest.IsolatedAsyncioTestCase):
    async def test_cross_encoder_order_decides_the_top_k(self):
        seen = {}

        def handler(request):
            seen["body"] = request.read().decode()
            return httpx.Response(200, json={"scores": [0.1, 2.5, -1.0]})

        reranker = CrossEncoderReranker(settings(), client=transport(handler))
        products = [{"id": "a", "name": "Loa Bluetooth"}, {"id": "b", "name": "Tai nghe chống ồn"}, {"id": "c", "name": "Cáp sạc"}]
        ranked = await reranker.rerank("tai nghe chống ồn", products)
        self.assertEqual([item["id"] for item in ranked], ["b", "a", "c"])
        self.assertIn("Tai nghe chống ồn", seen["body"])

    async def test_model_server_failure_keeps_hybrid_order(self):
        reranker = CrossEncoderReranker(settings(), client=transport(lambda _r: httpx.Response(503)))
        products = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]
        self.assertEqual(await reranker.rerank("x", products), products)

    async def test_only_the_candidate_window_is_scored(self):
        counts = []

        def handler(request):
            import json
            documents = json.loads(request.read())["documents"]
            counts.append(len(documents))
            return httpx.Response(200, json={"scores": list(range(len(documents)))})

        reranker = CrossEncoderReranker(settings(rerank_candidates=3), client=transport(handler))
        products = [{"id": str(index), "name": f"P{index}"} for index in range(6)]
        ranked = await reranker.rerank("p", products)
        self.assertEqual(counts, [3])
        self.assertEqual([item["id"] for item in ranked], ["2", "1", "0", "3", "4", "5"])


class VisualSearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = settings()
        self.client = AsyncQdrantClient(location=":memory:")
        self.visual = VisualSearch(self.settings, client=self.client, encoder=transport(self.embed))
        await self.client.create_collection(
            self.visual.collection, vectors_config=models.VectorParams(size=512, distance=models.Distance.COSINE)
        )
        await self.client.upsert(self.visual.collection, points=[
            models.PointStruct(id=1, vector=[1.0] + [0.0] * 511, payload={"productId": "p1", "variantId": "v1"}),
            models.PointStruct(id=2, vector=[0.9, 0.1] + [0.0] * 510, payload={"productId": "p1", "variantId": "v2"}),
            models.PointStruct(id=3, vector=[0.0, 1.0] + [0.0] * 510, payload={"productId": "p2", "variantId": ""}),
        ])

    async def asyncTearDown(self):
        await self.client.close()

    def embed(self, request):
        return httpx.Response(200, json={"identity": self.visual.identity, "embedding": [1.0] + [0.0] * 511})

    async def test_photo_returns_one_hit_per_product_above_threshold(self):
        hits = await self.visual.search(PNG, limit=10)
        self.assertEqual([hit["productId"] for hit in hits], ["p1"])
        self.assertEqual(hits[0]["sources"], ["image"])
        self.assertEqual(hits[0]["variantId"], "v1")

    async def test_vectors_from_another_model_are_refused(self):
        self.visual.encoder = transport(lambda _r: httpx.Response(200, json={"identity": "other", "embedding": [0.0] * 512}))
        with self.assertRaises(RuntimeError):
            await self.visual.search(PNG, limit=5)

    def test_payload_validation(self):
        self.assertEqual(image_payload(PNG), PNG.split(",", 1)[1])
        with self.assertRaises(InvalidImage):
            image_payload("data:image/png;base64,not base64!!")
        self.assertIsNotNone(ChatRequest(image=PNG).image)


class ImageTurnTests(unittest.IsolatedAsyncioTestCase):
    def test_caption_keeps_only_narrowing_constraints(self):
        turn = _image_search_turn("giống ảnh này nhưng màu đen dưới 500k")
        keys = sorted((item.key, item.operator) for item in turn.tasks[0].constraints)
        self.assertEqual(keys, [("color", "any"), ("price", "lte")])
        self.assertEqual(_image_search_turn("").tasks[0].query, "sản phẩm giống ảnh")

    async def test_photo_search_skips_name_checks_and_rerank(self):
        class Visual:
            async def search(self, _image, _limit):
                return [{"productId": "1" * 24, "vectorScore": 0.9, "sources": ["image"]}]

        class Marketplace:
            async def hydrate_products(self, hits, *_args):
                return [{"id": hit["productId"], "name": "Áo khoác gió", "specifications": []} for hit in hits]

        class Reranker:
            called = False

            async def rerank(self, *_args):
                Reranker.called = True
                return []

        agent = object.__new__(ProductAgent)
        agent.settings = SimpleNamespace(retrieval_limit=30, result_limit=5, max_retrieval_rounds=2)
        agent.retriever = None
        agent.marketplace = Marketplace()
        agent.visual = Visual()
        agent.reranker = Reranker()
        turn = _image_search_turn("")
        result = await agent.retrieve({
            "query": "sản phẩm giống ảnh", "message": "", "request": {"image": PNG},
            "plan": AgentPlan(query="sản phẩm giống ảnh", filters=SearchFilters()).model_dump(),
            "semantic_turn": turn.model_dump(), "retrieval_rounds": 0,
        })
        self.assertEqual([item["id"] for item in result["products"]], ["1" * 24])
        self.assertFalse(Reranker.called)


if __name__ == "__main__":
    unittest.main()
