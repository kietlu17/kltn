import unittest
from unittest.mock import AsyncMock

import httpx

from src.agents.order import OrderAgent
from src.agents.product import ProductAgent
from src.agents.router import RouterAgent
from src.core.settings import Settings
from src.infrastructure.clients import CommerceAPI


class OrderAgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.commerce = AsyncMock()
        self.order = OrderAgent(self.commerce)
        self.product = ProductAgent(AsyncMock(), AsyncMock(), AsyncMock())
        self.router = RouterAgent(self.product, None, self.order)

    async def test_status_routes_to_order_tool_and_reports_shipment(self):
        self.commerce.user_orders.return_value = [
            {"id": 42, "user_id": "buyer-1", "status": "shipped"}
        ]
        self.commerce.order_shipment.return_value = {
            "status": "in_transit", "tracking_code": "MOCK-42-ABC"
        }
        result = await self.router.graph.ainvoke({
            "message": "Đơn hàng của tôi ở đâu rồi?",
            "authenticated_user_id": "buyer-1",
            "actor_role": "buyer",
        })
        self.assertEqual(result["route_name"], "order")
        self.assertIn("Đơn #42 hiện đang giao", result["answer"])
        self.assertIn("đang vận chuyển", result["answer"])
        self.assertIn("MOCK-42-ABC", result["answer"])
        self.commerce.user_orders.assert_awaited_once_with("buyer-1")
        self.commerce.order_shipment.assert_awaited_once_with("buyer-1", 42)

    async def test_unauthenticated_order_question_never_calls_tool(self):
        result = await self.router.graph.ainvoke({"message": "Đơn #42 ở đâu?"})
        self.assertEqual(result["route_name"], "order")
        self.assertIn("đăng nhập", result["answer"])
        self.commerce.user_orders.assert_not_awaited()
        self.commerce.order_shipment.assert_not_awaited()

    async def test_order_count_routes_to_order_agent_and_uses_all_owned_orders(self):
        self.commerce.user_orders.return_value = [
            {"id": 79, "status": "pending_payment"},
            {"id": 78, "status": "delivered"},
            {"id": 77, "status": "cancelled"},
        ]
        result = await self.router.graph.ainvoke({
            "message": "Tôi có mấy đơn hàng?",
            "authenticated_user_id": "buyer-1", "actor_role": "buyer",
            "focused_order_id": "79",
        })
        self.assertEqual(result["route_name"], "order")
        self.assertEqual(result["answer"], "Bạn có 3 đơn hàng.")
        self.assertEqual(result["focused_order_id"], "79")
        self.commerce.user_orders.assert_awaited_once_with("buyer-1")
        self.commerce.order_shipment.assert_not_awaited()

    async def test_list_other_orders_excludes_focused_order(self):
        self.commerce.user_orders.return_value = [
            {"id": 79, "status": "pending_payment"},
            {"id": 78, "status": "delivered"},
            {"id": 77, "status": "cancelled"},
        ]
        result = await self.router.graph.ainvoke({
            "message": "Các đơn hàng khác của tôi?",
            "authenticated_user_id": "buyer-1", "actor_role": "buyer",
            "focused_order_id": "79",
        })
        self.assertEqual(result["route_name"], "order")
        self.assertIn("(2 đơn)", result["answer"])
        self.assertIn("#78", result["answer"])
        self.assertIn("#77", result["answer"])
        self.assertNotIn("#79", result["answer"])
        self.assertEqual(result["focused_order_id"], "79")
        self.commerce.order_shipment.assert_not_awaited()

    async def test_explicit_other_order_updates_focus_and_reads_owned_shipment(self):
        self.commerce.user_orders.return_value = [
            {"id": 79, "status": "pending_payment"},
            {"id": 77, "status": "shipped"},
        ]
        self.commerce.order_shipment.return_value = {"status": "in_transit"}
        result = await self.router.graph.ainvoke({
            "message": "Đơn #77 của tôi ở đâu?",
            "authenticated_user_id": "buyer-1", "actor_role": "buyer",
            "focused_order_id": "79",
        })
        self.assertIn("#77", result["answer"])
        self.assertEqual(result["focused_order_id"], "77")
        self.commerce.order_shipment.assert_awaited_once_with("buyer-1", 77)

    async def test_plain_numeric_order_id_routes_without_product_search(self):
        self.commerce.user_orders.return_value = [{"id": 79, "status": "pending_payment"}]
        result = await self.router.graph.ainvoke({
            "message": "đơn 79", "authenticated_user_id": "buyer-1", "actor_role": "buyer",
        })
        self.assertEqual(result["route_name"], "order")
        self.assertIn("Đơn #79 hiện chờ thanh toán", result["answer"])
        self.assertEqual(result["focused_order_id"], "79")

    async def test_order_by_product_title_selects_owned_order_instead_of_old_focus(self):
        self.commerce.user_orders.return_value = [
            {"id": 79, "status": "pending_payment", "products": [{"productName": "Áo thun nam"}]},
            {"id": 38, "status": "shipped", "products": [{"productName": "I Love Christmas"}]},
        ]
        self.commerce.order_shipment.return_value = {"status": "in_transit"}
        result = await self.router.graph.ainvoke({
            "message": "đơn I Love Christmas đang ở đâu",
            "authenticated_user_id": "buyer-1", "actor_role": "buyer",
            "focused_order_id": "79",
        })
        self.assertEqual(result["route_name"], "order")
        self.assertIn("Đơn #38 hiện đang giao", result["answer"])
        self.assertIn("I Love Christmas", result["answer"])
        self.assertEqual(result["focused_order_id"], "38")
        self.commerce.order_shipment.assert_awaited_once_with("buyer-1", 38)

    async def test_order_by_product_type_asks_for_id_when_multiple_match(self):
        self.commerce.user_orders.return_value = [
            {"id": 79, "status": "pending_payment", "products": [{"productName": "Áo thun nam Cotton"}]},
            {"id": 45, "status": "shipped", "products": [{"productName": "Áo thun nam Premium"}]},
            {"id": 38, "status": "delivered", "products": [{"productName": "I Love Christmas"}]},
        ]
        result = await self.router.graph.ainvoke({
            "message": "đơn áo thun đang ở đâu", "authenticated_user_id": "buyer-1", "actor_role": "buyer",
        })
        self.assertEqual(result["route_name"], "order")
        self.assertIn("2 đơn hàng khớp", result["answer"])
        self.assertIn("#79", result["answer"])
        self.assertIn("#45", result["answer"])
        self.assertNotIn("#38", result["answer"])
        self.commerce.order_shipment.assert_not_awaited()

    async def test_order_book_query_uses_order_items_and_clarifies_if_no_match(self):
        self.commerce.user_orders.return_value = [
            {"id": 79, "status": "pending_payment", "products": [{"productName": "I Love Christmas"}]},
        ]
        result = await self.router.graph.ainvoke({
            "message": "đơn hàng sách", "authenticated_user_id": "buyer-1", "actor_role": "buyer",
        })
        self.assertEqual(result["route_name"], "order")
        self.assertIn("tên sản phẩm đầy đủ hơn hoặc mã đơn", result["answer"])
        self.assertNotIn("quyền truy cập", result["answer"])
        self.commerce.order_shipment.assert_not_awaited()

    async def test_order_word_in_product_adjective_does_not_route_to_order(self):
        self.assertFalse(self.router._is_order("đơn giản và đẹp"))

    async def test_count_reloads_orders_instead_of_using_conversation_history(self):
        self.commerce.user_orders.side_effect = [
            [{"id": 79, "status": "pending_payment"}],
            [{"id": 79, "status": "pending_payment"}, {"id": 78, "status": "delivered"}],
        ]
        state = {"message": "Tôi có mấy đơn hàng?", "authenticated_user_id": "buyer-1", "actor_role": "buyer"}
        first = await self.order.graph.ainvoke(state)
        second = await self.order.graph.ainvoke(state)
        self.assertEqual(first["answer"], "Bạn có 1 đơn hàng.")
        self.assertEqual(second["answer"], "Bạn có 2 đơn hàng.")
        self.assertEqual(self.commerce.user_orders.await_count, 2)

    async def test_other_buyers_order_is_not_looked_up_by_shipment_id(self):
        self.commerce.user_orders.return_value = [{"id": 42, "status": "shipped"}]
        result = await self.order.graph.ainvoke({
            "message": "Đơn #99 ở đâu?",
            "authenticated_user_id": "buyer-1", "actor_role": "buyer",
        })
        self.assertIn("không tìm thấy", result["answer"])
        self.commerce.order_shipment.assert_not_awaited()

    async def test_return_question_does_not_invent_ten_day_policy(self):
        self.commerce.user_orders.return_value = [{
            "id": 42, "status": "delivered", "delivered_at": "2026-10-06T03:00:00Z"
        }]
        result = await self.router.graph.ainvoke({
            "message": "Tôi đã mua được 10 ngày thì có đổi được không?",
            "authenticated_user_id": "buyer-1", "actor_role": "buyer",
        })
        self.assertEqual(result["route_name"], "order")
        self.assertIn("Đơn #42", result["answer"])
        self.assertIn("06/10/2026", result["answer"])
        self.assertIn("chưa thể xác nhận", result["answer"])
        self.commerce.order_shipment.assert_not_awaited()

    async def test_return_question_with_multiple_orders_asks_for_id(self):
        self.commerce.user_orders.return_value = [
            {"id": 42, "status": "delivered"},
            {"id": 41, "status": "delivered"},
        ]
        result = await self.order.graph.ainvoke({
            "message": "Tôi đã mua 10 ngày, có đổi được không?",
            "authenticated_user_id": "buyer-1", "actor_role": "buyer",
        })
        self.assertIn("Vui lòng cho tôi mã đơn", result["answer"])

    async def test_generic_policy_question_keeps_customer_service_route(self):
        self.assertFalse(self.router._is_order("Chính sách đổi trả của sàn là gì?"))

    async def test_commerce_reads_use_buyer_identity_and_only_get(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.url.path.endswith("/orders/user"):
                return httpx.Response(200, json=[{"id": 42}])
            return httpx.Response(200, json={"order_id": 42, "status": "in_transit"})

        client = CommerceAPI(Settings())
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            self.assertEqual(await client.user_orders("buyer-1"), [{"id": 42}])
            self.assertEqual((await client.order_shipment("buyer-1", 42))["status"], "in_transit")
        finally:
            await client.close()
        self.assertEqual([request.method for request in requests], ["GET", "GET"])
        self.assertEqual([request.headers["x-user-id"] for request in requests], ["buyer-1", "buyer-1"])
        self.assertTrue(all(request.headers["x-user-role"] == "buyer" for request in requests))
