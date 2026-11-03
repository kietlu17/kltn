import time
import unittest

from langgraph.checkpoint.memory import MemorySaver

from app.config import AgenticSettings
from app.graph import (
    AgenticShoppingGraph,
    _continues_active_product,
    _focused_references,
    _requests_purchase,
)
from app.schemas import AgentPlan, PendingAction, SearchFilters, TurnUnderstanding


PRODUCT_ID = "a" * 24
VARIANT_ID = "b" * 24
ADDRESS_ID = "c" * 24
GALAXY_5G_ID = "d" * 24
GALAXY_ID = "e" * 24
REDMI_ID = "f" * 24
BASIC_ID = "1" * 24


class FakeModels:
    def __init__(self):
        self.next_plan = AgentPlan(intent="product_search", query="áo trắng")
        self.next_understanding = TurnUnderstanding()
        self.understand_calls = []

    async def understand(self, message, *_args, **_kwargs):
        self.understand_calls.append(message)
        return self.next_understanding

    async def plan(self, *_args, **_kwargs):
        return self.next_plan

    async def answer(self, _message, _plan, _result, products, _history):
        return f"Có {len(products)} kết quả đã kiểm tra."


class FakeRetriever:
    def __init__(self):
        self.calls = []

    async def search(self, query, filters, limit=None, sort_by="relevance"):
        self.calls.append((query, filters.model_dump(), limit, sort_by))
        return [{"productId": PRODUCT_ID, "vectorScore": 0.8}]

    async def product_context(self, product_id):
        return getattr(
            self,
            "anchor_context",
            {
                "productId": product_id,
                "productType": "ao_thun",
                "audience": ["nam"],
                "colors": ["den", "xam"],
                "sizes": ["M", "L", "XL"],
                "minPrice": 589000,
                "maxPrice": 589000,
                "text": "Áo thun nam cổ tròn tay ngắn",
            },
        )


class FakeMarketplace:
    def __init__(self):
        self.cart_writes = []
        self.confirmed_quotes = []
        self.product_filters = []

    async def categories(self):
        return [{"id": "fashion", "name": "Thời trang"}]

    async def hydrate_products(self, hits, _filters, _limit):
        return [await self.product_card(hits[0]["productId"])] if hits else []

    async def product_card(self, product_id, filters=None):
        self.product_filters.append(filters)
        return {
            "id": product_id,
            "name": "Áo sơ mi trắng",
            "price": 250000,
            "imageUrl": "",
            "shopId": "shop-1",
            "url": f"/product/{product_id}",
            "description": "Áo sơ mi",
            "score": 0.8,
            "variants": [
                {
                    "id": VARIANT_ID,
                    "name": "Trắng / M",
                    "price": 250000,
                    "availableStock": 5,
                    "imageUrl": "",
                }
            ],
        }

    async def cart(self, _user_id):
        return {
            "products": [
                {"productId": PRODUCT_ID, "variantId": VARIANT_ID, "quantity": 1}
            ]
        }

    async def add_to_cart(self, user_id, product_id, variant_id, quantity, action_id):
        self.cart_writes.append((user_id, product_id, variant_id, quantity, action_id))
        return {"changed": True}

    async def set_cart_line(self, user_id, product_id, variant_id, quantity):
        self.cart_writes.append((user_id, product_id, variant_id, quantity, "set"))
        return {"changed": True}

    async def addresses(self, _user_id):
        return [{"_id": ADDRESS_ID, "address": "Hà Nội"}]

    async def checkout_quote(
        self, _user_id, _session_id, products, _address_id, _payment_method, _voucher
    ):
        return {
            "quoteId": "quote-1",
            "products": products,
            "totalPrice": 250000,
            "confirmationToken": "server-secret",
            "status": "open",
        }

    async def confirm_checkout(self, user_id, session_id, quote_id, token):
        self.confirmed_quotes.append((user_id, session_id, quote_id, token))
        return {"orderIds": [101], "status": "committed"}

    async def orders(self, _user_id):
        return []

    async def shipment(self, _user_id, _order_id):
        return None


class VariantMarketplace(FakeMarketplace):
    async def product_card(self, product_id, filters=None):
        self.product_filters.append(filters)
        variants = []
        for color in ("Be", "ĐEN", "Đỏ"):
            for size in ("M", "L", "XL", "2XL"):
                variants.append(
                    {
                        "id": VARIANT_ID,
                        "name": f"{color} / {size}",
                        "price": 249000,
                        "availableStock": 5,
                        "imageUrl": "",
                    }
                )
        return {
            "id": product_id,
            "name": "Áo Thun Nam Dream Team",
            "price": 249000,
            "imageUrl": "",
            "shopId": "shop-1",
            "url": f"/product/{product_id}",
            "description": "Áo thun nam chất liệu cotton.",
            "score": 0.8,
            "variants": variants,
        }


def state(message, request=None, pending=None):
    return {
        "message": message,
        "user_id": "buyer-1",
        "role": "buyer",
        "session_id": "session-test",
        "history": [],
        "request": request or {},
        "understanding": {},
        "search_context": {},
        "plan": {},
        "query": "",
        "retrieval_rounds": 0,
        "retrieval_hits": [],
        "products": [],
        "render_product_cards": True,
        "tool_result": {},
        "answer": "",
        "pending_action": pending,
        "focused_products": [],
        "active_product_id": None,
        "warnings": [],
        "route": "",
        "session_expires_at": time.time() + 600,
        "committed": False,
    }


class AgentGraphTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.models = FakeModels()
        self.retriever = FakeRetriever()
        self.marketplace = FakeMarketplace()
        self.settings = AgenticSettings(gemini_api_key="test")
        self.agent = AgenticShoppingGraph(
            self.settings,
            self.models,
            self.retriever,
            self.marketplace,
            checkpointer=MemorySaver(),
        )

    async def test_search_returns_only_fresh_hydrated_cards(self):
        config = {"configurable": {"thread_id": "search"}}
        result = await self.agent.graph.ainvoke(state("áo trắng"), config=config)
        self.assertEqual(result["products"][0]["id"], PRODUCT_ID)
        self.assertEqual(result["retrieval_rounds"], 1)
        # A plain search is answered by template; the cards carry the facts.
        self.assertIn("Mình tìm thấy 1 sản phẩm", result["answer"])
        self.assertIn("Áo sơ mi trắng (250.000đ)", result["answer"])

    async def test_single_search_result_becomes_the_active_product(self):
        config = {"configurable": {"thread_id": "single-active"}}
        result = await self.agent.graph.ainvoke(
            state("áo thun mắc nhất"), config=config
        )

        self.assertEqual(result["active_product_id"], PRODUCT_ID)
        self.assertEqual(
            result["search_context"]["anchor_product_id"], PRODUCT_ID
        )

    async def test_named_followup_uses_only_products_already_in_focus(self):
        current = state("Galaxy A07 5G và Xiaomi Redmi 15 5G")
        current["focused_products"] = [
            {"id": GALAXY_5G_ID, "name": "Điện thoại Samsung Galaxy A07 5G"},
            {"id": GALAXY_ID, "name": "Điện thoại Samsung Galaxy A07"},
            {"id": REDMI_ID, "name": "Điện thoại Xiaomi Redmi 15 5G"},
        ]
        planned = await self.agent.plan(current)
        self.assertEqual(
            set(planned["plan"]["product_ids"]), {GALAXY_5G_ID, REDMI_ID}
        )
        self.assertFalse(planned["render_product_cards"])
        self.assertNotIn(GALAXY_ID, planned["plan"]["product_ids"])

        retrieved = await self.agent.retrieve({**current, **planned})
        self.assertEqual(self.retriever.calls, [])
        self.assertEqual(
            {hit["productId"] for hit in retrieved["retrieval_hits"]},
            {GALAXY_5G_ID, REDMI_ID},
        )

    async def test_named_purchase_routes_to_cart_without_broad_search(self):
        current = state("tôi muốn mua a07 5g")
        current["focused_products"] = [
            {"id": GALAXY_5G_ID, "name": "Điện thoại Samsung Galaxy A07 5G"},
            {"id": GALAXY_ID, "name": "Điện thoại Samsung Galaxy A07"},
            {"id": REDMI_ID, "name": "Điện thoại Xiaomi Redmi 15 5G"},
        ]
        planned = await self.agent.plan(current)
        self.assertEqual(planned["plan"]["intent"], "cart_add")
        self.assertEqual(planned["plan"]["product_id"], GALAXY_5G_ID)
        self.assertEqual(planned["plan"]["product_ids"], [GALAXY_5G_ID])

    def test_reference_helpers_do_not_treat_purchase_advice_as_cart_action(self):
        self.assertTrue(_requests_purchase("tôi muốn mua A07 5G"))
        self.assertFalse(_requests_purchase("A07 5G có đáng mua không?"))
        focused = [
            {"id": GALAXY_5G_ID, "name": "Điện thoại Samsung Galaxy A07 5G"},
            {"id": GALAXY_ID, "name": "Điện thoại Samsung Galaxy A07"},
        ]
        self.assertEqual(
            [item["id"] for item in _focused_references("mua a07 5g", focused)],
            [GALAXY_5G_ID],
        )
        unrelated = [
            {"id": PRODUCT_ID, "name": "Điện thoại Motorola G35 5G"},
            {"id": REDMI_ID, "name": "Điện thoại Xiaomi Redmi A7 Pro"},
        ]
        self.assertEqual(
            _focused_references(
                "Galaxy A07 5G và Xiaomi Redmi 15 5G", unrelated
            ),
            [],
        )

    async def test_attribute_followup_inherits_single_active_product(self):
        focused = [
            {"id": BASIC_ID, "name": "Áo Thun Nam Basic Regular"},
            {"id": PRODUCT_ID, "name": "Áo thun nam Dream Team"},
            {"id": GALAXY_ID, "name": "Áo Thun Nam Relax In Tràn Ngựa"},
        ]
        named = state("áo thun nam basic có màu gì")
        named["focused_products"] = focused
        planned_named = await self.agent.plan(named)
        self.assertEqual(planned_named["active_product_id"], BASIC_ID)
        self.assertFalse(planned_named["render_product_cards"])

        followup = state("màu đen bao nhiêu tiền")
        followup["focused_products"] = [{"id": BASIC_ID, "name": "Áo Thun Nam Basic Regular"}]
        followup["active_product_id"] = BASIC_ID
        planned_followup = await self.agent.plan(followup)
        self.assertEqual(planned_followup["plan"]["intent"], "product_detail")
        self.assertEqual(planned_followup["plan"]["product_id"], BASIC_ID)
        self.assertFalse(planned_followup["render_product_cards"])
        self.assertEqual(planned_followup["shopping_phase"], "detailing")

    async def test_variant_choice_survives_until_purchase(self):
        detail = state("màu đen bao nhiêu tiền")
        detail["focused_products"] = [
            {"id": BASIC_ID, "name": "Áo Thun Nam Basic Regular"}
        ]
        detail["active_product_id"] = BASIC_ID
        planned_detail = await self.agent.plan(detail)
        self.assertEqual(planned_detail["selected_options"]["colors"], ["den"])

        purchase = state("tôi muốn mua mẫu này")
        purchase["focused_products"] = detail["focused_products"]
        purchase["active_product_id"] = BASIC_ID
        purchase["selected_options"] = planned_detail["selected_options"]
        planned_purchase = await self.agent.plan(purchase)
        self.assertEqual(planned_purchase["plan"]["intent"], "cart_add")
        self.assertEqual(planned_purchase["plan"]["filters"]["colors"], ["den"])
        self.assertEqual(planned_purchase["shopping_phase"], "selling")

        await self.agent.prepare_cart({**purchase, **planned_purchase})
        self.assertEqual(self.marketplace.product_filters[-1].colors, ["den"])

    async def test_listing_options_clears_previous_variant_selection(self):
        current = state("áo này có màu gì")
        current["focused_products"] = [
            {"id": BASIC_ID, "name": "Áo Thun Nam Basic Regular"}
        ]
        current["active_product_id"] = BASIC_ID
        current["selected_options"] = {"colors": ["den"], "sizes": ["L"]}
        planned = await self.agent.plan(current)
        self.assertEqual(planned["selected_options"]["colors"], [])
        self.assertEqual(planned["selected_options"]["sizes"], ["L"])

    def variant_agent(self):
        marketplace = VariantMarketplace()
        return (
            AgenticShoppingGraph(
                self.settings,
                self.models,
                self.retriever,
                marketplace,
                checkpointer=MemorySaver(),
            ),
            marketplace,
        )

    async def resolve_variant_turn(self, agent, message, selected=None):
        current = state(message)
        current["focused_products"] = [
            {"id": BASIC_ID, "name": "Áo Thun Nam Dream Team"}
        ]
        current["active_product_id"] = BASIC_ID
        current["selected_options"] = selected or {"colors": [], "sizes": []}
        planned = await agent.plan(current)
        detailed = await agent.product_detail({**current, **planned})
        resolved = {**current, **planned, **detailed}
        return planned, resolved, agent._product_attribute_answer(resolved)

    async def test_size_question_wins_over_color_question(self):
        agent, _marketplace = self.variant_agent()
        _planned, resolved, answer = await self.resolve_variant_turn(
            agent, "màu be có size nào"
        )
        self.assertEqual(resolved["selected_options"]["colors"], ["be"])
        self.assertIn("màu Be", answer)
        self.assertIn("M, L, XL, 2XL", answer)
        self.assertNotIn("các màu", answer)

    async def test_unavailable_size_is_answered_without_cart_action(self):
        agent, _marketplace = self.variant_agent()
        planned, _resolved, answer = await self.resolve_variant_turn(
            agent,
            "màu be có size S không",
            {"colors": ["be"], "sizes": []},
        )
        self.assertEqual(planned["plan"]["intent"], "product_detail")
        self.assertIn("không có size S", answer)
        self.assertIn("M, L, XL, 2XL", answer)

    async def test_standalone_size_selects_variant_instead_of_buying(self):
        agent, _marketplace = self.variant_agent()
        planned, _resolved, answer = await self.resolve_variant_turn(
            agent,
            "xl",
            {"colors": ["den"], "sizes": []},
        )
        self.assertEqual(planned["plan"]["intent"], "product_detail")
        self.assertEqual(planned["shopping_phase"], "detailing")
        self.assertIn("size XL", answer)
        self.assertIn("thêm lựa chọn này vào giỏ", answer)

    async def test_measurements_do_not_invent_size_without_chart(self):
        agent, _marketplace = self.variant_agent()
        planned, _resolved, answer = await self.resolve_variant_turn(
            agent, "cao 1m8 nặng 75kg"
        )
        self.assertEqual(planned["plan"]["intent"], "product_detail")
        self.assertIn("chưa có bảng size", answer)
        self.assertIn("không có khoảng số đo đủ rõ", answer)
        self.assertNotIn("tham khảo các size lớn", answer)

    async def test_understand_keeps_original_vietnamese_and_extracts_variant(self):
        current = state("màu be có size nào")
        current["focused_products"] = [
            {"id": BASIC_ID, "name": "Áo Thun Nam Dream Team"}
        ]
        current["active_product_id"] = BASIC_ID
        understood = await self.agent.understand(current)
        payload = understood["understanding"]
        self.assertEqual(self.models.understand_calls[-1], "màu be có size nào")
        self.assertEqual(payload["dialogue_act"], "ask_attribute")
        self.assertEqual(payload["requested_attribute"], "size")
        self.assertEqual(payload["colors"], ["be"])

        planned = await self.agent.plan({**current, **understood})
        self.assertEqual(planned["plan"]["intent"], "product_detail")
        self.assertEqual(planned["plan"]["filters"]["colors"], ["be"])

    async def test_price_superlative_starts_a_new_ranked_search(self):
        current = state("loa mắt nhất")
        current["focused_products"] = [
            {"id": BASIC_ID, "name": "Loa Bluetooth Xiaomi Essential"}
        ]
        current["active_product_id"] = BASIC_ID

        understood = await self.agent.understand(current)
        payload = understood["understanding"]
        self.assertEqual(payload["dialogue_act"], "new_search")
        self.assertFalse(payload["refers_to_active_product"])
        self.assertEqual(payload["sort_by"], "price_desc")
        self.assertEqual(payload["result_limit"], 1)

        planned = await self.agent.plan({**current, **understood})
        self.assertEqual(planned["plan"]["intent"], "product_search")
        self.assertEqual(planned["plan"]["query"], "loa mắt nhất")
        self.assertEqual(planned["plan"]["sort_by"], "price_desc")
        self.assertEqual(planned["plan"]["result_limit"], 1)
        self.assertEqual(planned["plan"]["product_ids"], [])
        self.assertIsNone(planned["active_product_id"])

    async def test_generic_superlative_inherits_only_the_active_product_scope(self):
        current = state("loại mắc nhất mà bạn có là bao nhiêu")
        current["focused_products"] = [
            {"id": BASIC_ID, "name": "Loa Bluetooth Xiaomi Essential"}
        ]
        current["active_product_id"] = BASIC_ID
        understood = await self.agent.understand(current)
        planned = await self.agent.plan({**current, **understood})

        self.assertEqual(planned["plan"]["sort_by"], "price_desc")
        self.assertIn("Loa Bluetooth Xiaomi Essential", planned["plan"]["query"])
        self.assertEqual(planned["plan"]["product_ids"], [])

    async def test_similar_search_inherits_typed_constraints_from_anchor(self):
        current = state("có áo nào tương tự mà rẻ hơn không")
        current["focused_products"] = [
            {"id": BASIC_ID, "name": "MUJI Áo Thun Nam Waffle Cổ Tròn Tay Ngắn"}
        ]
        current["active_product_id"] = BASIC_ID
        current["selected_options"] = {"colors": ["den"], "sizes": ["L"]}

        understood = await self.agent.understand(current)
        resolved = await self.agent.resolve_context({**current, **understood})
        planned = await self.agent.plan({**current, **understood, **resolved})
        filters = planned["plan"]["filters"]

        self.assertEqual(understood["understanding"]["search_mode"], "similar")
        self.assertEqual(planned["plan"]["intent"], "product_search")
        self.assertEqual(planned["plan"]["sort_by"], "relevance")
        self.assertEqual(filters["product_type"], "ao_thun")
        self.assertEqual(filters["audience"], "nam")
        self.assertEqual(filters["colors"], ["den"])
        self.assertEqual(filters["sizes"], ["L"])
        self.assertEqual(filters["max_price"], 588999)
        self.assertEqual(filters["exclude_product_ids"], [BASIC_ID])
        self.assertIn("MUJI Áo Thun Nam", planned["plan"]["query"])
        self.assertLessEqual(len(planned["plan"]["query"]), 1000)

    async def test_similar_context_is_not_specific_to_clothing(self):
        self.retriever.anchor_context = {
            "productId": BASIC_ID,
            "productType": "loa",
            "audience": ["unisex"],
            "minPrice": 450000,
            "maxPrice": 450000,
            "text": "Loa Bluetooth nhỏ gọn chống nước IP66",
        }
        current = state("có loại tương tự nhưng rẻ hơn không")
        current["focused_products"] = [
            {"id": BASIC_ID, "name": "Loa Bluetooth Xiaomi Essential"}
        ]
        current["active_product_id"] = BASIC_ID

        understood = await self.agent.understand(current)
        resolved = await self.agent.resolve_context({**current, **understood})
        planned = await self.agent.plan({**current, **understood, **resolved})
        filters = planned["plan"]["filters"]

        self.assertEqual(filters["product_type"], "loa")
        self.assertEqual(filters["max_price"], 449999)
        self.assertEqual(filters["exclude_product_ids"], [BASIC_ID])
        self.assertIsNone(filters["audience"])

    async def test_similar_search_requires_one_unambiguous_anchor(self):
        current = state("có loại tương tự nhưng rẻ hơn không")
        current["focused_products"] = [
            {"id": BASIC_ID, "name": "Loa Bluetooth Xiaomi Essential"},
            {"id": PRODUCT_ID, "name": "Loa Bluetooth Xiaomi Sound Pocket"},
        ]

        understood = await self.agent.understand(current)
        resolved = await self.agent.resolve_context({**current, **understood})
        planned = await self.agent.plan({**current, **understood, **resolved})

        self.assertEqual(planned["plan"]["intent"], "general")
        self.assertIn("tương tự với mẫu nào", planned["plan"]["clarification"])

    async def test_similar_search_relaxes_only_soft_constraints(self):
        current = state("có mẫu tương tự rẻ hơn không")
        current["plan"] = AgentPlan(
            intent="product_search",
            query="áo thun tương tự",
            filters=SearchFilters(
                product_type="ao_thun",
                audience="nam",
                colors=["den"],
                sizes=["L"],
                max_price=588999,
                exclude_product_ids=[BASIC_ID],
            ),
        ).model_dump()
        current["query"] = "áo thun tương tự"
        current["search_context"] = {
            "mode": "similar",
            "anchor_product_id": BASIC_ID,
            "constraints": [
                {"key": "product_type", "value": "ao_thun", "strength": "hard"},
                {"key": "audience", "value": "nam", "strength": "hard"},
                {"key": "price", "operator": "lt", "value": 588999, "strength": "hard"},
                {"key": "variant.color", "operator": "any", "value": ["den"]},
                {"key": "variant.size", "operator": "any", "value": ["L"]},
            ],
            "exclude_product_ids": [BASIC_ID],
        }

        rewritten = await self.agent.relax_constraints(current)
        filters = rewritten["plan"]["filters"]

        self.assertEqual(filters["product_type"], "ao_thun")
        self.assertEqual(filters["audience"], "nam")
        self.assertEqual(filters["max_price"], 588999)
        self.assertEqual(filters["exclude_product_ids"], [BASIC_ID])
        self.assertEqual(filters["colors"], [])
        self.assertEqual(filters["sizes"], [])
        self.assertEqual(
            set(rewritten["search_context"]["relaxed_keys"]),
            {"variant.color", "variant.size"},
        )
        self.assertTrue(rewritten["warnings"])

    async def test_yes_confirms_only_the_previous_soft_cart_offer(self):
        current = state("có")
        current["history"] = [
            {
                "role": "assistant",
                "content": "Bạn có muốn thêm lựa chọn này vào giỏ không?",
            }
        ]
        current["focused_products"] = [
            {"id": BASIC_ID, "name": "Áo Thun Nam Dream Team"}
        ]
        current["active_product_id"] = BASIC_ID
        current["selected_options"] = {"colors": ["den"], "sizes": ["XL"]}
        understood = await self.agent.understand(current)
        self.assertEqual(understood["understanding"]["confirmation"], "yes")
        planned = await self.agent.plan({**current, **understood})
        self.assertEqual(planned["plan"]["intent"], "cart_add")

        unrelated = state("có")
        unrelated["focused_products"] = current["focused_products"]
        unrelated["active_product_id"] = BASIC_ID
        not_confirmed = await self.agent.understand(unrelated)
        self.assertIsNone(not_confirmed["understanding"]["confirmation"])

    def test_context_followup_detection_does_not_capture_new_search(self):
        self.assertTrue(_continues_active_product("màu đen bao nhiêu tiền"))
        self.assertTrue(_continues_active_product("còn hàng size XL không"))
        self.assertFalse(_continues_active_product("tìm mẫu áo khác màu đen"))

    def test_product_attribute_answers_are_grounded_in_variants(self):
        product = {
            "id": BASIC_ID,
            "name": "Áo Thun Nam Basic Regular",
            "price": 299000,
            "variants": [
                {"name": "Màu nâu 002 / M", "price": 299000, "availableStock": 5},
                {"name": "Trắng 001 / XL", "price": 299000, "availableStock": 4},
                {"name": "Đen 002 / L", "price": 299000, "availableStock": 3},
            ],
        }
        color_state = state("áo này có màu gì")
        color_state["products"] = [product]
        colors = self.agent._product_attribute_answer(color_state)
        self.assertIn("nâu", colors)
        self.assertIn("Trắng", colors)
        self.assertIn("Đen", colors)

        price_state = state("màu đen bao nhiêu tiền")
        price_state["products"] = [product]
        price_state["plan"] = {"filters": {"colors": ["den"], "sizes": []}}
        price = self.agent._product_attribute_answer(price_state)
        self.assertIn("Đen", price)
        self.assertIn("299.000đ", price)

    def test_product_name_is_not_reported_as_a_color(self):
        product = {
            "id": BASIC_ID,
            "name": "Loa Bluetooth Xiaomi Essential",
            "price": 450000,
            "variants": [
                {
                    "name": "Loa Bluetooth Xiaomi Essential",
                    "price": 450000,
                    "availableStock": 5,
                }
            ],
        }
        color_state = state("có mấy màu")
        color_state["products"] = [product]
        answer = self.agent._product_attribute_answer(color_state)

        self.assertIn("chưa có thông tin màu", answer)
        self.assertNotIn("các màu: Loa Bluetooth Xiaomi Essential", answer)

    async def test_cart_write_requires_explicit_action_id(self):
        self.models.next_plan = AgentPlan(
            intent="cart_add",
            query="",
            product_id=PRODUCT_ID,
            variant_id=VARIANT_ID,
            quantity=2,
        )
        config = {"configurable": {"thread_id": "cart"}}
        prepared = await self.agent.graph.ainvoke(state("thêm 2 vào giỏ"), config=config)
        self.assertEqual(self.marketplace.cart_writes, [])
        pending = prepared["pending_action"]
        self.assertTrue(pending["id"].startswith("act_"))

        confirmed = await self.agent.graph.ainvoke(
            state("", {"confirmActionId": pending["id"]}, pending), config=config
        )
        self.assertEqual(len(self.marketplace.cart_writes), 1)
        self.assertIsNone(confirmed["pending_action"])
        self.assertTrue(confirmed["tool_result"]["success"])

    async def test_checkout_token_never_enters_public_tool_result(self):
        self.models.next_plan = AgentPlan(intent="checkout", query="")
        config = {"configurable": {"thread_id": "checkout"}}
        prepared = await self.agent.graph.ainvoke(
            state(
                "thanh toán",
                {
                    "addressId": ADDRESS_ID,
                    "paymentMethod": "cod",
                    "voucherCode": None,
                },
            ),
            config=config,
        )
        pending = prepared["pending_action"]
        self.assertEqual(pending["secret"], "server-secret")
        self.assertNotIn("confirmationToken", str(prepared["tool_result"]))
        self.assertNotIn("server-secret", str(prepared["tool_result"]))
        public = PendingAction.model_validate(pending).public()
        self.assertNotIn("secret", public)
        self.assertNotIn("payload", public)

        confirmed = await self.agent.graph.ainvoke(
            state("", {"confirmActionId": pending["id"]}, pending), config=config
        )
        self.assertEqual(
            self.marketplace.confirmed_quotes[0],
            ("buyer-1", "session-test", "quote-1", "server-secret"),
        )
        self.assertTrue(confirmed["tool_result"]["success"])


if __name__ == "__main__":
    unittest.main()

