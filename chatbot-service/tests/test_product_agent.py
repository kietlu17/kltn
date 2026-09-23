import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from qdrant_client import AsyncQdrantClient
from langchain_google_genai.chat_models import GoogleRateLimitError

from src.agents.product import ProductAgent, RetrievalDecision
from src.agents.router import RouterAgent
from src.agents.state import SearchPlan
from src.core.settings import Settings
from src.product.image_indexer import ImageIndexer
from src.product.rag import ProductRAG
from src.product.visual import VisualCatalog

PID, OTHER = "a" * 24, "b" * 24


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_bayesian_reranker_prefers_well_supported_rating(self):
        api = AsyncMock()
        api.review_summaries.return_value = {
            "globalAverageRating": 4.3,
            "items": [
                {"productId": PID, "averageRating": 5.0, "reviewCount": 1},
                {"productId": OTHER, "averageRating": 4.8, "reviewCount": 100},
            ],
        }
        rag = ProductRAG(api, AsyncMock(), AsyncMock())
        cards = [
            {"id": PID, "name": "One review", "sold": 1},
            {"id": OTHER, "name": "Trusted", "sold": 100},
        ]

        ranked = await rag._rerank(cards, {PID: 1.0, OTHER: 1.0})

        self.assertEqual([card["id"] for card in ranked], [OTHER, PID])
        self.assertEqual(ranked[0]["reviewCount"], 100)
        self.assertEqual(ranked[0]["averageRating"], 4.8)

    async def test_quota_exhaustion_falls_back_to_rag_results(self):
        models = AsyncMock()
        models.structured.side_effect = GoogleRateLimitError("quota exhausted")
        agent = ProductAgent(AsyncMock(), models, AsyncMock())
        agent.rag.chain = AsyncMock()
        agent.rag.chain.ainvoke.return_value = {
            "products": [{"id": PID, "name": "Điện thoại", "price": 9000000}],
            "rounds": 1,
            "retrieval_mode": "text",
        }

        result = await agent.graph.ainvoke({"message": "điện thoại dưới 10 triệu"})

        self.assertEqual([product["id"] for product in result["products"]], [PID])
        self.assertIn("Gemini", result["answer"])
        self.assertTrue(result["warnings"])
        self.assertTrue(result["llm_degraded"])
        self.assertEqual(result["plan"]["max_price"], 10000000)
        self.assertEqual(models.structured.await_count, 1)

    async def test_router_dispatches_to_product_agent_subgraph(self):
        models = AsyncMock()
        models.structured.return_value = SearchPlan(intent="clarify", clarification="Bạn muốn tìm gì?")
        product_agent = ProductAgent(AsyncMock(), models, AsyncMock())
        result = await RouterAgent(product_agent).graph.ainvoke({"message": "hello"})
        self.assertEqual(result["route_name"], "product")
        self.assertEqual(result["answer"], "Bạn muốn tìm gì?")

    async def test_retry_preserves_constraints_and_stops_at_budget(self):
        models = AsyncMock()
        models.structured.side_effect = [
            SearchPlan(query="tai nghe", max_price=500000, variant_terms=["đen"]),
            RetrievalDecision(action="retry", query="tai nghe có mic"),
            RetrievalDecision(action="retry", query="tai nghe chơi game"),
        ]
        agent = ProductAgent(AsyncMock(), models, AsyncMock())
        observed = []

        async def retrieve(state):
            observed.append(dict(state["plan"]))
            return {"products": [], "rounds": state.get("rounds", 0) + 1, "retrieval_mode": "text"}

        agent.rag.chain = AsyncMock()
        agent.rag.chain.ainvoke.side_effect = retrieve
        result = await agent.graph.ainvoke({"message": "tai nghe dưới 500k màu đen"})
        self.assertEqual(len(observed), 2)
        self.assertEqual(result["rounds"], 2)
        self.assertEqual(observed[1]["query"], "tai nghe có mic")
        for item in observed:
            self.assertEqual(item["max_price"], 500000)
            self.assertEqual(item["variant_terms"], ["đen"])

    async def test_accept_ignores_invented_id(self):
        models = AsyncMock()
        models.structured.side_effect = [
            SearchPlan(query="áo"),
            RetrievalDecision(action="accept", product_ids=[PID, "invented"], answer="Áo phù hợp."),
        ]
        agent = ProductAgent(AsyncMock(), models, AsyncMock())
        agent.rag.chain = AsyncMock()
        agent.rag.chain.ainvoke.return_value = {
            "products": [{"id": PID, "name": "Áo"}, {"id": OTHER}],
            "rounds": 1,
            "retrieval_mode": "text",
        }
        result = await agent.graph.ainvoke({"message": "tìm áo"})
        self.assertEqual([product["id"] for product in result["products"]], [PID])
        self.assertEqual(result["answer"], "Áo phù hợp.")

    async def test_clarification_does_not_retrieve(self):
        models = AsyncMock()
        models.structured.return_value = SearchPlan(intent="clarify", clarification="Bạn cần sản phẩm nào?")
        agent = ProductAgent(AsyncMock(), models, AsyncMock())
        agent.rag.chain = AsyncMock()
        result = await agent.graph.ainvoke({"message": "hello"})
        self.assertEqual(result["answer"], "Bạn cần sản phẩm nào?")
        agent.rag.chain.ainvoke.assert_not_awaited()

    async def test_visual_failure_keeps_verified_text_results(self):
        visual = AsyncMock()
        visual.collection = "images"
        visual.embed.side_effect = RuntimeError("offline")
        rag = ProductRAG(AsyncMock(), AsyncMock(), AsyncMock(), visual)
        rag._text_candidates = AsyncMock(return_value={"products": [{"id": PID}]})
        result = await rag.retrieve({
            "message": "ảnh", "image": "bytes", "plan": SearchPlan().model_dump(),
        })
        self.assertEqual(result["products"], [{"id": PID}])
        self.assertTrue(result["warnings"])

    async def test_visual_candidates_are_filtered_by_stock_and_budget(self):
        api, visual = AsyncMock(), AsyncMock()
        visual.collection = "images"
        visual.embed.return_value = [1.0, 0.0]
        visual.exists.return_value = True
        visual.query.return_value = [
            SimpleNamespace(payload={"productId": PID}),
            SimpleNamespace(payload={"productId": OTHER}),
        ]
        api.fresh.return_value = ([
            {"_id": PID, "name": "Áo", "price": 200000, "moderationStatus": "approved"},
            {"_id": OTHER, "name": "Áo khác", "price": 900000, "moderationStatus": "approved"},
        ], {(PID, ""): 3, (OTHER, ""): 3})
        rag = ProductRAG(api, AsyncMock(), AsyncMock(), visual)
        rag._text_candidates = AsyncMock(return_value={"products": []})
        result = await rag.retrieve({
            "message": "ảnh", "image": "bytes", "plan": SearchPlan(max_price=300000).model_dump(),
        })
        self.assertEqual([product["id"] for product in result["products"]], [PID])
        self.assertEqual(result["retrieval_mode"], "text_and_image_vector")


class VisualIndexTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconcile_skips_unsupported_images_without_error_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=directory)
            visual = VisualCatalog(settings, AsyncQdrantClient(location=":memory:"))
            api = AsyncMock()
            api.all_products.return_value = [{
                "_id": PID,
                "name": "Animated image",
                "images": ["/uploads/product.gif"],
                "moderationStatus": "approved",
            }]
            api.image.side_effect = ValueError("unsupported GIF")
            worker = ImageIndexer(settings, api, visual)
            try:
                with self.assertLogs("src.product.image_indexer", level="WARNING") as logs:
                    result = await worker.reconcile()
                self.assertEqual(result["failed"], 1)
                self.assertIn("Skipping unsupported image", logs.output[0])
                self.assertNotIn("Traceback", logs.output[0])
            finally:
                worker.db.close()
                await visual.close()

    async def test_reconcile_cache_failure_deletion_and_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=directory)
            visual = VisualCatalog(settings, AsyncQdrantClient(location=":memory:"))
            visual.embed = AsyncMock(return_value=[1.0] + [0.0] * 511)
            api = AsyncMock()
            product = {"_id": PID, "name": "Áo", "images": ["/uploads/a.jpg"], "moderationStatus": "approved"}
            api.all_products.return_value = [product]
            api.image.return_value = "bytes"
            worker = ImageIndexer(settings, api, visual)
            try:
                await worker.reconcile()
                await worker.reconcile()
                self.assertEqual(visual.embed.await_count, 1)
                self.assertEqual(len(await visual.source_vectors(PID)), 1)
                api.image.side_effect = RuntimeError("download failed")
                await worker.reconcile()
                self.assertEqual(len(await visual.source_vectors(PID)), 1)
                api.image.side_effect = None
                await visual.client.delete_collection(visual.collection)
                await worker.reconcile()
                self.assertEqual(len(await visual.source_vectors(PID)), 1)
                api.all_products.return_value = []
                await worker.reconcile()
                self.assertEqual(await visual.product_ids(), set())
            finally:
                worker.db.close()
                await visual.close()
