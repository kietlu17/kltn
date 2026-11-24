"""Hybrid mode: the tool-calling advisor and its fallback to the graph."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from app.mentions import named_products  # noqa: E402
from app.config import AgenticSettings  # noqa: E402
from app.graph import AgenticShoppingGraph  # noqa: E402
from app.schemas import SemanticConstraint, SemanticReference, SemanticTask, SemanticTurn  # noqa: E402
from test_graph import state as base_state  # noqa: E402
from test_invariants import BY_ID, CatalogMarketplace, CatalogRetriever, ScriptedModels  # noqa: E402


class ScriptedLLM:
    """Returns the scripted replies in order; records what it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def bind_tools(self, _tools, **_kwargs):
        return self

    async def ainvoke(self, messages):
        self.sent.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def call(name, args, call_id):
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def build(llm, cart_ids=None):
    models = ScriptedModels()
    models.advisor_llm = llm
    agent = AgenticShoppingGraph(
        AgenticSettings(gemini_api_key="test", web_search_enabled=False, rerank_mode="none", agentic_mode="hybrid"),
        models,
        CatalogRetriever(),
        CatalogMarketplace(cart_ids),
        checkpointer=MemorySaver(),
    )
    return agent, models


def search_turn(query, *constraints):
    return SemanticTurn(
        tasks=[SemanticTask(intent="product_search", query=query, constraints=list(constraints))],
        confidence=0.9,
    )


def product_id(name):
    return next(key for key, item in BY_ID.items() if item["name"] == name)


class MentionTests(unittest.TestCase):
    # Names as they are in the catalog.
    ACER = {"id": "acer", "name": "Laptop Acer Aspire Lite 14 AL14 71P 55P9 - NX.D7USV.001 "
                                  "(i5 13500H, 16GB, 512GB, Full HD+, Win11)"}
    NEO = {"id": "neo", "name": "MacBook Neo 13 inch A18 Pro"}
    DELL_I3 = {"id": "i3", "name": "Laptop Dell 15 DC15250 - 71100520 (Core 3 100U, 8GB, 512GB, Win11)"}
    DELL_I7 = {"id": "i7", "name": "Laptop Dell 15 DC15250 - DC15250-i7U161W11SLU (i7 1355U, 16GB, 1TB, Win11)"}

    def test_configuration_and_sku_may_be_left_out(self):
        for text in (
            "Laptop Acer Aspire Lite 14 AL14 71P 55P9 - NX.D7USV.001: 18.990.000đ",
            "Laptop Acer Aspire Lite 14 AL14-71P-55P9, chip i5",
            "chiếc Acer Aspire Lite 14 AL14 71P 55P9.",
        ):
            self.assertEqual(named_products(text, [self.ACER]), ["acer"], text)

    def test_order_follows_the_reply(self):
        text = "1. MacBook Neo 13 inch A18 Pro 2. Laptop Acer Aspire Lite 14 AL14 71P 55P9 - NX.D7USV.001"
        self.assertEqual(named_products(text, [self.ACER, self.NEO]), ["neo", "acer"])

    def test_a_sku_names_one_configuration_and_the_model_names_both(self):
        dells = [self.DELL_I3, self.DELL_I7]
        self.assertEqual(named_products("Laptop Dell 15 DC15250 - 71100520 rẻ hơn", dells), ["i3"])
        self.assertEqual(named_products("Laptop Dell 15 DC15250 có 2 bản", dells), ["i3", "i7"])

    def test_no_accidental_mentions(self):
        self.assertEqual(named_products("JBL Clip 50", [{"id": "c", "name": "Loa Bluetooth JBL Clip 5"}]), [])
        self.assertEqual(named_products("áo thun nam dễ phối", [{"id": "a", "name": "Áo thun nam (form rộng)"}]), [])


class AdvisorTests(unittest.IsolatedAsyncioTestCase):
    async def run_turn(self, agent, models, message, turn, **extra):
        models.turn = turn
        current = {**base_state(message), **extra}
        return await agent.graph.ainvoke(current, config={"configurable": {"thread_id": message}})

    async def test_brands_are_searched_one_by_one_and_cards_follow_the_reply(self):
        llm = ScriptedLLM([
            AIMessage(content="", tool_calls=[
                call("search_products", {"query": "loa", "product_type": "loa bluetooth", "brand": "JBL",
                                         "max_price": 2_000_000}, "c1"),
                call("search_products", {"query": "loa", "product_type": "loa bluetooth", "brand": "Sony",
                                         "max_price": 2_000_000}, "c2"),
            ]),
            AIMessage(content="Trong tầm 2 triệu bạn nên lấy Loa Bluetooth JBL Clip 5 (1.790.000đ)."),
        ])
        agent, models = build(llm)
        result = await self.run_turn(agent, models, "JBL với Sony mẫu nào đáng mua?", search_turn("loa jbl sony"))

        self.assertIn("JBL Clip 5", result["answer"])
        self.assertEqual([item["name"] for item in result["products"]], ["Loa Bluetooth JBL Clip 5"])
        self.assertIn("ADVISOR", result["warnings"])
        self.assertEqual(models.answer_calls, 0)
        tool_results = [item for item in llm.sent[1] if isinstance(item, ToolMessage)]
        self.assertEqual(len(tool_results), 2)
        # Sony is only a soundbar in this catalog: never offered as a speaker.
        self.assertIn('"found": 0', tool_results[1].content)
        self.assertNotIn("loa thanh", tool_results[1].content.casefold())

    async def test_budget_bends_15_percent_and_says_so(self):
        llm = ScriptedLLM([
            AIMessage(content="", tool_calls=[call("search_products", {
                "query": "laptop dell", "product_type": "laptop", "brand": "Dell", "max_price": 16_000_000}, "c1")]),
            AIMessage(content="Laptop Dell Inspiron 15 hơi vượt ngân sách một chút."),
        ])
        agent, models = build(llm)
        result = await self.run_turn(agent, models, "laptop dell dưới 16 triệu", search_turn("laptop dell"))
        tool_result = next(item for item in llm.sent[1] if isinstance(item, ToolMessage)).content
        self.assertIn("ngân sách nới lên", tool_result)
        self.assertNotIn("Balo", tool_result)
        self.assertEqual([item["name"] for item in result["products"]], ["Laptop Dell Inspiron 15"])

    async def test_brand_outside_budget_is_reported_not_denied(self):
        llm = ScriptedLLM([
            AIMessage(content="", tool_calls=[call("search_products", {
                "query": "giày nike", "product_type": "giày thể thao", "brand": "Nike", "max_price": 2_000_000}, "c1")]),
            AIMessage(content="Giày Nike Air Zoom Pegasus giá 3.290.000đ, vượt ngân sách của bạn."),
        ])
        agent, models = build(llm)
        await self.run_turn(agent, models, "giày nike dưới 2 triệu", search_turn("giày nike"))
        tool_result = next(item for item in llm.sent[1] if isinstance(item, ToolMessage)).content
        self.assertIn("brand_outside_budget", tool_result)
        self.assertIn("Pegasus", tool_result)

    async def test_a_failed_advisor_turn_is_answered_by_the_graph(self):
        llm = ScriptedLLM([TimeoutError()])
        agent, models = build(llm)
        result = await self.run_turn(
            agent, models, "loa bluetooth dưới 2 triệu",
            search_turn("loa bluetooth", SemanticConstraint(key="product_type", value="loa bluetooth"),
                        SemanticConstraint(key="max_price", operator="lte", value=2_000_000)),
        )
        self.assertIn("ADVISOR_FALLBACK", result["warnings"])
        self.assertTrue(result["products"])
        self.assertEqual(models.answer_calls, 1)

    async def test_cart_and_checkout_stay_on_the_graph(self):
        llm = ScriptedLLM([])
        agent, models = build(llm, cart_ids=[product_id("Loa Bluetooth JBL Clip 5")])
        result = await self.run_turn(
            agent, models, "thanh toán",
            SemanticTurn(tasks=[SemanticTask(intent="checkout", query="thanh toán")], confidence=0.9),
        )
        self.assertEqual(llm.sent, [])
        self.assertEqual(result["route"], "checkout")

    async def test_a_reply_about_the_product_on_screen_keeps_its_card(self):
        clip = product_id("Loa Bluetooth JBL Clip 5")
        llm = ScriptedLLM([AIMessage(content="JBL Clip 5 kết nối được laptop Windows qua Bluetooth nhé.")])
        agent, models = build(llm)
        result = await self.run_turn(
            agent, models, "loa có kết nối laptop Windows không?", search_turn("loa kết nối windows"),
            focused_products=[{"id": clip, "name": "Loa Bluetooth JBL Clip 5"}],
        )
        self.assertEqual([item["id"] for item in result["products"]], [clip])

    async def test_a_reply_naming_an_earlier_product_shows_its_card(self):
        """The focus has narrowed to one model; the reply suggests another,
        shown turns ago, whether the advisor or the graph wrote it."""
        clip, flip = product_id("Loa Bluetooth JBL Clip 5"), product_id("Loa Bluetooth JBL Flip 6")
        text = "JBL Clip 5 hợp đấy, còn JBL Flip 6 to hơn."

        async def answer(*_args, **_kwargs):
            return text

        detail = SemanticTurn(
            tasks=[SemanticTask(intent="product_detail", query="có hợp không",
                                references=[SemanticReference(kind="active")])], confidence=0.9)
        for advised, turn in ((True, search_turn("loa")), (False, detail)):
            agent, models = build(ScriptedLLM([AIMessage(content=text)]))
            models.answer = answer
            result = await self.run_turn(
                agent, models, "có phù hợp với công việc văn phòng không", turn,
                active_product_id=clip,
                focused_products=[{"id": clip, "name": "Loa Bluetooth JBL Clip 5"}],
                recent_products=[{"id": flip, "name": "Loa Bluetooth JBL Flip 6"},
                                 {"id": clip, "name": "Loa Bluetooth JBL Clip 5"}],
            )
            self.assertEqual("ADVISOR" in result["warnings"], advised)
            self.assertEqual([item["id"] for item in result["products"]], [clip, flip])
            self.assertTrue(result["render_product_cards"])
            self.assertEqual([item["id"] for item in result["recent_products"]], [clip, flip])

    async def test_a_reply_naming_no_product_shows_no_unrelated_cards(self):
        llm = ScriptedLLM([
            AIMessage(content="", tool_calls=[call("search_products", {"query": "loa", "product_type": "loa bluetooth"}, "c1")]),
            AIMessage(content="Loa Bluetooth kết nối laptop qua Bluetooth là được."),
        ])
        agent, models = build(llm)
        result = await self.run_turn(agent, models, "loa kết nối laptop được không", search_turn("loa"))
        self.assertEqual(result["products"], [])

    async def test_the_loop_ends_with_an_answer_after_max_steps(self):
        looping = AIMessage(content="", tool_calls=[call("search_products", {"query": "loa"}, "c")])
        llm = ScriptedLLM([looping] * 4 + [AIMessage(content="Mình gợi ý Loa Bluetooth Xiaomi Sound Outdoor.")])
        agent, models = build(llm)
        result = await self.run_turn(agent, models, "tư vấn loa", search_turn("loa"))
        self.assertEqual(len(llm.sent), 5)
        self.assertIn("Xiaomi Sound Outdoor", result["answer"])


if __name__ == "__main__":
    unittest.main()
