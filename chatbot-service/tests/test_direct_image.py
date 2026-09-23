import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.agents.product import ProductAgent
from src.agents.state import SearchPlan

PID = "a" * 24
OTHER = "b" * 24


class DirectImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_image_search_keeps_visual_order_without_llm(self):
        api, models, text, visual = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
        visual.collection = "images"
        visual.exists.return_value = True
        visual.embed.return_value = [1.0, 0.0]
        visual.query.return_value = [
            SimpleNamespace(payload={"productId": PID}),
            SimpleNamespace(payload={"productId": OTHER}),
        ]
        api.fresh.return_value = ([
            {"_id": product_id, "name": "Headphones", "price": 100000, "moderationStatus": "approved"}
            for product_id in [OTHER, PID]
        ], {(PID, ""): 3, (OTHER, ""): 4})
        agent = ProductAgent(api, models, text, visual)
        for message in ["", "Tìm sản phẩm giống ảnh này", "Tìm sản phẩm tương tự hình này!"]:
            result = await agent.graph.ainvoke({
                "message": message,
                "image": "image",
                "previous_plan": {"max_price": 1},
                "image_vector": [0.0, 1.0],
                "image_namespace": "images",
            })
            self.assertEqual([product["id"] for product in result["products"]], [PID, OTHER])
            self.assertEqual(result["retrieval_mode"], "image_vector")
            self.assertEqual(result["rounds"], 1)
            self.assertEqual(result["image_vector"], [1.0, 0.0])
        models.structured.assert_not_awaited()
        models.describe.assert_not_awaited()
        models.embed_queries.assert_not_awaited()
        text.query.assert_not_awaited()

    async def test_constraints_and_reference_use_regular_planner(self):
        models = AsyncMock()
        models.describe.return_value = "Áo đỏ"
        models.structured.return_value = SearchPlan(query="áo đỏ")
        agent = ProductAgent(AsyncMock(), models, AsyncMock(), AsyncMock())
        for state in [
            {"message": "Tìm sản phẩm giống ảnh này dưới 500k", "image": "image"},
            {"message": "Tìm sản phẩm giống ảnh này màu đỏ", "image": "image"},
            {"message": "Tìm sản phẩm giống ảnh này", "image": "image", "reference_product_id": PID},
            {"message": "Tìm sản phẩm giống ảnh này"},
        ]:
            result = await agent.understand(state)
            self.assertFalse(result["visual_only"])
        self.assertEqual(models.structured.await_count, 4)

    async def test_visual_failure_is_not_reported_as_no_matches(self):
        visual = AsyncMock()
        visual.collection = "images"
        visual.embed.side_effect = RuntimeError("encoder unavailable")
        agent = ProductAgent(AsyncMock(), AsyncMock(), AsyncMock(), visual)
        with self.assertRaisesRegex(RuntimeError, "encoder unavailable"):
            await agent.graph.ainvoke({"message": "Tìm sản phẩm giống ảnh này", "image": "image"})

    async def test_out_of_stock_image_match_is_filtered(self):
        api, visual = AsyncMock(), AsyncMock()
        visual.collection = "images"
        visual.exists.return_value = True
        visual.embed.return_value = [1.0, 0.0]
        visual.query.return_value = [SimpleNamespace(payload={"productId": PID})]
        api.fresh.return_value = ([
            {"_id": PID, "name": "Headphones", "price": 100000, "moderationStatus": "approved"},
        ], {(PID, ""): 0})
        result = await ProductAgent(api, AsyncMock(), AsyncMock(), visual).graph.ainvoke(
            {"message": "Tìm sản phẩm giống ảnh này", "image": "image"})
        self.assertEqual(result["products"], [])
        self.assertTrue(result["answer"])
