import json
import unittest

from langchain_core.messages import AIMessageChunk

from app.graph import _contextual_clarification, _is_generic_clarification, _price_value
from app.main import TokenRelay
from app.schemas import ProfileUpdate, SemanticTask, SemanticTurn
from test_api import ChatApiTests
from test_graph import state
from test_production import SemanticModels, build


def chunk(text="", message_id="m1", tool=False):
    return AIMessageChunk(
        content=text,
        id=message_id,
        tool_call_chunks=[{"name": "search_products", "args": "{}", "id": "c1", "index": 0}] if tool else [],
    )


def meta(node):
    return {"langgraph_node": node}


class TokenRelayTests(unittest.TestCase):
    def test_only_reply_nodes_are_relayed(self):
        relay = TokenRelay()
        self.assertEqual(relay.feed(chunk("rank"), meta("retrieve")), [])
        self.assertEqual(relay.feed(chunk("Xin "), meta("finalize")), [("token", {"text": "Xin "})])
        self.assertEqual(relay.feed(chunk("chào"), meta("finalize")), [("token", {"text": "chào"})])

    def test_tool_step_is_withdrawn_and_the_answer_streams(self):
        relay = TokenRelay()
        self.assertEqual(relay.feed(chunk("Để mình tìm", "s1"), meta("advisor")), [("token", {"text": "Để mình tìm"})])
        self.assertEqual(relay.feed(chunk(message_id="s1", tool=True), meta("advisor")), [("reset", {})])
        self.assertEqual(relay.feed(chunk(" thêm", "s1"), meta("advisor")), [])
        self.assertEqual(relay.feed(chunk("Mẫu A", "s2"), meta("advisor")), [("token", {"text": "Mẫu A"})])

    def test_a_new_generation_replaces_the_draft(self):
        relay = TokenRelay()
        relay.feed(chunk("Advisor nói dở", "a1"), meta("advisor"))
        # The advisor failed; the graph's answer starts over.
        self.assertEqual(
            relay.feed(chunk("Câu trả lời", "f1"), meta("finalize")),
            [("reset", {}), ("token", {"text": "Câu trả lời"})],
        )

    def test_silent_tool_step_needs_no_reset(self):
        relay = TokenRelay()
        self.assertEqual(relay.feed(chunk(message_id="s1", tool=True), meta("advisor")), [])
        self.assertEqual(relay.feed(chunk("Kết quả", "s2"), meta("advisor")), [("token", {"text": "Kết quả"})])


class StreamStartsAtOnceTests(ChatApiTests):
    async def test_first_event_is_the_understand_status(self):
        async with self.client.stream(
            "POST", "/assistant/chat/stream", json={"message": "áo sơ mi"}, headers=self.headers
        ) as response:
            raw = "".join([part async for part in response.aiter_text()])
        first = raw.strip().split("\n\n")[0].split("\n")
        self.assertEqual(first[0], "event: status")
        self.assertEqual(json.loads(first[1][6:])["node"], "understand")


class ClarificationTests(unittest.IsolatedAsyncioTestCase):
    def test_generic_detection(self):
        self.assertTrue(_is_generic_clarification("Bạn có thể nói rõ hơn sản phẩm hoặc nhu cầu cần hỗ trợ không?"))
        self.assertTrue(_is_generic_clarification(""))
        self.assertFalse(_is_generic_clarification("Bố bạn thích công nghệ hay đồ dùng hằng ngày?"))

    def test_contextual_question(self):
        self.assertIn("bố 60 tuổi", _contextual_clarification({"recipient": "bố 60 tuổi"}, {}))
        self.assertIn("điện thoại", _contextual_clarification({}, {"product_type": "điện thoại"}))
        self.assertIsNone(_contextual_clarification({}, {}))

    async def test_generic_model_question_is_replaced_from_the_profile(self):
        models = SemanticModels(SemanticTurn(
            tasks=[SemanticTask(intent="clarify")],
            confidence=0.9,
            needs_clarification=True,
            profile_updates=[ProfileUpdate(key="recipient", value="bố 60 tuổi")],
        ))
        agent = build(models)
        result = await agent.graph.ainvoke(
            state("chào shop, mình muốn mua quà cho bố mình 60 tuổi"),
            config={"configurable": {"thread_id": "gift"}},
        )
        self.assertEqual(result["route"], "clarify")
        self.assertIn("bố 60 tuổi", result["answer"])
        self.assertNotIn("nói rõ hơn", result["answer"])

    async def test_a_specific_model_question_is_kept(self):
        question = "Bố bạn thích công nghệ hay chăm sóc sức khỏe? Ngân sách khoảng bao nhiêu?"
        models = SemanticModels(SemanticTurn(
            tasks=[SemanticTask(intent="clarify")], confidence=0.9,
            needs_clarification=True, clarification_question=question,
        ))
        result = await build(models).graph.ainvoke(
            state("mua quà cho bố"), config={"configurable": {"thread_id": "gift2"}}
        )
        self.assertIn(question, result["answer"])


class PriceValueTests(unittest.TestCase):
    def test_amounts_and_non_amounts(self):
        cases = {
            8_000_000: 8_000_000, "8000000": 8_000_000, "8.000.000": 8_000_000, "8 triệu": 8_000_000,
            "dưới 8 triệu": 8_000_000, "500k": 500_000, "1.5 triệu": 1_500_000,
        }
        for value, expected in cases.items():
            self.assertEqual(_price_value(value), expected, value)
        for value in ("rẻ hơn các mẫu vừa xem", "", True, -5, None):
            self.assertIsNone(_price_value(value), value)


if __name__ == "__main__":
    unittest.main()
