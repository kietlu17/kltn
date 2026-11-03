import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from langchain_google_genai.chat_models import GoogleRateLimitError

from src.agents.product import ProductAgent
from src.agents.size_search import ClothingSearchEstimate, prioritize_estimated_sizes
from src.agents.clothing_size import ClothingSizeEstimate, SIZE_DISCLAIMER
from src.infrastructure.models import ModelClients
from src.product.catalog import eligible_cards, query_metadata
from src.product.rag import ProductRAG


class SizeSearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api, self.models, self.vectors = AsyncMock(), AsyncMock(), AsyncMock()
        self.agent = ProductAgent(self.api, self.models, self.vectors)
        self.models.structured.return_value = ClothingSearchEstimate(sizes=["S", "M"])
        self.cards = [{"id": "a" * 24, "name": "Áo sơ mi nữ trắng", "variants": [{"name": "Trắng / M"}]}]
        self.agent.rag.chain = SimpleNamespace(ainvoke=AsyncMock(return_value={"products": self.cards}))

    async def turn(self, message, previous=None, **extra):
        return await self.agent.graph.ainvoke({"message": message, "previous_plan": previous or {}, **extra})

    async def test_reported_request_and_browse_followup_do_not_ask_for_product(self):
        first = await self.turn("nữ, cao 1m60, nặng 50kg thì áo sơ mi trắng nào phù hợp")
        second = await self.turn("cho tôi xem vài mẫu", first["plan"])
        for result in (first, second):
            plan = result["plan"]
            self.assertEqual(result["flow"], "retrieve")
            self.assertEqual(plan["dialogue_act"], "size_search")
            self.assertEqual((plan["product_type"], plan["audience"]), ("ao_so_mi", "nu"))
            self.assertEqual((plan["height_cm"], plan["weight_kg"]), (160, 50))
            self.assertEqual(plan["variant_terms"], ["trắng"])
            self.assertEqual(plan["estimated_sizes"], ["S", "M"])
            self.assertEqual(query_metadata(plan)["sizes"], [])
            self.assertNotIn("50", plan["query"])
            self.assertEqual(result["products"], self.cards)
            self.assertNotIn("sản phẩm cụ thể", result["answer"])
            self.assertIn(SIZE_DISCLAIMER, result["answer"])
        self.models.web_size_estimate.assert_not_awaited()

    async def test_browse_escapes_old_questionnaire_checkpoint(self):
        old = {"dialogue_act": "size_advice", "intent": "search", "query": "áo sơ mi nữ trắng",
               "product_type": "ao_so_mi", "audience": "nu", "variant_terms": ["trắng"],
               "height_cm": 160, "weight_kg": 50}
        result = await self.turn("cho tôi xem vài mẫu", old)
        self.assertEqual(result["flow"], "retrieve")
        self.assertEqual(result["products"], self.cards)
        self.assertEqual(result["plan"]["height_cm"], 160)

    async def test_purchase_without_size_collects_measurements_then_searches(self):
        first = await self.turn("tôi muốn mua áo thun nam mà không biết size")
        self.assertEqual(first["plan"]["dialogue_act"], "size_search")
        self.assertIn("chiều cao", first["answer"])
        self.assertIn("cân nặng", first["answer"])
        self.assertNotIn("sản phẩm cụ thể", first["answer"])
        self.models.structured.assert_not_awaited()
        self.agent.rag.chain.ainvoke.assert_not_awaited()
        height = await self.turn("tôi cao 1m7", first["plan"])
        self.assertNotIn("chiều cao", height["answer"])
        self.assertIn("cân nặng", height["answer"])
        for previous, message in ((first["plan"], "tôi cao 1m7, nặng 60kg"), (height["plan"], "nặng 60kg")):
            result = await self.turn(message, previous)
            self.assertEqual(result["plan"]["dialogue_act"], "size_search")
            self.assertEqual(result["plan"]["product_type"], "ao_thun")
            self.assertEqual(result["plan"]["audience"], "nam")
            self.assertEqual((result["plan"]["height_cm"], result["plan"]["weight_kg"]), (170, 60))
            self.assertEqual(result["products"], self.cards)
            self.assertNotIn("sản phẩm cụ thể", result["answer"])
            again = await self.turn("mẫu", result["plan"])
            self.assertEqual(again["products"], self.cards)

    async def test_existing_purchase_checkpoint_recovers_on_measurement_reply(self):
        old = {"intent": "search", "dialogue_act": "size_advice", "product_type": "ao_thun",
               "audience": "nam", "query": "tôi muốn mua áo thun nam mà không biết size"}
        result = await self.turn("tôi cao 1m7, nặng 60kg", old)
        self.assertEqual(result["plan"]["dialogue_act"], "size_search")
        self.assertEqual(result["products"], self.cards)
        old.update(height_cm=170, weight_kg=60)
        result = await self.turn("mẫu", old)
        self.assertEqual(result["products"], self.cards)

    async def test_category_availability_with_measurements_searches_immediately(self):
        for message in (
            "nữ cao 1m50, nặng 50kg, có áo thun nào không?",
            "nữ cao 1m50, nặng 50kg, có áo thun không?",
            "áo thun nữ cho người cao 150cm nặng 50kg",
        ):
            with self.subTest(message=message):
                result = await self.turn(message)
                self.assertEqual(result["flow"], "retrieve")
                self.assertEqual(result["plan"]["dialogue_act"], "size_search")
                self.assertEqual(result["plan"]["product_type"], "ao_thun")
                self.assertEqual(result["plan"]["audience"], "nu")
                self.assertEqual(result["plan"]["height_cm"], 150)
                self.assertEqual(result["plan"]["weight_kg"], 50)
                self.assertEqual(result["products"], self.cards)
                self.assertNotIn("sản phẩm cụ thể", result["answer"])
                followup = await self.turn("cho xem mẫu", result["plan"])
                self.assertEqual(followup["plan"]["product_type"], "ao_thun")
                self.assertEqual(followup["plan"]["height_cm"], 150)
                self.assertEqual(followup["flow"], "retrieve")

    async def test_explicit_size_question_still_uses_product_specific_flow(self):
        result = await self.turn("tư vấn size áo thun nữ, cao 150cm nặng 50kg")
        self.assertEqual(result["flow"], "answer")
        self.assertEqual(result["plan"]["dialogue_act"], "size_advice")
        self.models.structured.assert_not_awaited()

    async def test_selecting_search_result_returns_to_product_specific_size_advice(self):
        first = await self.turn("nữ, cao 1m60, nặng 50kg thì áo sơ mi trắng nào phù hợp")
        self.api.product.return_value = {"_id": "a" * 24, "name": self.cards[0]["name"], "moderationStatus": "approved"}
        self.models.structured.return_value = ClothingSizeEstimate(size="M")
        selected = await self.turn("Tư vấn size cho mẫu này", first["plan"], reference_product_id="a" * 24)
        self.assertEqual(selected["plan"]["sizing_product_id"], "a" * 24)
        self.assertEqual(selected["plan"]["height_cm"], 160)
        self.assertIn("size M", selected["answer"])

    async def test_web_fallback_and_no_estimate_still_show_products(self):
        self.models.structured.return_value = ClothingSearchEstimate()
        self.models.web_size_estimate.return_value = (ClothingSearchEstimate(sizes=["M"]), ["https://example.org/chart"])
        result = await self.turn("tìm áo sơ mi nữ trắng, cao 160cm nặng 50kg")
        self.assertEqual(result["plan"]["size_estimate_source"], "web")
        self.assertIn("https://example.org/chart", result["answer"])
        self.models.web_size_estimate.return_value = (ClothingSearchEstimate(), [])
        result = await self.turn("tìm áo sơ mi nữ trắng, cao 160cm nặng 50kg")
        self.assertEqual(result["products"], self.cards)
        self.assertIn("chưa có cơ sở", result["answer"])
        self.models.structured.side_effect = GoogleRateLimitError("unavailable")
        result = await self.turn("tìm áo sơ mi nữ trắng, cao 160cm nặng 50kg")
        self.assertEqual(result["products"], self.cards)

    async def test_explicit_size_wins_and_new_topic_resets_body_search(self):
        result = await self.turn("tìm áo sơ mi nữ trắng size L, cao 160cm nặng 50kg")
        self.models.structured.assert_not_awaited()
        self.assertEqual(query_metadata(result["plan"])["sizes"], ["L"])
        next_plan = await self.agent.understand({"message": "tìm tai nghe", "previous_plan": result["plan"]})
        self.assertEqual(next_plan["plan"]["dialogue_act"], "search")
        self.assertIsNone(next_plan["plan"]["height_cm"])
        self.assertEqual(next_plan["plan"]["estimated_sizes"], [])

    async def test_size_ranking_precedes_six_card_cutoff(self):
        rag = ProductRAG(self.api, self.models, self.vectors)
        cards = [{"id": str(i), "variants": [{"name": "Trắng / XL"}]} for i in range(6)]
        cards.append({"id": "match", "variants": [{"name": "Trắng / M"}]})
        self.models.embed_queries.return_value = [[1.0]]
        self.vectors.query.return_value = []
        rag._fresh_cards = AsyncMock(return_value=cards)
        rag._rerank = AsyncMock(return_value=cards)
        result = await rag._text_candidates({"message": "áo sơ mi", "plan": {
            "intent": "search", "query": "áo sơ mi nữ trắng", "estimated_sizes": ["M"]}})
        self.assertEqual(result["products"][0]["id"], "match")
        self.assertEqual(len(result["products"]), 6)

    def test_size_match_must_be_on_same_in_stock_white_variant(self):
        products = [{"_id": pid, "name": "Áo sơ mi nữ", "moderationStatus": "approved",
                     "variants": [{"_id": "1", "name": "Trắng / XL", "price": 100},
                                  {"_id": "2", "name": "Đen / M", "price": 100},
                                  {"_id": "3", "name": "Trắng / M", "price": 100}]}
                    for pid in ("bad", "good")]
        stock = {(pid, vid): 5 for pid in ("bad", "good") for vid in ("1", "2", "3")}
        stock["bad", "3"] = 0
        plan = {"product_type": "ao_so_mi", "audience": "nu", "variant_terms": ["trắng"], "estimated_sizes": ["M"]}
        cards = eligible_cards(products, stock, ["bad", "good"], plan)
        ranked = prioritize_estimated_sizes(cards, plan)
        self.assertEqual([c["id"] for c in ranked], ["good", "bad"])


class WebSizeFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_grounded_web_results_are_used(self):
        client = ModelClients.__new__(ModelClients)
        response = SimpleNamespace(text="Size guidance", response_metadata={})
        search = SimpleNamespace(ainvoke=AsyncMock(return_value=response))
        client.llm = SimpleNamespace(bind_tools=Mock(return_value=search))
        client.structured = AsyncMock(return_value=ClothingSearchEstimate(sizes=["M"]))
        estimate, sources = await client.web_size_estimate([], ClothingSearchEstimate)
        self.assertEqual(estimate.sizes, [])
        client.structured.assert_not_awaited()
        response.response_metadata = {"grounding_metadata": {
            "grounding_chunks": [{"web": {"uri": "https://example.org/chart"}}],
            "grounding_supports": [{"grounding_chunk_indices": [0]}]}}
        estimate, sources = await client.web_size_estimate([], ClothingSearchEstimate)
        self.assertEqual(estimate.sizes, ["M"])
        self.assertEqual(sources, ["https://example.org/chart"])
        client.llm.bind_tools.assert_called_with([{"google_search": {}}])
