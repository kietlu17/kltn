import unittest
from types import SimpleNamespace

from app.policy import PolicyRetriever
from app.graph import AgenticShoppingGraph


class PolicyRetrieverTests(unittest.IsolatedAsyncioTestCase):
    async def test_sources_keep_existing_policy_contract_and_deduplicate(self):
        class Models:
            async def embed_query(self, _question):
                return [0.1, 0.2]

        class Client:
            async def collection_exists(self, _collection):
                return True

            async def query_points(self, *_args, **_kwargs):
                payload = {
                    "title": "Chính sách bảo hành",
                    "text": "Sản phẩm đủ điều kiện được bảo hành theo tài liệu.",
                    "sourceUrl": "https://example.test/warranty",
                }
                return SimpleNamespace(
                    points=[
                        SimpleNamespace(payload=payload),
                        SimpleNamespace(payload={**payload, "text": "Đoạn tiếp theo."}),
                    ]
                )

        settings = SimpleNamespace(
            qdrant_url="http://qdrant:6333",
            request_timeout=10,
            embedding_model="embedding-model",
            embedding_dimensions=768,
        )
        retriever = PolicyRetriever(settings, Models(), client=Client())
        context, sources = await retriever.retrieve("bảo hành")
        self.assertEqual(len(context), 2)
        self.assertEqual(
            sources,
            [
                {
                    "number": 1,
                    "title": "Chính sách bảo hành",
                    "url": "https://example.test/warranty",
                }
            ],
        )

    async def test_policy_response_exposes_only_cited_sources(self):
        class Policy:
            async def retrieve(self, _question):
                return (
                    [{"number": 1, "title": "Bảo hành", "text": "Có bảo hành."}],
                    [
                        {"number": 1, "title": "Bảo hành", "url": "https://one"},
                        {"number": 2, "title": "Bảo hiểm", "url": "https://two"},
                    ],
                )

        class Models:
            async def answer_policy(self, _question, _context):
                return "Sản phẩm đủ điều kiện được bảo hành [Nguồn 1]."

        agent = object.__new__(AgenticShoppingGraph)
        agent.policy = Policy()
        agent.models = Models()
        answer, sources = await agent._policy_result("chính sách bảo hành")
        self.assertIn("[Nguồn 1]", answer)
        self.assertEqual([item["number"] for item in sources], [1])


if __name__ == "__main__":
    unittest.main()
