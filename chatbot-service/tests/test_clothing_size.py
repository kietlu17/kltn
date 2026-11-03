import json
import unittest
from unittest.mock import AsyncMock

from langchain_google_genai.chat_models import GoogleRateLimitError

from src.agents.clothing_size import ClothingSizeEstimate, SIZE_DISCLAIMER
from src.agents.product import ProductAgent
from src.agents.shopping import explicit_measurements


PID, OTHER = "a" * 24, "b" * 24
PRODUCT = {"_id": PID, "name": "Áo sơ mi nữ linen", "moderationStatus": "approved",
           "variants": [{"_id": "c" * 24, "name": "Trắng / S", "price": 100000}]}


class ClothingSizeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api, self.models, self.vectors = AsyncMock(), AsyncMock(), AsyncMock()
        self.api.product.side_effect = lambda pid: {**PRODUCT, "_id": pid}
        self.models.structured.return_value = ClothingSizeEstimate(size="S–M", reasoning="Form rộng có thể hợp nếu bạn thích mặc thoải mái.")
        self.agent = ProductAgent(self.api, self.models, self.vectors)
        self.cards = [{"id": PID, "name": PRODUCT["name"]}, {"id": OTHER, "name": "Áo sơ mi nữ cotton"}]

    async def turn(self, message, previous=None, **extra):
        return await self.agent.graph.ainvoke({"message": message, "previous_plan": previous or {},
                                              "previous_products": self.cards, **extra})

    async def test_requests_only_missing_inputs_before_calling_llm(self):
        first = await self.turn("tư vấn size áo sơ mi nữ")
        self.assertIn("sản phẩm cụ thể", first["answer"])
        self.assertIn("chiều cao", first["answer"])
        self.assertIn("cân nặng", first["answer"])
        second = await self.turn("tôi cao 1m6", first["plan"])
        self.assertNotIn("chiều cao", second["answer"])
        self.assertIn("cân nặng", second["answer"])
        third = await self.turn("50kg", second["plan"])
        self.assertIn("sản phẩm cụ thể", third["answer"])
        self.assertNotIn("cân nặng", third["answer"])
        self.models.structured.assert_not_awaited()
        self.models.embed_queries.assert_not_awaited()

        final = await self.turn("mẫu thứ hai", third["plan"])
        self.assertEqual(final["plan"]["sizing_product_id"], OTHER)
        self.api.product.assert_awaited_once_with(OTHER)
        self.assertEqual(final["plan"]["height_cm"], 160)
        self.assertEqual(final["plan"]["weight_kg"], 50)
        self.assertIn("size S–M", final["answer"])
        self.assertTrue(final["answer"].endswith(SIZE_DISCLAIMER))
        self.models.structured.assert_awaited_once()

    async def test_link_and_measurements_use_selected_product_without_search(self):
        result = await self.turn(f"Tư vấn size http://localhost:5173/product/{PID}, 160cm 50kg")
        self.assertEqual(result["plan"]["sizing_product_id"], PID)
        self.assertIsNone(result["plan"]["reference_product_id"])
        self.assertEqual(result["flow"], "answer")
        self.assertIn(PRODUCT["name"], result["answer"])
        self.assertIn(SIZE_DISCLAIMER, result["answer"])
        self.assertEqual(result["products"], [])
        messages, schema = self.models.structured.await_args.args
        payload = json.loads(messages[1]["content"])
        self.assertEqual((payload["height_cm"], payload["weight_kg"]), (160, 50))
        self.assertEqual(payload["untrusted_product"]["id"], PID)
        self.assertIs(schema, ClothingSizeEstimate)
        self.models.embed_queries.assert_not_awaited()
        self.vectors.query.assert_not_awaited()

    async def test_selected_product_survives_separate_measurement_turns(self):
        first = await self.turn("tư vấn size mẫu đầu tiên")
        self.assertEqual(first["plan"]["sizing_product_id"], PID)
        second = await self.turn("160cm", first["plan"])
        self.assertEqual(second["plan"]["sizing_product_id"], PID)
        self.assertIn("cân nặng", second["answer"])
        third = await self.turn("nặng 50kg", second["plan"])
        self.assertIn("size S–M", third["answer"])
        self.models.structured.assert_awaited_once()

    async def test_explicit_product_parameter_is_not_similar_search(self):
        result = await self.turn("tư vấn size, cao 1m6 nặng 50kg", reference_product_id=PID)
        self.assertEqual(result["plan"]["sizing_product_id"], PID)
        self.assertEqual(result["plan"]["intent"], "search")
        self.assertIn(SIZE_DISCLAIMER, result["answer"])
        self.api.product.assert_awaited_once_with(PID)

    async def test_current_product_focus_is_used_without_reasking_product(self):
        result = await self.turn("size nào hợp, 160cm 50kg", focused_product_id=OTHER)
        self.assertEqual(result["plan"]["sizing_product_id"], OTHER)
        self.assertIn(SIZE_DISCLAIMER, result["answer"])

    async def test_changed_product_keeps_body_measurements_but_new_search_resets(self):
        first = await self.turn("tư vấn size mẫu đầu tiên, cao 1m6 nặng 50kg")
        changed = await self.turn("mẫu thứ hai", first["plan"])
        self.assertEqual(changed["plan"]["sizing_product_id"], OTHER)
        self.assertEqual(changed["plan"]["height_cm"], 160)
        result = await self.agent.understand({"message": "tìm tai nghe", "previous_plan": changed["plan"], "previous_products": self.cards})
        self.assertIsNone(result["plan"]["sizing_product_id"])
        self.assertIsNone(result["plan"]["height_cm"])
        self.assertEqual(result["plan"]["dialogue_act"], "search")

    async def test_similar_product_button_still_searches_similar_products(self):
        first = await self.turn("tư vấn size mẫu đầu tiên, 160cm 50kg")
        result = await self.agent.understand({"message": "Tìm tương tự", "reference_product_id": PID,
                                             "previous_plan": first["plan"], "previous_products": self.cards})
        self.assertEqual(result["plan"]["intent"], "similar")
        self.assertEqual(result["plan"]["reference_product_id"], PID)
        self.assertIsNone(result["plan"]["sizing_product_id"])

    async def test_unavailable_or_non_clothing_product_never_calls_llm(self):
        self.api.product.side_effect = None
        for product in (None, {**PRODUCT, "moderationStatus": "pending"}, {**PRODUCT, "name": "Tai nghe"}):
            self.api.product.return_value = product
            result = await self.turn(f"tư vấn size /product/{PID}, 160cm 50kg")
            self.assertIsNone(result["plan"]["sizing_product_id"])
        self.models.structured.assert_not_awaited()

    async def test_no_estimate_and_quota_failure_still_include_disclaimer(self):
        self.models.structured.return_value = ClothingSizeEstimate(size=None, reasoning="Chưa đủ cơ sở để ước lượng.")
        result = await self.turn("size mẫu đầu tiên, 160cm 50kg")
        self.assertIn(SIZE_DISCLAIMER, result["answer"])
        self.assertIn("chưa có cơ sở", result["answer"])
        self.assertIn(PRODUCT["name"], result["answer"])
        self.assertNotIn("thử lại", result["answer"])
        self.models.structured.side_effect = GoogleRateLimitError("quota exceeded")
        result = await self.turn("size mẫu đầu tiên, 160cm 50kg")
        self.assertIn(SIZE_DISCLAIMER, result["answer"])
        self.assertNotIn("size S", result["answer"])
        self.assertIn("tạm thời không khả dụng", result["answer"])
        self.assertIn(PRODUCT["name"], result["answer"])
        self.assertEqual(result["plan"]["sizing_product_id"], PID)
        self.models.structured.reset_mock()
        cooldown = await self.turn("tư vấn lại size", result["plan"])
        self.models.structured.assert_not_awaited()
        self.assertIn("160cm", cooldown["answer"])
        self.agent.llm_retry_after = 0
        self.models.structured.side_effect = None
        self.models.structured.return_value = ClothingSizeEstimate(size="M")
        retried = await self.turn("tư vấn lại size", cooldown["plan"])
        self.assertIn("size M", retried["answer"])
        self.assertEqual(retried["plan"]["sizing_product_id"], PID)

    async def test_exact_reported_name_resolves_product_and_measurements(self):
        selected_id = "6ad8cc23a55a838dfd3437b6"
        selected_name = "Áo Sơ Mi Nữ Dáng Suông Trễ Cổ"
        self.cards.append({"id": selected_id, "name": selected_name})
        self.api.product.side_effect = lambda pid: {**PRODUCT, "_id": pid, "name": selected_name}
        first = await self.turn("tôi không biết size nào phù hợp", {
            "intent": "search", "query": "tôi muốn mua áo sơ mi trắng nữ",
            "product_type": "ao_so_mi", "audience": "nu", "variant_terms": ["trắng"],
        })
        result = await self.turn(f"mẫu này {selected_name}, cao 1m60, nặng 50kg", first["plan"])
        self.assertEqual(result["plan"]["sizing_product_id"], selected_id)
        self.assertEqual((result["plan"]["height_cm"], result["plan"]["weight_kg"]), (160, 50))
        self.assertIn(selected_name, result["answer"])
        self.assertIn("size S–M", result["answer"])
        self.api.product.assert_awaited_once_with(selected_id)
        self.models.embed_queries.assert_not_awaited()

    async def test_card_selection_then_measurements_keeps_exact_id(self):
        first = await self.turn("Tư vấn size cho Áo sơ mi nữ cotton", reference_product_id=OTHER)
        self.assertEqual(first["plan"]["sizing_product_id"], OTHER)
        self.assertNotIn("sản phẩm cụ thể", first["answer"])
        result = await self.turn("cao 1m60, nặng 50kg", first["plan"], previous_products=[])
        self.assertEqual(result["plan"]["sizing_product_id"], OTHER)
        self.api.product.assert_awaited_once_with(OTHER)
        self.assertIn("size S–M", result["answer"])

    def test_height_accepts_common_formats_without_reading_bust_as_height(self):
        for message in ("160cm 50kg", "cao 1m6 nặng 50kg", "1.60m 50kg"):
            self.assertEqual(explicit_measurements(message, "ao_so_mi")["height_cm"], 160)
        self.assertNotIn("height_cm", explicit_measurements("vòng ngực 100cm", "ao_so_mi"))
