import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agents.state import SearchPlan
from src.core.settings import Settings
from src.infrastructure.models import ModelClients


class ModelClientTests(unittest.IsolatedAsyncioTestCase):
    def build_client(self):
        llm = MagicMock()
        embeddings = MagicMock()
        with patch("src.infrastructure.models.ChatGoogleGenerativeAI", return_value=llm), \
             patch("src.infrastructure.models.GoogleGenerativeAIEmbeddings", return_value=embeddings):
            client = ModelClients(Settings(gemini_api_key="test", embedding_dimensions=3))
        return client, llm, embeddings

    async def test_structured_output_uses_langchain_model(self):
        client, llm, _ = self.build_client()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content='{"query":"áo"}'))
        result = await client.structured([
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ], SearchPlan)
        self.assertEqual(result.query, "áo")
        messages = llm.ainvoke.call_args.args[0]
        self.assertIsInstance(messages[0], SystemMessage)
        self.assertIn("JSON Schema", messages[0].content)
        self.assertIsInstance(messages[1], SystemMessage)
        self.assertIsInstance(messages[2], HumanMessage)

    async def test_text_and_multimodal_generation(self):
        client, llm, _ = self.build_client()
        llm.ainvoke = AsyncMock(side_effect=[
            AIMessage(content="Câu trả lời"),
            AIMessage(content="Áo đỏ cổ tròn"),
        ])
        self.assertEqual(await client.chat([{"role": "user", "content": "hello"}]), "Câu trả lời")
        self.assertEqual(await client.describe("base64-image"), "Áo đỏ cổ tròn")
        image_message = llm.ainvoke.call_args.args[0][1]
        self.assertEqual(image_message.content[1]["base64"], "base64-image")

    async def test_missing_key_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
            ModelClients(Settings(gemini_api_key=""))
