import unittest
from unittest.mock import AsyncMock

from src.agents.commerce import CommerceAgent, resolve_product_reference, resolve_product_references


PRODUCT_ID = "a" * 24
OTHER_ID = "d" * 24
VARIANT_ID = "b" * 24
ADDRESS_ID = "e" * 24


class CommerceAgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.catalog = AsyncMock()
        self.commerce = AsyncMock()
        self.agent = CommerceAgent(self.catalog, self.commerce)
        self.base = {
            "authenticated_user_id": "buyer-1",
            "actor_role": "buyer",
            "session_id": "session-1",
            "previous_products": [{"id": PRODUCT_ID, "name": "Trà sữa"}],
        }

    async def test_variant_is_required_and_followup_adds_selected_variant(self):
        product = {
            "_id": PRODUCT_ID, "name": "Trà sữa", "price": 30000,
            "variants": [
                {"_id": VARIANT_ID, "name": "Size L - Trân châu", "price": 39000},
                {"_id": "c" * 24, "name": "Size M - Thạch", "price": 34000},
            ],
        }
        self.catalog.product.return_value = product
        first = await self.agent.execute({**self.base, "commerce_intent": "add_to_cart", "message": "thêm vào giỏ"})
        self.assertEqual(first["pending_action"]["type"], "cart_configuration")
        self.commerce.add_to_cart.assert_not_awaited()

        self.commerce.add_to_cart.return_value = {"replayed": False}
        self.commerce.cart.return_value = {
            "products": [{"productId": PRODUCT_ID, "variantId": VARIANT_ID, "quantity": 1}]
        }
        self.commerce.checkout_vouchers.return_value = [
            {"code": "SAVE10", "eligible": True, "discountAmount": 10000}
        ]
        second = await self.agent.execute({
            **self.base, "commerce_intent": "configure_cart", "message": "size L trân châu",
            "pending_action": first["pending_action"], "action_request_id": "request-1",
        })
        self.assertEqual(second["pending_action"]["type"], "cart_mutation_confirmation")
        self.commerce.add_to_cart.assert_not_awaited()

        self.assertEqual(self.agent.detect({
            "message": "có", "pending_action": second["pending_action"],
        }), "await_cart_mutation")
        confirmed = await self.agent.execute({
            **self.base,
            "commerce_intent": "confirm_cart_mutation",
            "message": "xác nhận",
            "pending_action": second["pending_action"],
        })
        self.assertEqual(confirmed["action_result"]["status"], "completed")
        call = self.commerce.add_to_cart.await_args.args
        self.assertEqual(call[:4], ("buyer-1", PRODUCT_ID, VARIANT_ID, 1))
        self.assertEqual(call[4], second["pending_action"]["actionId"])
        self.assertIn("SAVE10", confirmed["answer"])
        self.assertTrue(confirmed["action_result"]["checkoutSuggested"])
        self.assertEqual(confirmed["pending_action"]["type"], "checkout_offer")
        self.assertEqual(self.agent.detect({
            "message": "có", "pending_action": confirmed["pending_action"],
        }), "accept_checkout_offer")

        accepted = await self.agent.execute({
            **self.base,
            "commerce_intent": "accept_checkout_offer",
            "message": "có",
            "pending_action": confirmed["pending_action"],
        })
        self.assertEqual(accepted["action_result"]["tool"], "open_checkout")
        self.assertIsNone(accepted["pending_action"])

    async def test_checkout_offer_can_be_declined_without_changing_cart(self):
        pending = {"type": "checkout_offer", "cartLine": {"productId": PRODUCT_ID}}
        state = {**self.base, "message": "không", "pending_action": pending}

        self.assertEqual(self.agent.detect(state), "decline_checkout_offer")
        result = await self.agent.execute({**state, "commerce_intent": "decline_checkout_offer"})

        self.assertEqual(result["action_result"]["status"], "declined")
        self.assertIsNone(result["pending_action"])
        self.commerce.add_to_cart.assert_not_awaited()

    async def test_buy_by_unique_name_reuses_color_and_size_context(self):
        coolmax_id = "f" * 24
        black_large = "1" * 24
        products = [
            {"id": PRODUCT_ID, "name": "Áo thun Cotton Compact Premium"},
            {"id": coolmax_id, "name": "Áo thun Polo Nam Coolmax Premium"},
        ]
        state = {
            **self.base,
            "message": "mua cái coolmax",
            "previous_products": products,
            "previous_plan": {"variant_terms": ["đen", "L"]},
        }
        self.catalog.product.return_value = {
            "_id": coolmax_id,
            "name": "Áo thun Polo Nam Coolmax Premium",
            "price": 240075,
            "variants": [
                {"_id": black_large, "name": "Đen L", "price": 240075},
                {"_id": "2" * 24, "name": "Đen M", "price": 240075},
                {"_id": "3" * 24, "name": "Trắng L", "price": 240075},
            ],
        }

        self.assertEqual(resolve_product_reference("mua cái coolmax", products), coolmax_id)
        self.assertEqual(self.agent.detect(state), "add_to_cart")
        result = await self.agent.execute({**state, "commerce_intent": "add_to_cart"})

        self.assertEqual(result["pending_action"]["type"], "cart_mutation_confirmation")
        self.assertEqual(result["pending_action"]["productId"], coolmax_id)
        self.assertEqual(result["pending_action"]["variantId"], black_large)
        self.commerce.add_to_cart.assert_not_awaited()

    async def test_buy_quantity_uses_the_only_previous_product(self):
        self.catalog.product.return_value = {
            "_id": PRODUCT_ID,
            "name": "Balo Xbags Modern",
            "price": 387000,
            "variants": [],
        }
        state = {**self.base, "message": "mua 2 cái", "focused_product_ids": []}

        self.assertEqual(resolve_product_references("mua 2 cái", self.base["previous_products"]), [PRODUCT_ID])
        self.assertEqual(self.agent.detect(state), "add_to_cart")
        result = await self.agent.execute({**state, "commerce_intent": "add_to_cart"})

        self.assertEqual(result["pending_action"]["productId"], PRODUCT_ID)
        self.assertEqual(result["pending_action"]["quantity"], 2)
        self.commerce.add_to_cart.assert_not_awaited()

    def test_quantity_is_not_mistaken_for_second_product(self):
        products = [
            {"id": PRODUCT_ID, "name": "Balo Xbags"},
            {"id": OTHER_ID, "name": "Balo Coolmax"},
        ]
        self.assertEqual(resolve_product_references("mua 2 cái", products), [])
        self.assertEqual(resolve_product_references("mua cái thứ 2", products), [OTHER_ID])
        self.assertEqual(self.agent.detect({"message": "mua 2 cái", "previous_products": products}), "add_to_cart")

    async def test_ambiguous_buy_keeps_quantity_and_bottom_product_followup(self):
        products = [
            {"id": PRODUCT_ID, "name": "Quần short nam cotton big size"},
            {"id": OTHER_ID, "name": "Quần short thun nam vải cotton"},
        ]
        first_state = {**self.base, "message": "mua 2 cái cotton", "previous_products": products}
        first = await self.agent.execute({**first_state, "commerce_intent": "add_to_cart"})

        self.assertEqual(first["pending_action"]["type"], "cart_product_selection")
        self.assertEqual(first["pending_action"]["quantity"], 2)
        self.assertEqual(resolve_product_reference("cái dưới", products), OTHER_ID)

        self.catalog.product.return_value = {
            "_id": OTHER_ID, "name": products[1]["name"], "price": 85000, "variants": [],
        }
        followup = {
            **self.base,
            "message": "cái dưới",
            "previous_products": products,
            "pending_action": first["pending_action"],
        }
        self.assertEqual(self.agent.detect(followup), "add_to_cart")
        result = await self.agent.execute({**followup, "commerce_intent": "add_to_cart"})

        self.assertEqual(result["pending_action"]["productId"], OTHER_ID)
        self.assertEqual(result["pending_action"]["quantity"], 2)

    async def test_quantity_remove_and_replace_use_fresh_cart_line(self):
        line = {"productId": PRODUCT_ID, "variantId": VARIANT_ID, "quantity": 1}
        self.commerce.cart.return_value = {"products": [line]}
        context = {"type": "cart_line_context", **line}
        changed = await self.agent.execute({
            **self.base, "commerce_intent": "set_quantity", "message": "số lượng 2", "pending_action": context,
        })
        self.assertEqual(changed["pending_action"]["targetQuantity"], 2)
        self.commerce.set_cart_line.assert_not_awaited()
        confirmed_change = await self.agent.execute({
            **self.base, "commerce_intent": "confirm_cart_mutation", "message": "xác nhận",
            "pending_action": changed["pending_action"],
        })
        self.assertEqual(confirmed_change["action_result"]["quantity"], 2)
        self.commerce.set_cart_line.assert_awaited_with("buyer-1", PRODUCT_ID, VARIANT_ID, 2, 1)

        self.commerce.set_cart_line.reset_mock()
        removed = await self.agent.execute({
            **self.base, "commerce_intent": "remove_cart", "message": "không lấy sản phẩm này nữa", "pending_action": context,
        })
        self.assertEqual(removed["pending_action"]["operation"], "remove_cart")
        self.commerce.set_cart_line.assert_not_awaited()
        confirmed_remove = await self.agent.execute({
            **self.base, "commerce_intent": "confirm_cart_mutation", "message": "xác nhận xóa khỏi giỏ",
            "pending_action": removed["pending_action"],
        })
        self.assertIsNone(confirmed_remove["pending_action"])
        self.commerce.set_cart_line.assert_awaited_with("buyer-1", PRODUCT_ID, VARIANT_ID, 0, 1)

        replacement = {"_id": OTHER_ID, "name": "Cà phê", "variants": []}
        self.catalog.product.return_value = replacement
        replaced = await self.agent.execute({
            **self.base,
            "previous_products": [{"id": PRODUCT_ID, "name": "Trà sữa"}, {"id": OTHER_ID, "name": "Cà phê"}],
            "reference_product_id": OTHER_ID, "commerce_intent": "replace_cart", "message": "đổi sang cà phê",
            "pending_action": context,
        })
        self.assertEqual(replaced["pending_action"]["productId"], OTHER_ID)
        self.commerce.replace_cart_line.assert_not_awaited()
        confirmed_replace = await self.agent.execute({
            **self.base, "commerce_intent": "confirm_cart_mutation", "message": "xác nhận đổi sản phẩm",
            "pending_action": replaced["pending_action"],
        })
        self.assertEqual(confirmed_replace["action_result"]["productId"], OTHER_ID)
        self.commerce.replace_cart_line.assert_awaited_once_with("buyer-1", PRODUCT_ID, VARIANT_ID, OTHER_ID, None, 1)

    async def test_view_cart_and_relative_quantity_changes_are_explicit(self):
        self.commerce.cart.return_value = {
            "products": [{"productId": PRODUCT_ID, "variantId": VARIANT_ID, "quantity": 2}]
        }
        self.catalog.product.return_value = {
            "_id": PRODUCT_ID,
            "name": "Trà sữa",
            "price": 30000,
            "variants": [{"_id": VARIANT_ID, "name": "Size L", "price": 39000}],
        }
        viewed = await self.agent.execute({
            **self.base, "commerce_intent": "view_cart", "message": "giỏ hàng có gì",
        })
        self.assertIn("Trà sữa (Size L) × 2", viewed["answer"])
        self.assertIn("78.000 đ", viewed["answer"])
        self.assertEqual(viewed["pending_action"]["type"], "cart_view_context")
        self.commerce.set_cart_line.assert_not_awaited()
        self.commerce.add_to_cart.assert_not_awaited()

        increased = await self.agent.execute({
            **self.base,
            "commerce_intent": "set_quantity",
            "message": "tăng thêm 1",
            "pending_action": viewed["pending_action"],
        })
        self.assertEqual(increased["pending_action"]["targetQuantity"], 3)
        self.commerce.set_cart_line.assert_not_awaited()

        decreased = await self.agent.execute({
            **self.base,
            "commerce_intent": "set_quantity",
            "message": "giảm 2",
            "pending_action": viewed["pending_action"],
        })
        self.assertEqual(decreased["pending_action"]["operation"], "remove_cart")
        self.assertEqual(decreased["pending_action"]["targetQuantity"], 0)
        self.commerce.set_cart_line.assert_not_awaited()

    async def test_named_quantity_update_preserves_compound_checkout_and_followup_context(self):
        headphone_id = "f" * 24
        lines = [
            {"productId": PRODUCT_ID, "variantId": None, "quantity": 1},
            {"productId": headphone_id, "variantId": VARIANT_ID, "quantity": 1},
        ]
        products = {
            PRODUCT_ID: {"_id": PRODUCT_ID, "name": "I Love Christmas", "price": 191500, "shopId": "shop-1", "variants": []},
            headphone_id: {
                "_id": headphone_id,
                "name": "Tai Nghe Nhét Tai New4all CK7 Sport Earphone Kèm Mic - Hàng Chính Hãng",
                "price": 159000,
                "shopId": "shop-1",
                "variants": [{"_id": VARIANT_ID, "name": "Gold", "price": 169000}],
            },
        }
        self.commerce.cart.return_value = {"products": lines}
        self.catalog.product.side_effect = lambda product_id: products.get(product_id)

        viewed = await self.agent.execute({
            **self.base, "commerce_intent": "view_cart", "message": "giỏ hàng có gì",
        })
        prepared = await self.agent.execute({
            **self.base,
            "commerce_intent": "set_quantity",
            "message": "tăng tai nghe lên 2 và thanh toán",
            "pending_action": viewed["pending_action"],
        })
        self.assertEqual(prepared["pending_action"]["productId"], headphone_id)
        self.assertEqual(prepared["pending_action"]["targetQuantity"], 2)
        self.assertEqual(prepared["pending_action"]["nextAction"], "checkout")
        self.commerce.set_cart_line.assert_not_awaited()

        completed = await self.agent.execute({
            **self.base,
            "commerce_intent": "confirm_cart_mutation",
            "message": "xác nhận",
            "pending_action": prepared["pending_action"],
        })
        self.commerce.set_cart_line.assert_awaited_once_with(
            "buyer-1", headphone_id, VARIANT_ID, 2, 1
        )
        self.assertIsNone(completed["pending_action"])
        self.assertEqual(completed["action_result"]["tool"], "open_checkout")
        self.assertTrue(completed["action_result"]["cartChanged"])
        self.assertIn("Đã đổi số lượng thành 2", completed["answer"])

        self.commerce.set_cart_line.reset_mock()
        selection = await self.agent.execute({
            **self.base,
            "commerce_intent": "set_quantity",
            "message": "tăng lên 2 và thanh toán",
            "pending_action": viewed["pending_action"],
        })
        self.assertEqual(selection["pending_action"]["type"], "cart_quantity_selection")
        self.assertEqual(self.agent.detect({
            "message": "Tai Nghe Nhét Tai New4all CK7 Spor",
            "pending_action": selection["pending_action"],
        }), "configure_quantity")
        resumed = await self.agent.execute({
            **self.base,
            "commerce_intent": "configure_quantity",
            "message": "Tai Nghe Nhét Tai New4all CK7 Spor",
            "pending_action": selection["pending_action"],
        })
        self.assertEqual(resumed["pending_action"]["productId"], headphone_id)
        self.assertEqual(resumed["pending_action"]["targetQuantity"], 2)
        self.assertEqual(resumed["pending_action"]["nextAction"], "checkout")
        self.commerce.set_cart_line.assert_not_awaited()

    async def test_details_and_reviews_are_grounded(self):
        self.catalog.product.return_value = {
            "_id": PRODUCT_ID, "name": "Trà sữa", "price": 30000,
            "description": "<p>Trà đen và sữa tươi.</p>", "variants": [],
        }
        self.catalog.review_summaries.return_value = {
            "items": [{"productId": PRODUCT_ID, "averageRating": 4.7, "reviewCount": 21}]
        }
        self.catalog.reviews.return_value = {"items": [{"rating": 5, "comment": "Vị ngon, giao nhanh"}]}
        result = await self.agent.execute({
            **self.base, "commerce_intent": "product_details", "message": "món này mấy sao, khách đánh giá sao?",
            "focused_product_ids": [PRODUCT_ID],
        })
        self.assertIn("4.7/5", result["answer"])
        self.assertIn("Vị ngon", result["answer"])
        self.assertEqual(result["focused_product_ids"], [PRODUCT_ID])

    async def test_checkout_hands_off_without_collecting_payment_data(self):
        self.commerce.cart.return_value = {"products": [{"productId": PRODUCT_ID, "variantId": VARIANT_ID, "quantity": 2}]}
        self.catalog.product.return_value = {
            "_id": PRODUCT_ID, "name": "Trà sữa", "shopId": "shop-1", "price": 30000,
            "variants": [{"_id": VARIANT_ID, "name": "Size L", "price": 39000}],
        }
        self.commerce.checkout_vouchers.return_value = [
            {"code": "SAVE10", "eligible": True, "discountAmount": 10000}
        ]
        self.commerce.addresses.return_value = [
            {"_id": ADDRESS_ID, "label": "Nhà", "line1": "1 Test", "city": "HCM", "phone": "0900000000", "isDefault": True}
        ]
        handoff = await self.agent.execute({**self.base, "commerce_intent": "checkout", "message": "tính tiền"})
        self.assertEqual(handoff["action_result"]["status"], "handoff_required")
        self.assertEqual(handoff["action_result"]["tool"], "open_checkout")
        self.assertIsNone(handoff["action_result"]["paymentMethod"])
        self.assertIsNone(handoff["action_result"]["voucherCode"])
        self.assertEqual(handoff["action_result"]["selectedProductIds"], [f"{PRODUCT_ID}::{VARIANT_ID}"])
        self.assertIsNone(handoff["pending_action"])
        self.commerce.checkout_vouchers.assert_not_awaited()
        self.commerce.addresses.assert_not_awaited()
        self.commerce.checkout_quote.assert_not_awaited()
        self.commerce.confirm_checkout.assert_not_awaited()

    async def test_checkout_without_address_still_opens_checkout_page(self):
        self.commerce.cart.return_value = {"products": [{"productId": PRODUCT_ID, "variantId": None, "quantity": 1}]}
        self.catalog.product.return_value = {"_id": PRODUCT_ID, "name": "Trà", "shopId": "shop-1", "price": 20000, "variants": []}
        self.commerce.checkout_vouchers.return_value = []
        self.commerce.addresses.return_value = []
        result = await self.agent.execute({**self.base, "commerce_intent": "checkout", "message": "thanh toán"})
        self.assertEqual(result["action_result"]["tool"], "open_checkout")
        self.commerce.addresses.assert_not_awaited()

    async def test_checkout_one_line_keeps_other_cart_lines(self):
        cart_lines = [
            {"productId": PRODUCT_ID, "variantId": None, "quantity": 2},
            {"productId": OTHER_ID, "variantId": None, "quantity": 1},
        ]
        products = {
            PRODUCT_ID: {"_id": PRODUCT_ID, "name": "Trà sữa", "shopId": "shop-1", "price": 30000, "variants": []},
            OTHER_ID: {"_id": OTHER_ID, "name": "Cà phê", "shopId": "shop-1", "price": 25000, "variants": []},
        }
        self.commerce.cart.return_value = {"products": cart_lines}
        self.catalog.product.side_effect = lambda product_id: products.get(product_id)
        self.commerce.checkout_vouchers.return_value = []
        self.commerce.addresses.return_value = [
            {"_id": ADDRESS_ID, "label": "Nhà", "line1": "1 Test", "city": "HCM", "phone": "0900000000", "isDefault": True}
        ]
        whole_cart = await self.agent.execute({
            **self.base,
            "commerce_intent": "checkout",
            "message": "thanh toán",
            "pending_action": None,
        })
        self.assertEqual(whole_cart["action_result"]["tool"], "open_checkout")
        self.assertEqual(
            whole_cart["action_result"]["selectedProductIds"],
            [f"{PRODUCT_ID}::", f"{OTHER_ID}::"],
        )
        self.commerce.checkout_vouchers.assert_not_awaited()

        handoff = await self.agent.execute({
            **self.base,
            "commerce_intent": "checkout",
            "message": "chỉ thanh toán cà phê",
            "pending_action": None,
        })
        selected_id = f"{OTHER_ID}::"
        self.assertEqual(handoff["action_result"]["selectedProductIds"], [selected_id])
        self.assertEqual(handoff["action_result"]["tool"], "open_checkout")

        first = await self.agent.execute({
            **self.base, "commerce_intent": "checkout", "message": "tính tiền số 1",
        })
        second = await self.agent.execute({
            **self.base, "commerce_intent": "checkout", "message": "tính tiền số 2",
        })
        self.assertEqual(first["action_result"]["selectedProductIds"], [f"{PRODUCT_ID}::"])
        self.assertEqual(second["action_result"]["selectedProductIds"], [f"{OTHER_ID}::"])
        self.commerce.checkout_quote.assert_not_awaited()
        self.commerce.confirm_checkout.assert_not_awaited()
        self.commerce.set_cart_line.assert_not_awaited()

    async def test_legacy_checkout_confirmation_hands_off_without_creating_order(self):
        pending = {
            "type": "checkout_confirmation",
            "quoteId": "legacy-quote-id",
            "confirmationToken": "secret-token",
            "selectedProductIds": [f"{PRODUCT_ID}::{VARIANT_ID}"],
            "paymentMethod": "bank_transfer",
            "voucherCode": "SAVE10",
            "addressId": ADDRESS_ID,
        }
        result = await self.agent.execute({
            **self.base,
            "commerce_intent": "confirm_checkout",
            "confirm_action_id": "legacy-quote-id",
            "pending_action": pending,
        })
        self.assertEqual(result["action_result"]["status"], "handoff_required")
        self.assertEqual(result["action_result"]["tool"], "open_checkout")
        self.assertIsNone(result["pending_action"])
        self.commerce.confirm_checkout.assert_not_awaited()

    def test_checkout_selection_followup_routes_back_to_checkout(self):
        self.assertEqual(self.agent.detect({
            "message": "chỉ sản phẩm 2",
            "pending_action": {"type": "checkout_selection"},
        }), "checkout")

    def test_checkout_selection_supports_name_and_requires_variant_disambiguation(self):
        items = [
            {"productId": PRODUCT_ID, "variantId": VARIANT_ID, "productName": "Áo cotton", "variantName": "Size L"},
            {"productId": PRODUCT_ID, "variantId": "c" * 24, "productName": "Áo cotton", "variantName": "Size M"},
            {"productId": OTHER_ID, "variantId": None, "productName": "Cà phê", "variantName": None},
        ]
        self.assertEqual(
            self.agent._resolve_checkout_selection({"message": "chỉ thanh toán cà phê"}, items),
            [f"{OTHER_ID}::"],
        )
        self.assertEqual(
            self.agent._resolve_checkout_selection({
                "message": "chỉ thanh toán cà phê",
                "pending_action": {"type": "cart_line_context", "productId": PRODUCT_ID, "variantId": VARIANT_ID},
            }, items),
            [f"{OTHER_ID}::"],
        )
        self.assertEqual(
            self.agent._resolve_checkout_selection({"message": "thanh toán áo cotton"}, items),
            [],
        )
        self.assertEqual(
            self.agent._resolve_checkout_selection({"message": "thanh toán áo cotton size L"}, items),
            [f"{PRODUCT_ID}::{VARIANT_ID}"],
        )
        self.assertEqual(
            self.agent._resolve_checkout_selection({"message": "thanh toán cả giỏ"}, items),
            [f"{PRODUCT_ID}::{VARIANT_ID}", f"{PRODUCT_ID}::{'c' * 24}", f"{OTHER_ID}::"],
        )
        self.assertEqual(
            self.agent._resolve_checkout_selection({"message": "chỉ checkout 1 sản phẩm"}, items),
            [],
        )

    def test_action_detection_and_multiple_references(self):
        products = [
            {"id": PRODUCT_ID, "name": "I Love Christmas"},
            {"id": "b" * 24, "name": "Monster"},
            {"id": "c" * 24, "name": "Wild Ghost"},
            {"id": OTHER_ID, "name": "Sew Trouble"},
        ]
        self.assertEqual(resolve_product_references("so sánh món 1, 4", products), [PRODUCT_ID, OTHER_ID])
        self.assertEqual(resolve_product_reference("Love Christmas nội dung", products), PRODUCT_ID)
        self.assertEqual(self.agent.detect({"message": "thêm vào giỏ"}), "add_to_cart")
        self.assertEqual(self.agent.detect({"message": "số lượng 2"}), "set_quantity")
        self.assertEqual(self.agent.detect({"message": "giỏ hàng có gì"}), "view_cart")
        self.assertEqual(self.agent.detect({"message": "tăng thêm 1"}), "set_quantity")
        self.assertEqual(self.agent.detect({"message": "tính tiền"}), "checkout")
        self.assertEqual(self.agent.detect({"message": "có mã voucher gì cho đơn hàng không"}), "checkout")
        self.assertEqual(self.agent.detect({"message": "cod", "pending_action": {"type": "checkout_handoff"}}), "checkout")
        self.assertEqual(self.agent.detect({
            "message": "xác nhận đặt hàng",
            "pending_action": {"type": "checkout_confirmation", "quoteId": "quote-1"},
        }), "confirm_checkout")
        self.assertEqual(self.agent.detect({"message": "tìm áo cotton"}), "")


if __name__ == "__main__":
    unittest.main()
