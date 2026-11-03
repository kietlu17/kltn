import json
import unittest

import httpx
from langgraph.checkpoint.memory import MemorySaver

from app.config import AgenticSettings
from app.graph import AgenticShoppingGraph
from app.main import create_agentic_app
from app.schemas import SemanticTask, SemanticTurn
from test_graph import FakeMarketplace, FakeRetriever
from test_production import SemanticModels


class ChatApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.models = SemanticModels(
            SemanticTurn(
                tasks=[SemanticTask(intent="product_search", query="áo sơ mi")],
                confidence=0.2,
            )
        )
        settings = AgenticSettings(gemini_api_key="test")
        checkpointer = MemorySaver()
        self.app = create_agentic_app()
        # ASGITransport does not run the lifespan; wire the state directly.
        self.app.state.settings = settings
        self.app.state.checkpointer = checkpointer
        self.app.state.busy_sessions = set()
        self.app.state.agent = AgenticShoppingGraph(
            settings, self.models, FakeRetriever(), FakeMarketplace(), checkpointer=checkpointer
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://test"
        )
        self.headers = {"x-user-id": "buyer-1", "x-user-role": "buyer"}

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_clarification_count_persists_across_requests(self):
        first = await self.client.post(
            "/assistant/chat", json={"message": "cái đó"}, headers=self.headers
        )
        self.assertEqual(first.status_code, 200)
        body = first.json()
        self.assertEqual(body["route"], "clarify")
        self.assertEqual(body["suggestions"], ["Thời trang"])
        session = body["sessionId"]
        for message in ("cái kia", "nói chung vậy"):
            last = await self.client.post(
                "/assistant/chat",
                json={"message": message, "sessionId": session},
                headers=self.headers,
            )
        self.assertTrue(last.json()["handoff"])

    async def test_stream_emits_status_then_final_response(self):
        self.models.turn = SemanticTurn(
            tasks=[SemanticTask(intent="product_search", query="áo sơ mi")],
            confidence=0.95,
            focus_update="replace",
        )
        async with self.client.stream(
            "POST", "/assistant/chat/stream", json={"message": "áo sơ mi"}, headers=self.headers
        ) as response:
            self.assertEqual(response.status_code, 200)
            raw = "".join([chunk async for chunk in response.aiter_text()])
        events = [
            (block.split("\n")[0].removeprefix("event: "), json.loads(block.split("\n")[1][6:]))
            for block in raw.strip().split("\n\n")
        ]
        names = [name for name, _payload in events]
        self.assertIn("status", names)
        self.assertLess(names.index("products"), names.index("final"))
        final = events[-1][1]
        self.assertEqual(final["route"], "product_search")
        self.assertIn("Mình tìm thấy 1 sản phẩm", final["answer"])
        self.assertEqual(self.app.state.busy_sessions, set())


if __name__ == "__main__":
    unittest.main()
