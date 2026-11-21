"""Behaviours a free-form demo leans on: typed confirmations, kept context,
wishes that rank instead of filter, budgets as people say them, and a slow
plan model that never drops the turn."""

import asyncio
import time
import unittest

from app.graph import (
    AgenticShoppingGraph,
    _drop_unbacked_action_claims,
    _spec_comparison,
    _explicit_pending_answer,
    _pending_reply,
    _soften,
)
from app.models import GeminiGateway
from app.schemas import SearchFilters, SemanticConstraint, SemanticReference, SemanticTask, SemanticTurn
from app.search_parser import _normalize_message, _price
from test_graph import PRODUCT_ID, VARIANT_ID, FakeMarketplace, state
from test_production import SemanticModels, build


def pending_cart_add():
    return {
        "id": "act_demo",
        "kind": "cart_add",
        "summary": "Thêm Áo thun — số lượng 1",
        "payload": {"productId": PRODUCT_ID, "variantId": VARIANT_ID, "quantity": 1},
        "secret": "",
        "expires_at": time.time() + 600,
    }


class TypedConfirmationTests(unittest.IsolatedAsyncioTestCase):
    def test_short_replies_answer_the_waiting_action(self):
        for message in ("Xác nhận", "ok", "có nhé", "đồng ý", "Chốt đơn!"):
            self.assertEqual(_pending_reply(message), "confirm", message)
        for message in ("thôi", "hủy đi", "không"):
            self.assertEqual(_pending_reply(message), "cancel", message)
        for message in ("có màu xanh không", "ok nhưng cho mình xem mẫu khác trước đã"):
            self.assertIsNone(_pending_reply(message), message)

    def test_a_hedged_yes_is_not_a_confirmation(self):
        self.assertFalse(_explicit_pending_answer("Có thể, nhưng phải có bảo hành chính hãng", "confirm"))
        self.assertTrue(_explicit_pending_answer("Xác nhận. Mà có được đổi trả không?", "confirm"))

    async def test_typed_confirmation_writes_the_cart_without_a_model_call(self):
        models = SemanticModels(SemanticTurn(tasks=[SemanticTask(intent="general")], confidence=0.9))
        marketplace = FakeMarketplace()
        agent = build(models, marketplace=marketplace)
        result = await agent.graph.ainvoke(
            state("Xác nhận", pending=pending_cart_add()), config={"configurable": {"thread_id": "typed"}}
        )
        self.assertEqual(len(marketplace.cart_writes), 1)
        self.assertEqual(models.decide_calls, 0)
        self.assertIsNone(result["pending_action"])
        self.assertTrue(result["tool_result"]["success"])
        # The widget's "Thanh toán" button opens checkout for the added line.
        self.assertTrue(result["tool_result"]["result"]["cartChanged"])
        self.assertEqual(result["tool_result"]["result"]["addedLines"], [f"{PRODUCT_ID}::{VARIANT_ID}"])

    async def test_model_yes_inside_a_longer_message_needs_explicit_words(self):
        models = SemanticModels(
            SemanticTurn(
                tasks=[SemanticTask(intent="product_search", query="laptop")],
                confidence=0.9,
                pending_decision="confirm",
            )
        )
        marketplace = FakeMarketplace()
        agent = build(models, marketplace=marketplace)
        await agent.graph.ainvoke(
            state("Có thể, nhưng phải có bảo hành chính hãng. Cho mình 2 mẫu để so sánh.", pending=pending_cart_add()),
            config={"configurable": {"thread_id": "hedged"}},
        )
        self.assertEqual(marketplace.cart_writes, [])


class ContextAndFilterTests(unittest.TestCase):
    def test_follow_up_for_the_same_product_keeps_budget_and_kind(self):
        last = {"product_type": "điện thoại", "category_path": "Điện tử › Điện thoại", "max_price": 15e6}
        follow = SearchFilters(spec_constraints=[SemanticConstraint(key="storage", value="256GB")])
        merged = AgenticShoppingGraph._carry_over(follow, last)
        self.assertEqual(merged.max_price, 15e6)
        self.assertEqual(merged.product_type, "điện thoại")
        # A different product starts fresh.
        other = AgenticShoppingGraph._carry_over(SearchFilters(product_type="tai nghe"), last)
        self.assertIsNone(other.max_price)

    def test_wishes_rank_instead_of_filtering(self):
        self.assertEqual(_soften(SemanticConstraint(key="weight", value="không quá nặng")).strength, "soft")
        self.assertEqual(_soften(SemanticConstraint(key="water_resistant", value="chống nước")).strength, "soft")
        self.assertEqual(_soften(SemanticConstraint(key="storage", value="256GB")).strength, "hard")
        self.assertEqual(_soften(SemanticConstraint(key="capacity", value=5, unit="lít")).strength, "hard")

    def test_semantic_filters_read_colours_brands_and_sizes_sensibly(self):
        task = SemanticTask(intent="product_search", constraints=[
            SemanticConstraint(key="color", value=["be", "đen"]),
            SemanticConstraint(key="color", value="xanh navy"),
            SemanticConstraint(key="brand", value="cùng hãng"),
            SemanticConstraint(key="size", value="480"),
            SemanticConstraint(key="delivery_time", value="6 ngày"),
            SemanticConstraint(key="gift_wrapping", value="có"),
        ])
        filters = AgenticShoppingGraph._semantic_filters(task)
        self.assertEqual(filters.colors, ["be", "đen", "xanh navy"])
        self.assertIsNone(filters.brand)
        self.assertEqual(filters.sizes, [])
        self.assertEqual([item.key for item in filters.spec_constraints], ["size"])
        neutral = AgenticShoppingGraph._semantic_filters(SemanticTask(
            intent="product_search", constraints=[SemanticConstraint(key="color", value="màu trung tính")]
        ))
        self.assertIn("be", neutral.colors)

    def test_budgets_as_customers_say_them(self):
        def price(text):
            return _price(_normalize_message(text)[1])[:2]

        self.assertEqual(price("điện thoại tầm 15 triệu đổ lại"), (None, 15_000_000))
        self.assertEqual(price("tầm 2tr trở xuống"), (None, 2_000_000))
        self.assertEqual(price("dưới 700 nghìn"), (None, 700_000))
        low, high = price("laptop tầm 20 triệu")
        self.assertLess(low, 20_000_000)
        self.assertLessEqual(high, 22_000_000)
        low, high = price("tai nghe 1tr5")
        self.assertTrue(low < 1_500_000 < high)


class SlowPlanModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_model_answers_when_the_decide_model_is_slow(self):
        gateway = object.__new__(GeminiGateway)
        fast_turn = SemanticTurn(tasks=[SemanticTask(intent="general")], confidence=0.9)
        gateway.settings = type("S", (), {"decide_timeout": 5, "decide_fallback_after": 0.05})()
        gateway.llm, gateway.decide_llm = object(), object()

        async def structured(kind, _timeout, _messages, _schema, llm=None):
            if llm is gateway.decide_llm:
                await asyncio.sleep(2)
                raise AssertionError("the slow model should have been cancelled")
            return fast_turn

        gateway._structured = structured
        started = time.monotonic()
        result = await gateway._hedged_decide([])
        self.assertIs(result, fast_turn)
        self.assertLess(time.monotonic() - started, 1)



class HonestActionTests(unittest.TestCase):
    def test_claimed_cart_change_without_a_tool_is_removed(self):
        answer = "Mình đã thêm Điện thoại Nothing Phone (4a) Pro, bản 256GB, màu xanh vào giỏ hàng. Máy có camera 50MP."
        cleaned = _drop_unbacked_action_claims(answer, {"found": True})
        self.assertNotIn("đã thêm", cleaned)
        self.assertIn("camera 50MP", cleaned)
        self.assertIn("xác nhận", cleaned)

    def test_real_success_and_customer_sentences_are_kept(self):
        done = "Mình đã thêm áo vào giỏ hàng."
        self.assertEqual(_drop_unbacked_action_claims(done, {"success": True}), done)
        policy = "Nếu bạn đã đặt đơn và muốn hủy, hãy vào mục Đơn hàng."
        self.assertEqual(_drop_unbacked_action_claims(policy, {}), policy)


class FollowUpAfterListTests(unittest.IsolatedAsyncioTestCase):
    async def test_detail_question_after_a_list_answers_for_the_first_result(self):
        turn = SemanticTurn(
            tasks=[SemanticTask(intent="product_detail", requested_attributes=["color"])],
            conversation_action="continue", confidence=0.9,
        )
        agent = build(SemanticModels(turn))
        current = {**state("có màu đen không"), "semantic_turn": turn.model_dump()}
        current["focused_products"] = [{"id": PRODUCT_ID, "name": "Samsung Galaxy A26"}, {"id": "9" * 24, "name": "A17"}]
        planned = await agent.plan(current)
        self.assertEqual(planned["plan"]["intent"], "product_detail")
        self.assertEqual(planned["plan"]["product_id"], PRODUCT_ID)
        self.assertIn("ASSUMED_FIRST_PRODUCT", planned["warnings"])


class ManyItemsAndComparisonTests(unittest.IsolatedAsyncioTestCase):
    async def test_several_products_are_added_with_one_confirmation(self):
        other = "8" * 24
        turn = SemanticTurn(
            tasks=[SemanticTask(intent="cart_add", references=[
                SemanticReference(kind="focused_index", index=1),
                SemanticReference(kind="focused_index", index=2),
            ])],
            conversation_action="continue", confidence=0.95,
        )
        marketplace = FakeMarketplace()
        agent = build(SemanticModels(turn), marketplace=marketplace)
        config = {"configurable": {"thread_id": "many"}}
        current = state("thêm vào giỏ mỗi loại một chai")
        current["focused_products"] = [{"id": PRODUCT_ID, "name": "Dầu gội"}, {"id": other, "name": "Dầu xả"}]
        prepared = await agent.graph.ainvoke(current, config=config)
        pending = prepared["pending_action"]
        self.assertEqual([item["productId"] for item in pending["payload"]["items"]], [PRODUCT_ID, other])
        self.assertEqual(marketplace.cart_writes, [])
        confirmed = await agent.graph.ainvoke(state("xác nhận", pending=pending), config=config)
        self.assertEqual([write[1] for write in marketplace.cart_writes], [PRODUCT_ID, other])
        self.assertTrue(confirmed["tool_result"]["success"])

    def test_comparison_facts_name_the_lighter_product(self):
        products = [
            {"name": "Laptop A", "specifications": [{"name": "Khối lượng", "value": "1.39 kg"}]},
            {"name": "Laptop B", "specifications": [{"name": "Trọng lượng", "value": "1100 g"}]},
        ]
        facts = _spec_comparison({"message": "cái nào nhẹ hơn", "products": products, "semantic_turn": {}})
        self.assertEqual(facts["computed"]["weight"], "nhẹ nhất: Laptop B")
        self.assertEqual(facts["rows"][0]["values"]["weight"], "Khối lượng: 1.39 kg")
        self.assertIsNone(_spec_comparison({"message": "cái nào đẹp hơn", "products": products}))


class KnowledgeResearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_knowledge_answer_is_kept_without_sources(self):
        from types import SimpleNamespace

        gateway = object.__new__(GeminiGateway)
        gateway.settings = SimpleNamespace(web_search_provider="gateway", web_search_timeout=5)
        gateway._web_cache = {}
        from collections import OrderedDict
        gateway._web_cache = OrderedDict()

        class Model:
            async def ainvoke(self, _messages):
                return SimpleNamespace(text="Woburn III có màu Đen, Kem và Nâu.\nTU_KHOA: loa marshall", response_metadata={})

        gateway.web_llm = Model()
        research = await gateway.web_research("Woburn III có mấy màu")
        self.assertIn("Đen", research.summary)
        self.assertEqual(research.sources, [])
        self.assertEqual(research.catalog_queries, ["loa marshall"])


class ListQuestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_which_one_question_is_answered_from_the_list(self):
        turn = SemanticTurn(
            tasks=[SemanticTask(intent="compare_products", requested_attributes=["display"])],
            confidence=0.6, needs_clarification=True, clarification_question="Bạn muốn hỏi sản phẩm nào?",
        )
        agent = build(SemanticModels(turn))
        current = {**state("mẫu nào có màn OLED"), "semantic_turn": turn.model_dump()}
        current["focused_products"] = [{"id": PRODUCT_ID, "name": "A"}, {"id": "9" * 24, "name": "B"}]
        planned = await agent.plan(current)
        self.assertEqual(planned["plan"]["intent"], "product_search")
        self.assertEqual(planned["plan"]["product_ids"], [PRODUCT_ID, "9" * 24])

    async def test_missing_colour_is_named_instead_of_out_of_stock(self):
        from app.agents import OrderAgent
        from app.schemas import AgentPlan

        class Picky(FakeMarketplace):
            async def product_card(self, product_id, filters=None):
                if filters is not None and filters.colors:
                    return None
                return await super().product_card(product_id, filters)

        agent = OrderAgent(type("S", (), {"action_ttl": 600})(), SemanticModels(), Picky())
        plan = AgentPlan(intent="cart_add", query="", product_id=PRODUCT_ID, filters=SearchFilters(colors=["xanh"]))
        result = await agent._prepare_add_one(state("thêm màu xanh"), plan)
        self.assertIn("không có phiên bản xanh", result["tool_result"]["clarification"])
        self.assertIn("Trắng / M", result["tool_result"]["clarification"])


class ConversationMemoryTests(unittest.TestCase):
    def test_generic_question_targets_the_product_just_recommended(self):
        focused = [{"id": "1" * 24, "name": "Điện thoại Samsung Galaxy A26 5G"}, {"id": "2" * 24, "name": "Điện thoại Samsung Galaxy A07 5G"}]
        current = {"history": [{"role": "assistant", "content": "Điện thoại Samsung Galaxy A07 5G có pin trâu nhất 6000 mAh."}]}
        self.assertEqual(AgenticShoppingGraph._last_recommended(current, focused), "2" * 24)
        self.assertEqual(AgenticShoppingGraph._last_recommended({"history": []}, focused), "1" * 24)

    def test_naming_a_brand_for_the_first_time_keeps_the_budget(self):
        last = {"product_type": "loa bluetooth", "max_price": 2e6}
        merged = AgenticShoppingGraph._carry_over(SearchFilters(brand="Sony"), last)
        self.assertEqual(merged.max_price, 2e6)

    def test_earlier_wishes_carry_over_as_soft_and_restated_ones_win(self):
        water = SemanticConstraint(key="water_resistant", value="chống nước")
        battery = SemanticConstraint(key="battery_life", value="8 giờ", strength="soft")
        last = {
            "product_type": "loa bluetooth",
            "spec_constraints": [water.model_dump(), battery.model_dump()],
        }
        follow = SearchFilters(spec_constraints=[SemanticConstraint(key="battery_life", value="12 giờ")])
        merged = AgenticShoppingGraph._carry_over(follow, last)
        by_key = {item.key: item for item in merged.spec_constraints}
        self.assertEqual(by_key["battery_life"].value, "12 giờ")
        self.assertEqual((by_key["water_resistant"].strength, by_key["water_resistant"].source), ("soft", "conversation"))
        # Another kind of product does not inherit the wishes.
        other = AgenticShoppingGraph._carry_over(SearchFilters(product_type="nồi cơm điện"), last)
        self.assertEqual(other.spec_constraints, [])

    def test_the_named_kind_is_loosened_last_a_mismatched_branch_first(self):
        from app.conversation import _next_relaxation

        named = SearchFilters(category_ids=["a" * 24], category_path="Điện tử › Laptop",
                              product_type="laptop", max_price=16e6, brand="Dell")
        self.assertEqual(_next_relaxation(named, []), "price")
        self.assertEqual(_next_relaxation(named, ["price", "brand"]), "category")
        wrong = SearchFilters(category_ids=["a" * 24], category_path="Điện tử › Laptop",
                              product_type="balo laptop", max_price=1e6)
        self.assertEqual(_next_relaxation(wrong, []), "category")

    def test_another_brand_does_not_inherit_the_old_budget(self):
        last = {"product_type": "điện thoại", "brand": "Samsung", "min_price": 4e6, "max_price": 8.8e6}
        merged = AgenticShoppingGraph._carry_over(SearchFilters(brand="Apple"), last)
        self.assertIsNone(merged.max_price)
        self.assertEqual(merged.product_type, "điện thoại")


class RankingSchemaTests(unittest.TestCase):
    def test_an_overlong_judgement_is_trimmed_not_rejected(self):
        from app.schemas import CandidateRanking

        ranking = CandidateRanking.model_validate({"results": [
            {"index": 1, "relevance": 3, "evidence": [f"e{i}" for i in range(7)], "reason": "x" * 400}
        ]})
        self.assertEqual(len(ranking.results[0].evidence), 6)
        self.assertEqual(len(ranking.results[0].reason), 300)

if __name__ == "__main__":
    unittest.main()
