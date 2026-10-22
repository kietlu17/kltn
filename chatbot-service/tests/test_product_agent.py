import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from qdrant_client import AsyncQdrantClient
from langchain_google_genai.chat_models import GoogleAPIError, GoogleRateLimitError
from pydantic import ValidationError

from src.agents.product import ProductAgent, RetrievalDecision
from src.agents.router import RouterAgent
from src.agents.state import SearchPlan
from src.core.settings import Settings
from src.product.image_indexer import ImageIndexer
from src.product.rag import ProductRAG
from src.product.visual import VisualCatalog

PID, OTHER = "a" * 24, "b" * 24


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_query_clears_optional_checkout_offer(self):
        agent = ProductAgent(AsyncMock(), AsyncMock(), AsyncMock(), commerce=AsyncMock())

        result = await agent.classify_action({
            "message": "tìm balo đi làm",
            "pending_action": {"type": "checkout_offer", "cartLine": {"productId": PID}},
        })

        self.assertEqual(result["commerce_intent"], "")
        self.assertIsNone(result["pending_action"])

    async def test_short_followups_accumulate_product_color_and_use_case(self):
        models = AsyncMock()
        agent = ProductAgent(AsyncMock(), models, AsyncMock())

        first = await agent.understand({"message": "balo nam"})
        second = await agent.understand({
            "message": "màu đỏ",
            "previous_plan": first["plan"],
        })
        third = await agent.understand({
            "message": "phù hợp với văn phòng",
            "previous_plan": second["plan"],
        })
        fourth = await agent.understand({
            "message": "size L",
            "previous_plan": third["plan"],
        })

        self.assertEqual(second["plan"]["query"], "balo nam; màu đỏ")
        self.assertEqual(second["plan"]["variant_terms"], ["đỏ"])
        self.assertEqual(third["plan"]["query"], "balo nam; màu đỏ; phù hợp với văn phòng")
        self.assertEqual(third["plan"]["variant_terms"], ["đỏ"])
        self.assertEqual(fourth["plan"]["variant_terms"], ["đỏ", "L"])
        models.structured.assert_not_awaited()

    async def test_explicit_new_product_does_not_inherit_previous_constraints(self):
        models = AsyncMock()
        agent = ProductAgent(AsyncMock(), models, AsyncMock())

        result = await agent.understand({
            "message": "tai nghe bluetooth",
            "previous_plan": SearchPlan(
                query="balo nam màu đỏ",
                variant_terms=["đỏ"],
                max_price=500000,
            ).model_dump(),
        })

        self.assertEqual(result["plan"]["query"], "tai nghe bluetooth")
        self.assertEqual(result["plan"]["variant_terms"], [])
        self.assertIsNone(result["plan"]["max_price"])

    async def test_default_search_uses_one_final_generation_call(self):
        models = AsyncMock()
        models.structured.return_value = RetrievalDecision(
            action="accept", product_ids=[PID], answer="Tai nghe phù hợp với nhu cầu của bạn."
        )
        agent = ProductAgent(AsyncMock(), models, AsyncMock())
        agent.rag.chain = AsyncMock()
        agent.rag.chain.ainvoke.return_value = {
            "products": [{"id": PID, "name": "Tai nghe", "price": 500000}],
            "rounds": 1,
            "retrieval_mode": "text",
        }

        result = await agent.graph.ainvoke({"message": "tìm tai nghe"})

        self.assertEqual(models.structured.await_count, 1)
        self.assertEqual([item["id"] for item in result["products"]], [PID])
        self.assertEqual(result["answer"], "Tai nghe phù hợp với nhu cầu của bạn.")

    async def test_final_generator_is_used_for_product_detail_question(self):
        models = AsyncMock()
        models.structured.return_value = RetrievalDecision(
            action="accept", product_ids=[PID], answer="Nội dung sách."
        )
        agent = ProductAgent(AsyncMock(), models, AsyncMock())
        agent.rag.chain = AsyncMock()
        agent.rag.chain.ainvoke.return_value = {
            "products": [{"id": PID, "name": "I Love Christmas", "price": 191500}],
            "rounds": 1,
            "retrieval_mode": "text",
        }

        result = await agent.graph.ainvoke({"message": "I Love Christmas nội dung"})

        self.assertEqual(models.structured.await_count, 1)
        self.assertEqual(result["answer"], "Nội dung sách.")

    async def test_high_demand_error_enters_cooldown_and_returns_rag_results(self):
        models = AsyncMock()
        models.structured.side_effect = GoogleAPIError(503, {"message": "high demand"})
        agent = ProductAgent(AsyncMock(), models, AsyncMock())
        agent.rag.chain = AsyncMock()
        agent.rag.chain.ainvoke.return_value = {
            "products": [{"id": PID, "name": "Điện thoại", "price": 9000000}],
            "rounds": 1,
            "retrieval_mode": "text",
        }

        first = await agent.graph.ainvoke({"message": "điện thoại dưới 10 triệu"})
        second = await agent.graph.ainvoke({"message": "điện thoại khác"})

        self.assertEqual(models.structured.await_count, 1)
        self.assertTrue(first["llm_degraded"])
        self.assertTrue(second["llm_degraded"])
        self.assertIn("quá tải", second["answer"])

    async def test_text_retrieval_uses_one_composite_embedding(self):
        api, models, vectors = AsyncMock(), AsyncMock(), AsyncMock()
        api.product.return_value = {"_id": PID, "name": "Áo đỏ", "categoryId": "fashion"}
        models.embed_queries.return_value = [[1.0, 0.0, 0.0]]
        vectors.query.return_value = []
        rag = ProductRAG(api, models, vectors)

        await rag._text_candidates({
            "message": "mẫu tương tự màu xanh",
            "visual_description": "áo cổ tròn màu đỏ",
            "plan": SearchPlan(
                intent="similar",
                query="mẫu tương tự màu xanh",
                reference_product_id=PID,
            ).model_dump(),
        })

        self.assertEqual(len(models.embed_queries.await_args.args[0]), 1)
        vectors.source_visuals.assert_not_awaited()

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
        agent = ProductAgent(AsyncMock(), models, AsyncMock(), use_llm_evaluator=True)
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
        product_agent = ProductAgent(AsyncMock(), models, AsyncMock())
        result = await RouterAgent(product_agent).graph.ainvoke({"message": "hello"})
        self.assertEqual(result["route_name"], "product")
        self.assertEqual(result["answer"], "Bạn muốn tìm sản phẩm nào?")
        models.structured.assert_not_awaited()

    async def test_generator_cannot_start_a_second_retrieval_round(self):
        models = AsyncMock()
        with self.assertRaises(ValidationError):
            RetrievalDecision(action="retry", query="tai nghe có mic")
        models.structured.return_value = RetrievalDecision(action="accept", product_ids=[PID], answer="Sản phẩm phù hợp.")
        agent = ProductAgent(AsyncMock(), models, AsyncMock(), use_llm_evaluator=True)
        observed = []

        async def retrieve(state):
            observed.append(dict(state["plan"]))
            return {"products": [{"id": PID, "name": "Tai nghe"}],
                    "rounds": state.get("rounds", 0) + 1, "retrieval_mode": "text"}

        agent.rag.chain = AsyncMock()
        agent.rag.chain.ainvoke.side_effect = retrieve
        result = await agent.graph.ainvoke({"message": "tai nghe dưới 500k màu đen"})
        self.assertEqual(len(observed), 1)
        self.assertEqual(result["rounds"], 1)
        self.assertEqual(models.structured.await_count, 1)
        for item in observed:
            self.assertEqual(item["max_price"], 500000)
            self.assertEqual(item["variant_terms"], ["đen"])

    async def test_empty_retrieval_does_not_call_gemini(self):
        models = AsyncMock()
        agent = ProductAgent(AsyncMock(), models, AsyncMock())
        agent.rag.chain = AsyncMock()
        agent.rag.chain.ainvoke.return_value = {
            "products": [], "rounds": 1, "retrieval_mode": "text",
        }

        result = await agent.graph.ainvoke({"message": "tìm sản phẩm không có"})

        self.assertEqual(result["rounds"], 1)
        self.assertIn("chưa tìm được", result["answer"])
        agent.rag.chain.ainvoke.assert_awaited_once()
        models.structured.assert_not_awaited()

    async def test_action_plan_skips_retrieval_and_gemini(self):
        models = AsyncMock()
        agent = ProductAgent(AsyncMock(), models, AsyncMock(), commerce=AsyncMock())
        agent.rag.chain = AsyncMock()
        agent.commerce_agent.detect = lambda state: "add_to_cart"
        agent.commerce_agent.execute = AsyncMock(return_value={"answer": "Đã xử lý yêu cầu."})

        result = await agent.graph.ainvoke({"message": "thêm vào giỏ"})

        self.assertEqual(result["flow"], "commerce")
        self.assertEqual(result["answer"], "Đã xử lý yêu cầu.")
        agent.commerce_agent.execute.assert_awaited_once()
        agent.rag.chain.ainvoke.assert_not_awaited()
        models.structured.assert_not_awaited()

    async def test_accept_ignores_invented_id(self):
        models = AsyncMock()
        models.structured.return_value = RetrievalDecision(
            action="accept", product_ids=[PID, "invented"], answer="Áo phù hợp."
        )
        agent = ProductAgent(AsyncMock(), models, AsyncMock(), use_llm_evaluator=True)
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
        agent = ProductAgent(AsyncMock(), models, AsyncMock())
        agent.rag.chain = AsyncMock()
        result = await agent.graph.ainvoke({"message": "hello"})
        self.assertEqual(result["answer"], "Bạn muốn tìm sản phẩm nào?")
        agent.rag.chain.ainvoke.assert_not_awaited()
        models.structured.assert_not_awaited()

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
    async def test_product_events_skip_existing_unchanged_images(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=directory)
            visual = VisualCatalog(settings, AsyncQdrantClient(location=":memory:"))
            visual.embed = AsyncMock(return_value=[1.0] + [0.0] * 511)
            api = AsyncMock()
            item = {"_id": PID, "name": "Áo", "images": ["/uploads/a.jpg"],
                    "variants": [], "moderationStatus": "approved"}
            api.product.return_value = item
            api.image.return_value = "bytes"
            worker = ImageIndexer(settings, api, visual)
            try:
                await worker.process_events([("product.created", PID)])
                await worker.process_events([("product.created", PID), ("product.updated", PID)])
                self.assertEqual(visual.embed.await_count, 1)
                self.assertEqual(api.image.await_count, 1)
            finally:
                worker.db.close()
                await visual.close()

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
