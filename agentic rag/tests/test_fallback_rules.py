"""The rule fallbacks that run when the semantic model is unavailable."""

import asyncio
import unittest

from app.graph import _pending_reply
from app.models import GeminiGateway
from app.schemas import SemanticTurn
from app.search_parser import parse_followup_turn, parse_search_turn, parse_smalltalk_turn
from test_graph import state
from test_production import SemanticModels, build

PID = "a" * 24
PENDING = {"id": "x" * 10, "kind": "cart_add", "summary": "Thêm áo", "payload": {}, "expires_at": 9e12}


class Down(SemanticModels):
    async def decide(self, *_args, **_kwargs):
        self.decide_calls += 1
        raise RuntimeError("503 UNAVAILABLE")


async def understand(message, **context):
    agent = build(Down())
    current = state(message, pending=context.pop("pending_action", None))
    current.update(context)
    current.setdefault("last_search", {})
    out = await agent.understand(current)
    return SemanticTurn.model_validate(out["semantic_turn"]), out


def constraint(turn, key):
    return {(c.key, c.operator): c.value for c in turn.tasks[0].constraints}.get(key)


class SortParseTests(unittest.TestCase):
    def test_price_extremes_become_a_sort_order(self):
        cheapest = parse_search_turn("điện thoại rẻ nhất")
        self.assertEqual(cheapest.tasks[0].sort_by, "price_asc")
        self.assertEqual(constraint(cheapest, ("product_type", "eq")), "điện thoại")
        priciest = parse_search_turn("laptop đắt nhất")
        self.assertEqual(priciest.tasks[0].sort_by, "price_desc")
        self.assertEqual(constraint(priciest, ("product_type", "eq")), "laptop")

    def test_plain_search_keeps_relevance(self):
        self.assertEqual(parse_search_turn("tai nghe bluetooth").tasks[0].sort_by, "relevance")


class FollowUpParseTests(unittest.TestCase):
    LAST = {"query": "laptop lập trình", "product_type": "laptop", "max_price": 20_000_000}

    def test_budget_only_keeps_the_product_kind(self):
        turn = parse_followup_turn("dưới 15 triệu thôi", self.LAST)
        self.assertEqual(constraint(turn, ("product_type", "eq")), "laptop")
        self.assertEqual(constraint(turn, ("price", "lte")), 15_000_000)

    def test_cheaper_sorts_within_the_old_budget(self):
        turn = parse_followup_turn("rẻ hơn chút được không", self.LAST)
        self.assertEqual(turn.tasks[0].sort_by, "price_asc")
        self.assertEqual(constraint(turn, ("price", "lte")), 20_000_000)

    def test_pricier_raises_the_floor(self):
        turn = parse_followup_turn("đắt hơn chút", self.LAST)
        self.assertEqual(turn.tasks[0].sort_by, "price_desc")
        self.assertEqual(constraint(turn, ("price", "gte")), 16_000_000)

    def test_spec_words_join_the_query_as_a_soft_wish(self):
        turn = parse_followup_turn("loại 16GB RAM", self.LAST)
        self.assertEqual(turn.tasks[0].query, "laptop lập trình 16gb ram")
        soft = [c for c in turn.tasks[0].constraints if c.key == "feature"]
        self.assertEqual([c.strength for c in soft], ["soft"])

    def test_cheapest_of_the_last_search(self):
        self.assertEqual(parse_followup_turn("cái nào rẻ nhất", self.LAST).tasks[0].sort_by, "price_asc")

    def test_not_a_follow_up(self):
        for message in ("tai nghe dưới 500k", "chính sách đổi trả", "cái thứ 2 bao nhiêu", "ok", "chào shop"):
            self.assertIsNone(parse_followup_turn(message, self.LAST), message)
        self.assertIsNone(parse_followup_turn("dưới 15 triệu", {}))


class SmalltalkParseTests(unittest.TestCase):
    def test_greetings_thanks_and_catalog_questions(self):
        for message in ("chào shop", "xin chào", "hello ad", "cảm ơn nhé", "thanks shop"):
            self.assertEqual(parse_smalltalk_turn(message).tasks[0].intent, "general", message)
        for message in ("shop bán những gì", "shop có những sản phẩm gì", "xem danh mục"):
            self.assertEqual(parse_smalltalk_turn(message).tasks[0].intent, "browse_categories", message)

    def test_requests_are_not_smalltalk(self):
        for message in ("chào shop, tìm tai nghe", "shop có tai nghe gì", "cảm ơn, thêm vào giỏ"):
            self.assertIsNone(parse_smalltalk_turn(message), message)


class PendingReplyTests(unittest.TestCase):
    def test_cancel_phrasings(self):
        for message in ("thôi không", "không bạn ơi", "không cần", "chưa cần đâu", "hủy đi", "thôi bỏ"):
            self.assertEqual(_pending_reply(message), "cancel", message)

    def test_confirm_phrasings_unchanged(self):
        for message in ("ok", "ok bạn", "có nhé", "xác nhận"):
            self.assertEqual(_pending_reply(message), "confirm", message)
        self.assertIsNone(_pending_reply("có đâu"))


class OutageChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_named_kind_is_searched_while_a_product_is_in_focus(self):
        turn, out = await understand("tai nghe bluetooth dưới 500k", active_product_id=PID)
        self.assertIn("MODEL_UNAVAILABLE", out["warnings"])
        self.assertEqual(turn.tasks[0].intent, "product_search")
        # A bare variant pick on the focused product is still a variant pick.
        turn, _ = await understand("màu đen size L", active_product_id=PID)
        self.assertEqual(turn.tasks[0].intent, "product_detail")

    async def test_follow_up_uses_the_last_search(self):
        turn, _ = await understand("dưới 15 triệu thôi", last_search={"product_type": "điện thoại"})
        self.assertEqual(turn.tasks[0].intent, "product_search")
        self.assertEqual(constraint(turn, ("price", "lte")), 15_000_000)
        turn, _ = await understand("cái nào rẻ nhất")
        self.assertTrue(turn.needs_clarification)

    async def test_smalltalk_and_cancel_are_answered(self):
        turn, _ = await understand("chào shop")
        self.assertEqual(turn.tasks[0].intent, "general")
        turn, out = await understand("thôi không", pending_action=dict(PENDING))
        self.assertEqual(turn.pending_decision, "cancel")
        self.assertIn("TEXT_CONFIRMATION", out["warnings"])

    async def test_follow_up_search_runs_end_to_end(self):
        agent = build(Down())
        current = state("rẻ hơn chút được không")
        current["last_search"] = {"query": "áo sơ mi", "product_type": "áo sơ mi", "max_price": 500_000}
        result = await agent.graph.ainvoke(current, config={"configurable": {"thread_id": "follow"}})
        self.assertEqual(result["route"], "product_search")
        filters = (result.get("tool_result") or {}).get("filters") or result["plan"]["filters"]
        self.assertEqual(filters.get("max_price"), 500_000)
        self.assertEqual(result["plan"]["sort_by"], "price_asc")


class OutageClarifyKeyTests(unittest.IsolatedAsyncioTestCase):
    async def test_resending_after_an_outage_is_not_a_repeat(self):
        agent = build(Down())
        current = state("abc xyz")
        current["last_clarify_key"] = "cau truoc"
        current["clarify_count"] = 1
        result = await agent.graph.ainvoke(current, config={"configurable": {"thread_id": "outage"}})
        self.assertEqual(result["route"], "clarify")
        self.assertEqual(result["last_clarify_key"], "cau truoc")
        self.assertEqual(result["clarify_count"], 1)


class HedgeTimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_starts_before_the_primary_times_out(self):
        gateway = GeminiGateway.__new__(GeminiGateway)
        gateway.settings = type("S", (), {"decide_timeout": 1.0, "decide_fallback_after": 6})()
        started: dict[str, float] = {}
        loop = asyncio.get_running_loop()
        begin = loop.time()

        async def structured(kind, *_args, **_kwargs):
            started[kind] = loop.time() - begin
            if kind == "decide":
                await asyncio.sleep(1.0)
                raise asyncio.TimeoutError
            return SemanticTurn(tasks=[{"intent": "general"}], confidence=0.9)

        gateway._structured = structured
        gateway.decide_llm = object()
        turn = await gateway._hedged_decide([])
        self.assertEqual(turn.tasks[0].intent, "general")
        self.assertLess(started["decide_fallback"], 0.9)


if __name__ == "__main__":
    unittest.main()
