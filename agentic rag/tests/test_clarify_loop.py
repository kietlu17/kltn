"""The assistant asks at most one clarifying question in a row."""

import unittest

from langgraph.checkpoint.memory import MemorySaver

from app.config import AgenticSettings
from app.graph import AgenticShoppingGraph
from app.schemas import SemanticTask, SemanticTurn
from test_agents import JudgeModels
from test_graph import FakeMarketplace, FakeRetriever, state


def clarify_turn(question, *tasks):
    return SemanticTurn(
        tasks=list(tasks) or [SemanticTask(intent="clarify")],
        conversation_action="clarify",
        confidence=0.6,
        needs_clarification=True,
        clarification_question=question,
    )


def graph(turn):
    return AgenticShoppingGraph(
        AgenticSettings(gemini_api_key="test"), JudgeModels(turn), FakeRetriever(), FakeMarketplace(),
        checkpointer=MemorySaver(),
    )


def after_question(message, question, original):
    current = state(message)
    current["clarify_count"] = 1
    current["history"] = [
        {"role": "user", "content": "tôi muốn mua áo thun xl"},
        {"role": "assistant", "content": "Mình tìm thấy 5 sản phẩm."},
        {"role": "user", "content": original},
        {"role": "assistant", "content": question},
    ]
    return current


class ClarifyLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_first_real_question_is_still_asked(self):
        turn = clarify_turn("Bạn muốn áo thun, polo hay sơ mi?")
        result = await graph(turn).understand(state("áo cho nam, đề xuất 1 mẫu đi biển"))
        self.assertTrue(result["semantic_turn"]["needs_clarification"])

    async def test_answer_to_the_question_is_joined_with_the_request(self):
        question = "Bạn muốn áo thun nam hay polo, sơ mi để đi biển?"
        turn = clarify_turn("Bạn muốn tìm áo thun nam mặc đi biển đúng không?")
        current = after_question("áo thun", question, "áo cho nam, đề xuất 1 mẫu phù hợp đi biển")
        result = await graph(turn).understand(current)
        semantic = result["semantic_turn"]
        self.assertFalse(semantic["needs_clarification"])
        self.assertEqual(semantic["tasks"][0]["intent"], "product_search")
        self.assertEqual(semantic["tasks"][0]["query"], "áo cho nam, đề xuất 1 mẫu phù hợp đi biển áo thun")
        self.assertIn("ASSUMED_INTENT", result["warnings"])

    async def test_bare_yes_runs_the_search_the_model_proposed(self):
        proposed = SemanticTask(intent="product_search", query="áo thun nam đi biển")
        turn = clarify_turn("Bạn muốn tìm áo thun nam đi biển phải không?", proposed)
        current = after_question("đúng", "Bạn muốn tìm áo thun nam mặc đi biển đúng không?", "áo thun")
        result = await graph(turn).understand(current)
        self.assertEqual(result["semantic_turn"]["tasks"][0]["query"], "áo thun nam đi biển")

    async def test_bare_yes_without_a_proposal_drops_the_yes_word(self):
        turn = clarify_turn("Bạn có thể nói rõ hơn không?")
        current = after_question("đúng rồi", "Bạn muốn tìm áo thun nam đi biển đúng không?", "áo thun nam đi biển")
        result = await graph(turn).understand(current)
        self.assertEqual(result["semantic_turn"]["tasks"][0]["query"], "áo thun nam đi biển")

    async def test_a_yes_no_restatement_of_a_clear_search_is_not_asked(self):
        proposed = SemanticTask(intent="product_search", query="áo thun nam size XL")
        turn = clarify_turn("Bạn muốn tìm áo thun size XL và L màu đen, đúng không?", proposed)
        result = await graph(turn).understand(state("tôi muốn mua 1 cái áo thun xl, 1 L đen"))
        self.assertFalse(result["semantic_turn"]["needs_clarification"])
        self.assertEqual(result["semantic_turn"]["tasks"][0]["intent"], "product_search")


class EmptyCart(FakeMarketplace):
    async def cart(self, _user_id):
        return {"products": []}


class CartQuestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_question_about_the_cart_goes_to_the_real_cart(self):
        turn = clarify_turn("Bạn muốn thanh toán cho món nào (áo thun nam đen XL, tất, hay cả giỏ)?")
        agent = AgenticShoppingGraph(
            AgenticSettings(gemini_api_key="test"), JudgeModels(turn), FakeRetriever(), EmptyCart(),
            checkpointer=MemorySaver(),
        )
        result = await agent.graph.ainvoke(state("thanh toán đơn"), config={"configurable": {"thread_id": "empty"}})
        self.assertEqual(result["route"], "checkout")
        self.assertIn("Giỏ hàng đang trống", result["answer"])
        self.assertNotIn("tất", result["answer"])

    async def test_checkout_task_beside_a_question_wins(self):
        turn = clarify_turn("Thanh toán món nào?", SemanticTask(intent="checkout", query="thanh toán áo"))
        result = await graph(turn).understand(state("thanh toán áo"))
        self.assertEqual(result["semantic_turn"]["tasks"][0]["intent"], "checkout")
        self.assertIn("CART_DECIDES", result["warnings"])


if __name__ == "__main__":
    unittest.main()
