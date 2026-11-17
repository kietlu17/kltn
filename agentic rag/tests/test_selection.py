"""Checkbox pickers: several variants into the cart, chosen cart lines to pay."""

import unittest

from langgraph.checkpoint.memory import MemorySaver

from app.config import AgenticSettings
from app.graph import AgenticShoppingGraph
from app.schemas import ChatRequest, OrderDecision
from test_agents import OrderModels, VariantCard, order_agent, order_state
from test_graph import PRODUCT_ID, FakeRetriever, state

M, L, WHITE_L = "9" * 24, "8" * 24, "7" * 24
SHIRT_OLD, SHIRT_NEW, SPEAKER = "a" * 24, "b" * 24, "c" * 24
V_OLD, V_L, V_XL = "d" * 24, "e" * 24, "f" * 24


class ShirtCart(VariantCard):
    """An older shirt, the L and XL shirt added in this chat, and a speaker."""

    def __init__(self, lines=None):
        super().__init__()
        self.lines = lines or [
            {"productId": SHIRT_OLD, "variantId": V_OLD, "quantity": 1},
            {"productId": SHIRT_NEW, "variantId": V_L, "quantity": 1},
            {"productId": SHIRT_NEW, "variantId": V_XL, "quantity": 1},
            {"productId": SPEAKER, "variantId": None, "quantity": 1},
        ]

    async def cart(self, _user_id):
        return {"products": self.lines}

    async def product(self, product_id):
        return {
            SHIRT_OLD: {"name": "Áo thun trơn", "price": 90000, "variants": [{"id": V_OLD, "name": "Trắng / M"}]},
            SHIRT_NEW: {"name": "Áo thun basic", "price": 150000, "variants": [
                {"id": V_L, "name": "Đen / L", "price": 150000},
                {"id": V_XL, "name": "Đen / XL", "price": 150000},
            ]},
            SPEAKER: {"name": "Loa bluetooth", "price": 500000, "variants": []},
        }[product_id]


def checkout_state(message, added=(), **request):
    current = order_state(message, "checkout", product_id=None)
    current["request"] = request
    current["cart_lines_added"] = list(added)
    return current


class VariantPickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_unclear_variant_returns_a_checkbox_list(self):
        models = OrderModels(OrderDecision(action="clarify", clarification="Bạn lấy size nào?"))
        result = await order_agent(models).prepare_cart(order_state("thêm áo thun", "cart_add"))
        picker = result["tool_result"]["selection"]
        self.assertEqual(picker["type"], "variant_select")
        self.assertTrue(picker["multiple"])
        self.assertEqual([item["id"] for item in picker["options"]], [M, L, WHITE_L])
        self.assertEqual([item["disabled"] for item in picker["options"]], [False, False, True])

    async def test_ticked_variants_become_one_confirmation(self):
        current = order_state("Thêm 2 phiên bản", "cart_add")
        current["request"] = {"referenceProductId": PRODUCT_ID, "variantIds": [M, L, WHITE_L]}
        models = OrderModels()
        result = await order_agent(models).prepare_cart(current)
        payload = result["pending_action"]["payload"]
        # The sold-out variant is dropped; no model call is needed.
        self.assertEqual([item["variantId"] for item in payload["items"]], [M, L])
        self.assertEqual(models.contexts, [])
        self.assertIn("Đen / M, Đen / L", result["pending_action"]["summary"])

    async def test_model_may_pick_several_variants_from_text(self):
        models = OrderModels(OrderDecision(action="add", variant_index=1, variant_indices=[1, 2], confidence=0.9))
        result = await order_agent(models).prepare_cart(order_state("lấy cả size M và L", "cart_add"))
        self.assertEqual([item["variantId"] for item in result["pending_action"]["payload"]["items"]], [M, L])

    async def test_outage_with_two_matches_pre_ticks_both(self):
        current = order_state("lấy màu đen", "cart_add")
        current["selected_options"] = {"colors": ["đen"], "sizes": []}
        result = await order_agent(OrderModels(fail=True)).prepare_cart(current)
        checked = [item["id"] for item in result["tool_result"]["selection"]["options"] if item["checked"]]
        self.assertEqual(checked, [M, L])

    async def test_confirming_records_the_lines_added_in_this_chat(self):
        current = order_state("Thêm", "cart_add")
        current["request"] = {"referenceProductId": PRODUCT_ID, "variantIds": [M, L]}
        agent = order_agent(OrderModels())
        pending = (await agent.prepare_cart(current))["pending_action"]
        confirm = state("Xác nhận", request={"confirmActionId": pending["id"]}, pending=pending)
        result = await agent.resolve_pending(confirm)
        self.assertEqual(result["cart_lines_added"], [f"{PRODUCT_ID}::{M}", f"{PRODUCT_ID}::{L}"])


class CheckoutPickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_named_kind_matching_an_older_line_asks_with_the_chat_lines_ticked(self):
        added = [f"{SHIRT_NEW}::{V_L}"]
        result = await order_agent(OrderModels(), ShirtCart()).prepare_checkout(
            checkout_state("thanh toán đơn áo thun", added)
        )
        picker = result["tool_result"]["selection"]
        self.assertEqual(picker["type"], "checkout_select")
        checked = [item["id"] for item in picker["options"] if item["checked"]]
        self.assertEqual(checked, added)
        self.assertNotIn("status", result["tool_result"])

    async def test_only_chat_lines_named_go_straight_to_checkout(self):
        added = [f"{SHIRT_NEW}::{V_L}", f"{SHIRT_NEW}::{V_XL}"]
        cart = ShirtCart([line for line in ShirtCart().lines if line["productId"] != SHIRT_OLD])
        result = await order_agent(OrderModels(), cart).prepare_checkout(
            checkout_state("thanh toán áo thun", added)
        )
        self.assertEqual(result["tool_result"]["selectedProductIds"], added)

    async def test_ticked_lines_are_paid_and_the_rest_kept(self):
        chosen = [f"{SHIRT_NEW}::{V_L}", f"{SPEAKER}::"]
        result = await order_agent(OrderModels(), ShirtCart()).prepare_checkout(
            checkout_state("Thanh toán các mục đã chọn", checkoutLineIds=chosen)
        )
        self.assertEqual(result["tool_result"]["selectedProductIds"], chosen)
        self.assertIn("vẫn được giữ trong giỏ", result["tool_result"]["handoffMessage"])

    async def test_whole_cart_needs_no_picker(self):
        result = await order_agent(OrderModels(), ShirtCart()).prepare_checkout(checkout_state("thanh toán cả giỏ"))
        self.assertEqual(len(result["tool_result"]["selectedProductIds"]), 4)


class SelectionRequestTests(unittest.IsolatedAsyncioTestCase):
    def test_request_validation(self):
        ChatRequest(referenceProductId=PRODUCT_ID, variantIds=[M])
        ChatRequest(checkoutLineIds=[f"{SHIRT_NEW}::{V_L}", f"{SPEAKER}::"])
        with self.assertRaises(ValueError):
            ChatRequest(message="x", variantIds=[M])
        with self.assertRaises(ValueError):
            ChatRequest(checkoutLineIds=["not-a-line"])

    async def test_picker_turn_skips_the_model_and_routes_to_the_order_agent(self):
        class NoModel:
            async def decide(self, *_args, **_kwargs):
                raise AssertionError("the model must not be called")

        graph = AgenticShoppingGraph(
            AgenticSettings(gemini_api_key="test"), NoModel(), FakeRetriever(), ShirtCart(),
            checkpointer=MemorySaver(),
        )
        current = state("Thêm Đen / M, Đen / L", request={"referenceProductId": PRODUCT_ID, "variantIds": [M, L]})
        understood = await graph.understand(current)
        self.assertIn("UI_SELECTION", understood["warnings"])
        planned = await graph.plan({**current, **understood})
        self.assertEqual(planned["plan"]["intent"], "cart_add")
        self.assertEqual(AgenticShoppingGraph._main_route(planned), "prepare_cart")
        current = state("Thanh toán", request={"checkoutLineIds": [f"{SPEAKER}::"]})
        planned = await graph.plan({**current, **(await graph.understand(current))})
        self.assertEqual(AgenticShoppingGraph._main_route(planned), "prepare_checkout")


if __name__ == "__main__":
    unittest.main()
