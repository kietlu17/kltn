import unittest
from unittest.mock import AsyncMock

from src.agents.intent import TurnIntent
from src.agents.order import OrderAgent
from src.agents.product import ProductAgent
from src.agents.router import RouterAgent
from src.infrastructure.models import ModelClients


class SemanticIntentTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_client_requests_typed_understanding(self):
        client = ModelClients.__new__(ModelClients)
        client.structured = AsyncMock(return_value=TurnIntent(route="customer_service"))

        result = await client.understand_intent({"message": "Tôi cần hỗ trợ về quyền dữ liệu"})

        self.assertEqual(result.route, "customer_service")
        messages, schema = client.structured.await_args.args
        self.assertIs(schema, TurnIntent)
        self.assertIn("quyền dữ liệu", messages[1]["content"])

    async def test_route_uses_meaning_even_without_order_words(self):
        models = AsyncMock()
        models.understand_intent.return_value = TurnIntent(route="order", order_intent="status")
        router = RouterAgent(ProductAgent(AsyncMock(), models, AsyncMock()),
                             order_agent=OrderAgent(AsyncMock()))

        result = await router.route({"message": "Gói tôi đặt giờ tới đâu rồi?"})

        self.assertEqual(result["route_name"], "order")
        self.assertEqual(result["turn_understanding"]["order_intent"], "status")
        models.understand_intent.assert_awaited_once()

    async def test_failed_interpreter_does_not_guess_cart_action_from_words(self):
        models = AsyncMock()
        models.understand_intent.side_effect = ValueError("model unavailable")
        agent = ProductAgent(AsyncMock(), models, AsyncMock(), commerce=AsyncMock())

        result = await agent.classify_action({"message": "Thêm sản phẩm này vào giỏ"})

        self.assertEqual(result["commerce_intent"], "")

    async def test_live_graph_asks_again_when_understanding_is_unavailable(self):
        models = AsyncMock()
        models.understand_intent.side_effect = ValueError("intent unavailable")
        models.interpret_turn.side_effect = ValueError("plan unavailable")
        commerce = AsyncMock()
        agent = ProductAgent(AsyncMock(), models, AsyncMock(), commerce=commerce)

        result = await RouterAgent(agent).graph.ainvoke({"message": "Thêm món này vào giỏ"})

        self.assertEqual(result["commerce_intent"], "")
        self.assertEqual(result["flow"], "answer")
        self.assertIn("thử nói lại", result["answer"])
        commerce.add_to_cart.assert_not_awaited()

    async def test_semantic_catalog_request_accepts_paraphrase(self):
        api, models, vectors = AsyncMock(), AsyncMock(), AsyncMock()
        models.understand_intent.return_value = TurnIntent(browse_catalog=True)
        api.categories.return_value = [{"_id": "books", "name": "Sách"}]
        vectors.category_counts.return_value = {"books": 2}

        result = await ProductAgent(api, models, vectors).graph.ainvoke(
            {"message": "Ở đây có những ngành hàng nào?"},
        )

        self.assertEqual(result["retrieval_mode"], "category_browse")
        self.assertIn("Sách", result["answer"])
        models.interpret_turn.assert_not_awaited()

    async def test_router_passes_understanding_to_product_subgraph(self):
        api, models, vectors = AsyncMock(), AsyncMock(), AsyncMock()
        models.understand_intent.return_value = TurnIntent(browse_catalog=True)
        api.categories.return_value = [{"_id": "books", "name": "Sách"}]
        vectors.category_counts.return_value = {"books": 2}
        router = RouterAgent(ProductAgent(api, models, vectors))

        result = await router.graph.ainvoke({"message": "Ở đây có những ngành hàng nào?"})

        self.assertEqual(result["route_name"], "product")
        self.assertEqual(result["retrieval_mode"], "category_browse")
        models.understand_intent.assert_awaited_once()
