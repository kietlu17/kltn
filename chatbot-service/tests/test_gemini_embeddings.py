import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.settings import Settings
from src.infrastructure.models import ModelClients


class GeminiEmbeddingTests(unittest.IsolatedAsyncioTestCase):
    def build_client(self):
        embeddings = MagicMock()
        with patch("src.infrastructure.models.ChatGoogleGenerativeAI"), \
             patch("src.infrastructure.models.GoogleGenerativeAIEmbeddings", return_value=embeddings):
            client = ModelClients(Settings(gemini_api_key="test", embedding_dimensions=3))
        return client, embeddings

    async def test_document_and_query_methods_use_langchain_embedding_roles(self):
        client, embeddings = self.build_client()
        embeddings.aembed_documents = AsyncMock(return_value=[[0, 3, 4], [3, 0, 0]])
        embeddings.aembed_query = AsyncMock(return_value=[0, 0, 2])
        documents = await client.embed_documents(["a", "b"])
        queries = await client.embed_queries(["q"])
        self.assertEqual(documents, [[0.0, 0.6, 0.8], [1.0, 0.0, 0.0]])
        self.assertEqual(queries, [[0.0, 0.0, 1.0]])
        embeddings.aembed_documents.assert_awaited_once_with(["a", "b"])
        embeddings.aembed_query.assert_awaited_once_with("q")

    async def test_invalid_vectors_fail_closed(self):
        client, embeddings = self.build_client()
        for values in [[1, 2], [0, 0, 0], [True, 1, 2]]:
            embeddings.aembed_query = AsyncMock(return_value=values)
            with self.assertRaises(RuntimeError):
                await client.embed_queries(["a"])

    def test_dimension_and_model_changes_isolate_collections(self):
        self.assertNotEqual(Settings().collection, "catalog_deaac8531440")
        self.assertNotEqual(
            Settings(embedding_dimensions=768).collection,
            Settings(embedding_dimensions=1536).collection,
        )
        self.assertNotEqual(Settings().collection, Settings(embedding_model="another-model").collection)
