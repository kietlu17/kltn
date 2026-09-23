import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.agents.product import ProductAgent
from src.agents.router import RouterAgent
from src.policy.agent import CustomerServiceAgent
from src.policy.crawler import _content_to_paragraphs
from src.policy.indexer import PolicyEmbeddingCache, _retry_wait, reconcile
from src.policy.pdf import build_policy_pdf
from src.policy.pdf_loader import load_policy_pdf
from src.policy.scraper import parse_article


SOURCE = "https://help.shopee.vn/portal/4/article/77244"


class PolicyAgentTests(unittest.IsolatedAsyncioTestCase):
    def test_policy_embedding_cache_and_server_retry_delay(self):
        with TemporaryDirectory() as temporary:
            cache = PolicyEmbeddingCache(temporary)
            cache.put_many([("chunk", [0.1, 0.2])])
            self.assertEqual(cache.get("chunk"), [0.1, 0.2])
            cache.close()
        self.assertGreaterEqual(_retry_wait("Please retry in 41.5s", 0), 43.5)

    async def test_policy_indexer_batches_embeddings_across_pdf_files(self):
        with TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.pdf"
            second = Path(temporary) / "second.pdf"
            first.touch()
            second.touch()
            chunks_by_name = {
                "first.pdf": [
                    {"title": "A", "text": "one", "sourceUrl": "https://example/a"},
                    {"title": "A", "text": "two", "sourceUrl": "https://example/a"},
                ],
                "second.pdf": [
                    {"title": "B", "text": "three", "sourceUrl": "https://example/b"},
                ],
            }
            models, catalog = AsyncMock(), AsyncMock()
            models.embed_documents.side_effect = lambda texts: [[float(len(text))] for text in texts]
            catalog.replace_source.side_effect = lambda source, chunks, vectors: len(chunks)
            with patch("src.policy.indexer.load_policy_pdf", side_effect=lambda path: chunks_by_name[path.name]), \
                    patch.dict("os.environ", {
                        "CHATBOT_POLICY_EMBED_BATCH_SIZE": "2",
                        "CHATBOT_POLICY_EMBED_DELAY_SECONDS": "0",
                    }):
                count = await reconcile(models, catalog, [temporary])

        self.assertEqual(count, 3)
        self.assertEqual(models.embed_documents.await_count, 2)
        self.assertEqual(catalog.replace_source.await_count, 2)
        first_vectors = catalog.replace_source.await_args_list[0].args[2]
        second_vectors = catalog.replace_source.await_args_list[1].args[2]
        self.assertEqual((len(first_vectors), len(second_vectors)), (2, 1))

    def test_local_pdf_round_trip_keeps_rag_provenance(self):
        article = {
            "articleId": "12345",
            "title": "Chính sách trả hàng",
            "paragraphs": [
                "1. ĐIỀU KIỆN TRẢ HÀNG",
                "Người mua có thể gửi yêu cầu trả hàng theo điều kiện của sàn.",
                "Yêu cầu cần được gửi trong thời hạn hiển thị trên đơn hàng.",
            ],
            "sourceUrl": "https://help.shopee.vn/portal/4/article/12345",
            "crawledAt": "2026-09-23T00:00:00+00:00",
            "hash": "a" * 64,
            "category": "Trả Hàng & Hoàn Tiền",
            "subcategory": "Gửi yêu cầu trả hàng",
        }
        with TemporaryDirectory() as temporary:
            pdf_path = Path(temporary) / "policy.pdf"
            build_policy_pdf(article, pdf_path)
            chunks = load_policy_pdf(pdf_path, chunk_size=180, overlap=20)

        self.assertTrue(chunks)
        self.assertEqual(chunks[0]["articleId"], "12345")
        self.assertEqual(chunks[0]["sourceUrl"], article["sourceUrl"])
        self.assertEqual(chunks[0]["category"], article["category"])
        self.assertEqual(chunks[0]["subcategory"], article["subcategory"])
        self.assertIn("trả hàng", " ".join(chunk["text"] for chunk in chunks).lower())

    def test_portal_html_extraction_keeps_lists_and_tables(self):
        paragraphs = _content_to_paragraphs(
            "<p>Điều kiện</p><ul><li>Còn thời hạn</li></ul>"
            "<table><tr><td>Loại</td><td>Thời gian</td></tr></table>"
        )
        self.assertEqual(paragraphs, ["Điều kiện", "Còn thời hạn", "Loại | Thời gian"])

    async def test_unindexed_policy_topic_does_not_return_unrelated_privacy_text(self):
        models, catalog = AsyncMock(), AsyncMock()
        models.embed_queries.return_value = [[1.0, 0.0]]
        catalog.query.return_value = [SimpleNamespace(payload={
            "title": "CHÍNH SÁCH BẢO MẬT",
            "text": "Nội dung về dữ liệu cá nhân.",
            "sourceUrl": SOURCE,
        })]
        agent = CustomerServiceAgent(models, catalog)

        result = await agent.graph.ainvoke({"message": "Chính sách đổi trả và hoàn tiền thế nào?"})

        self.assertEqual(result["sources"], [])
        self.assertIn("chưa tìm thấy", result["answer"])
        models.chat.assert_not_awaited()

    async def test_router_sends_privacy_question_to_grounded_policy_agent(self):
        models, catalog = AsyncMock(), AsyncMock()
        models.embed_queries.return_value = [[1.0, 0.0]]
        models.chat.return_value = "Sàn thu thập dữ liệu khi người dùng đăng ký. [Nguồn 1]"
        catalog.query.return_value = [SimpleNamespace(payload={
            "title": "CHÍNH SÁCH BẢO MẬT",
            "text": "Sàn có thể thu thập dữ liệu khi người dùng đăng ký tài khoản.",
            "sourceUrl": SOURCE,
        })]
        product = ProductAgent(AsyncMock(), models, AsyncMock())
        customer = CustomerServiceAgent(models, catalog)

        result = await RouterAgent(product, customer).graph.ainvoke({
            "message": "Chính sách bảo mật thu thập dữ liệu khi nào?"
        })

        self.assertEqual(result["route_name"], "customer_service")
        self.assertEqual(result["products"], [])
        self.assertEqual(result["sources"][0]["url"], SOURCE)
        self.assertIn("[Nguồn 1]", result["answer"])

    def test_shopee_article_parser_keeps_provenance_and_chunks(self):
        html = """
        <html><body><div class="article_detail___abc">
          <h2>CHÍNH SÁCH BẢO MẬT</h2>
          <div class="content___abc tiny-editor-preview">
            <p>1. GIỚI THIỆU</p><p>Thông tin chính sách đủ dài để kiểm thử.</p>
            <p>Người dùng có quyền được biết cách dữ liệu cá nhân được xử lý.</p>
            <p>Dữ liệu chỉ được sử dụng theo các mục đích đã công bố.</p>
            <p>Người dùng có thể gửi yêu cầu liên quan đến dữ liệu cá nhân.</p>
          </div>
        </div></body></html>
        """
        chunks = parse_article(html, SOURCE, chunk_size=100, overlap=20)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0]["sourceUrl"], SOURCE)
        self.assertEqual(chunks[0]["articleId"], "77244")
        self.assertEqual(chunks[0]["title"], "CHÍNH SÁCH BẢO MẬT")
        self.assertTrue(chunks[0]["hash"])


if __name__ == "__main__":
    unittest.main()
