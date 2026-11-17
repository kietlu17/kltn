import asyncio
import unittest

import httpx
from langgraph.checkpoint.memory import MemorySaver

from app.config import AgenticSettings
from app.graph import AgenticShoppingGraph
from app.main import create_agentic_app
from app.memory import (
    MAX_BACKLOG_MESSAGES,
    apply_profile_updates,
    extend_backlog,
    memory_context,
    memory_note,
    resolved_message,
    split_history,
)
from app.schemas import ProfileUpdate, SemanticTask, SemanticTurn
from test_graph import FakeMarketplace, FakeRetriever, state
from test_production import SemanticModels, build


class ProfileTests(unittest.TestCase):
    def test_set_replace_and_remove(self):
        profile = apply_profile_updates({}, [
            ProfileUpdate(key="recipient", value="bố 60 tuổi"),
            {"key": "avoided_brands", "value": "Xiaomi"},
        ])
        self.assertEqual(profile, {"recipient": "bố 60 tuổi", "avoided_brands": "Xiaomi"})
        profile = apply_profile_updates(profile, [
            {"key": "avoided_brands", "action": "remove"},
            {"key": "body", "value": "cao 1m70, size L"},
        ])
        self.assertEqual(profile, {"recipient": "bố 60 tuổi", "body": "cao 1m70, size L"})

    def test_empty_value_drops_and_bad_updates_are_ignored(self):
        profile = apply_profile_updates(
            {"style": "tối giản", "unknown": "x"},
            [{"key": "style", "value": "  "}, {"key": "budget", "value": "5 triệu"}, "rác"],
        )
        self.assertEqual(profile, {})

    def test_semantic_turn_accepts_and_caps_updates(self):
        turn = SemanticTurn.model_validate({
            "tasks": [{"intent": "general"}],
            "profile_updates": [{"key": "notes", "value": f"ghi chú {index}"} for index in range(9)],
        })
        self.assertEqual(len(turn.profile_updates), 6)
        self.assertEqual(SemanticTurn(tasks=[SemanticTask(intent="general")]).profile_updates, [])


class HistoryTests(unittest.TestCase):
    def messages(self, count):
        return [{"role": "user" if i % 2 == 0 else "assistant", "content": str(i)} for i in range(count)]

    def test_nothing_leaves_until_the_window_overflows(self):
        kept, evicted = split_history(self.messages(20), keep=12, maximum=20)
        self.assertEqual((len(kept), evicted), (20, []))

    def test_overflow_cuts_back_to_keep_in_one_batch(self):
        kept, evicted = split_history(self.messages(22), keep=12, maximum=20)
        self.assertEqual([item["content"] for item in kept], [str(i) for i in range(10, 22)])
        self.assertEqual(len(evicted), 10)
        self.assertEqual(kept[0]["role"], "user")

    def test_backlog_is_bounded(self):
        backlog = extend_backlog(self.messages(30), self.messages(30))
        self.assertEqual(len(backlog), MAX_BACKLOG_MESSAGES)

    def test_memory_views(self):
        state = {"conversation_summary": "Khách tìm laptop dưới 20 triệu.", "shopper_profile": {"use_case": "lập trình"}}
        self.assertEqual(
            memory_context(state),
            {
                "earlier_conversation_summary": "Khách tìm laptop dưới 20 triệu.",
                "shopper_profile": {"use_case": "lập trình"},
            },
        )
        self.assertIn("Mục đích sử dụng: lập trình", memory_note(state))
        self.assertEqual(memory_context({}), {})
        self.assertEqual(memory_note({}), "")


class MemoryModels(SemanticModels):
    def __init__(self, turn=None):
        super().__init__(turn)
        self.summaries: list[tuple[str, list[dict]]] = []
        self.memories: list[str] = []
        self.decide_states: list[dict] = []
        self.fail_summary = False

    async def decide(self, *args, **kwargs):
        self.decide_states.append(kwargs.get("conversation_state") or {})
        return await super().decide(*args, **kwargs)

    async def answer(self, message, plan, result, products, history, memory=""):
        self.answer_calls += 1
        self.memories.append(memory)
        return f"Trả lời: {message}"

    async def summarize(self, previous_summary, messages):
        if self.fail_summary:
            raise RuntimeError("model down")
        self.summaries.append((previous_summary, list(messages)))
        return (previous_summary + " | " if previous_summary else "") + f"{len(messages)} tin cũ"


class SessionMemoryApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.models = MemoryModels(
            SemanticTurn(
                tasks=[SemanticTask(intent="general", query="chào")],
                confidence=0.95,
                profile_updates=[ProfileUpdate(key="recipient", value="bố 60 tuổi")],
            )
        )
        settings = AgenticSettings(
            gemini_api_key="test", history_keep_messages=4, history_max_messages=6
        )
        self.checkpointer = MemorySaver()
        self.app = create_agentic_app()
        self.app.state.settings = settings
        self.app.state.checkpointer = self.checkpointer
        self.app.state.busy_sessions = set()
        self.app.state.models = self.models
        self.app.state.agent = AgenticShoppingGraph(
            settings, self.models, FakeRetriever(), FakeMarketplace(), checkpointer=self.checkpointer
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://test"
        )
        self.headers = {"x-user-id": "buyer-1", "x-user-role": "buyer"}

    async def asyncTearDown(self):
        await self.client.aclose()

    async def chat(self, message, session=None):
        response = await self.client.post(
            "/assistant/chat",
            json={"message": message, **({"sessionId": session} if session else {})},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["sessionId"]

    async def values(self, session):
        await asyncio.gather(*self.app.state.summary_tasks.values())
        snapshot = await self.app.state.agent.graph.aget_state(
            {"configurable": {"thread_id": session}}
        )
        return snapshot.values

    async def test_profile_persists_and_reaches_decide_and_answer(self):
        session = await self.chat("mình muốn mua quà cho bố 60 tuổi")
        self.models.turn = SemanticTurn(tasks=[SemanticTask(intent="general")], confidence=0.95)
        await self.chat("có gì gợi ý không", session)
        values = await self.values(session)
        self.assertEqual(values["shopper_profile"], {"recipient": "bố 60 tuổi"})
        self.assertEqual(
            self.models.decide_states[-1]["shopper_profile"], {"recipient": "bố 60 tuổi"}
        )
        self.assertIn("Mua cho: bố 60 tuổi", self.models.memories[-1])

    async def test_overflow_is_summarized_and_next_turn_sees_it(self):
        session = await self.chat("tin 1")
        for index in range(2, 4):
            await self.chat(f"tin {index}", session)
        values = await self.values(session)
        # 3 turns = 6 messages: still within the window.
        self.assertEqual(len(values["history"]), 6)
        self.assertEqual(self.models.summaries, [])

        await self.chat("tin 4", session)
        values = await self.values(session)
        self.assertEqual([item["content"] for item in values["history"]][0], "tin 3")
        self.assertEqual(len(values["history"]), 4)
        self.assertEqual(values["summary_backlog"], [])
        self.assertEqual(values["conversation_summary"], "4 tin cũ")
        self.assertEqual(
            [item["content"] for item in self.models.summaries[0][1] if item["role"] == "user"],
            ["tin 1", "tin 2"],
        )

        await self.chat("tin 5", session)
        self.assertEqual(
            self.models.decide_states[-1]["earlier_conversation_summary"], "4 tin cũ"
        )
        self.assertIn("4 tin cũ", self.models.memories[-1])

    async def test_failed_summary_keeps_backlog_for_retry(self):
        self.models.fail_summary = True
        session = await self.chat("tin 1")
        for index in range(2, 5):
            await self.chat(f"tin {index}", session)
        values = await self.values(session)
        self.assertEqual(len(values["summary_backlog"]), 4)
        self.assertEqual(values.get("conversation_summary", ""), "")

        self.models.fail_summary = False
        # The next turn retries the kept backlog, then a later overflow is
        # folded on top of that summary.
        for index in range(5, 7):
            await self.chat(f"tin {index}", session)
        values = await self.values(session)
        self.assertEqual(values["summary_backlog"], [])
        self.assertEqual([len(batch) for _prev, batch in self.models.summaries], [4, 4])
        self.assertEqual(values["conversation_summary"], "4 tin cũ | 4 tin cũ")



class RecordingPolicy:
    def __init__(self):
        self.questions = []

    async def retrieve(self, question):
        self.questions.append(question)
        return (
            [{"number": 1, "title": "Bảo hành", "text": "Laptop bảo hành 12 tháng", "url": ""}],
            [{"number": 1, "title": "Bảo hành", "url": ""}],
        )


class StandaloneQueryTests(unittest.IsolatedAsyncioTestCase):
    def test_schema_normalizes_and_caps_the_rewrite(self):
        turn = SemanticTurn.model_validate({
            "tasks": [{"intent": "general"}],
            "standalone_query": "  Laptop   Asus\nbảo hành bao lâu? " + "x" * 600,
        })
        self.assertTrue(turn.standalone_query.startswith("Laptop Asus bảo hành bao lâu?"))
        self.assertEqual(len(turn.standalone_query), 500)

    def test_resolved_message_falls_back_to_the_typed_message(self):
        self.assertEqual(resolved_message({"message": "thế còn bảo hành?"}), "thế còn bảo hành?")
        self.assertEqual(
            resolved_message({"message": "thế còn bảo hành?", "standalone_query": " Bảo hành laptop bao lâu? "}),
            "Bảo hành laptop bao lâu?",
        )

    async def test_policy_retrieval_uses_the_rewrite_when_the_task_has_no_query(self):
        models = MemoryModels(
            SemanticTurn(
                tasks=[SemanticTask(intent="policy")],
                confidence=0.95,
                standalone_query="Chính sách bảo hành laptop là bao lâu?",
            )
        )
        policy = RecordingPolicy()
        agent = build(models, policy=policy)
        result = await agent.graph.ainvoke(
            state("thế còn bảo hành?"), config={"configurable": {"thread_id": "rewrite"}}
        )
        self.assertEqual(result["route"], "policy")
        self.assertEqual(policy.questions, ["Chính sách bảo hành laptop là bao lâu?"])
        self.assertEqual(result["standalone_query"], "Chính sách bảo hành laptop là bao lâu?")

    async def test_without_a_rewrite_the_typed_message_is_used(self):
        models = MemoryModels(SemanticTurn(tasks=[SemanticTask(intent="policy")], confidence=0.95))
        policy = RecordingPolicy()
        agent = build(models, policy=policy)
        await agent.graph.ainvoke(
            state("chính sách bảo hành thế nào"), config={"configurable": {"thread_id": "plain"}}
        )
        self.assertEqual(policy.questions, ["chính sách bảo hành thế nào"])


if __name__ == "__main__":
    unittest.main()
