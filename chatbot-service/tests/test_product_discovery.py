import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from qdrant_client import AsyncQdrantClient, models

from src.agents.product import ProductAgent
from src.agents.intent import TurnIntent
from src.infrastructure.models import ModelClients
from src.product.catalog import VectorCatalog
from src.product.discovery import SearchExploration, lexical_terms
from src.product.rag import ProductRAG


BOOK = "c" * 24
BAG = "d" * 24


class ProductDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_overview_uses_categories_without_embedding(self):
        api, llm, vectors = AsyncMock(), AsyncMock(), AsyncMock()
        api.categories.return_value = [
            {"_id": "fashion", "name": "Thời trang"},
            {"_id": "electronics", "name": "Điện tử"},
            {"_id": "empty", "name": "Danh mục trống"},
        ]
        vectors.category_counts.return_value = {"fashion": 10, "electronics": 5}
        llm.understand_intent.return_value = TurnIntent(browse_catalog=True)
        result = await ProductAgent(api, llm, vectors).graph.ainvoke({"message": "Shop bán gì?"})
        self.assertEqual(result["retrieval_mode"], "category_browse")
        self.assertEqual(result["plan"]["query"], "")
        self.assertIn("Thời trang, Điện tử", result["answer"])
        self.assertNotIn("Danh mục trống", result["answer"])
        llm.embed_queries.assert_not_awaited()

    async def test_lexical_candidates_respect_price_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            client = AsyncQdrantClient(path=directory)
            catalog = VectorCatalog(SimpleNamespace(collection="products"), client)
            try:
                await catalog.ensure(3)
                await catalog.upsert([
                    models.PointStruct(id=1, vector=[1., 0., 0.], payload={
                        "productId": BOOK, "kind": "text", "text": "Tên sản phẩm: Sách lập trình cho bé",
                        "chunkType": "base", "categoryId": "books",
                        "minPrice": 200000, "maxPrice": 200000,
                    }),
                    models.PointStruct(id=2, vector=[0., 1., 0.], payload={
                        "productId": BAG, "kind": "text", "text": "Tên sản phẩm: Sách lập trình cho bé cao cấp",
                        "chunkType": "base", "categoryId": "books",
                        "minPrice": 900000, "maxPrice": 900000,
                    }),
                ])
                hits = await catalog.query(None, kind="text", text_query="sách lập trình",
                                           metadata={"max_price": 500000})
                self.assertEqual([hit.payload["productId"] for hit in hits], [BOOK])
                self.assertEqual(await catalog.category_counts(), {"books": 2})
            finally:
                await catalog.close()

    async def test_hybrid_retrieval_recovers_exact_name(self):
        api, llm, vectors = AsyncMock(), AsyncMock(), AsyncMock()
        llm.embed_queries.return_value = [[1., 0., 0.]]
        vectors.query.side_effect = lambda vector, **kwargs: (
            [SimpleNamespace(payload={"productId": BOOK,
                                      "text": "Tên sản phẩm: Áo sơ mi xanh"})]
            if kwargs.get("text_query") else []
        )
        api.fresh.return_value = ([{
            "_id": BOOK, "name": "Áo sơ mi xanh", "price": 200000,
            "moderationStatus": "approved", "images": [],
        }], {(BOOK, ""): 2})
        api.review_summaries.return_value = {"items": []}
        result = await ProductRAG(api, llm, vectors)._text_candidates({
            "message": "áo sơ mi xanh", "plan": {"intent": "search", "query": "áo sơ mi xanh",
                                                   "product_type": "ao_so_mi"},
        })
        self.assertEqual([card["id"] for card in result["products"]], [BOOK])
        self.assertEqual(len(llm.embed_queries.await_args.args[0]), 1)

    async def test_show_more_excludes_previous_cards(self):
        api, llm, vectors = AsyncMock(), AsyncMock(), AsyncMock()
        llm.embed_queries.return_value = [[1.]]
        vectors.query.side_effect = lambda vector, **kwargs: (
            [] if kwargs.get("text_query") else [
                SimpleNamespace(payload={"productId": BOOK}),
                SimpleNamespace(payload={"productId": BAG}),
            ]
        )
        api.fresh.return_value = ([
            {"_id": BAG, "name": "Áo sơ mi đỏ", "price": 250000,
             "moderationStatus": "approved", "images": []},
        ], {(BAG, ""): 2})
        api.review_summaries.return_value = {"items": []}
        result = await ProductRAG(api, llm, vectors)._text_candidates({
            "message": "Cho xem thêm mẫu khác cùng nhu cầu",
            "turn_understanding": {"show_more": True},
            "previous_products": [{"id": BOOK}],
            "plan": {"intent": "search", "query": "áo sơ mi", "product_type": "ao_so_mi"},
        })
        self.assertEqual([card["id"] for card in result["products"]], [BAG])
        self.assertEqual(api.fresh.await_args.args[0], [BAG])

    async def test_broad_intent_expands_queries_without_bypassing_constraints(self):
        api, llm, vectors = AsyncMock(), AsyncMock(), AsyncMock()
        llm.structured.return_value = SearchExploration(queries=["sách thiếu nhi", "balo trẻ em"])
        llm.shopping_research.return_value = ("Sách là một ý tưởng quà tặng.", ["https://example.com"])
        llm.embed_queries.return_value = [[1.], [2.], [3.]]

        async def find(vector, **kwargs):
            if kwargs.get("text_query"):
                return []
            product_id = {2.: BOOK, 3.: BAG}.get(vector[0])
            return [SimpleNamespace(payload={"productId": product_id})] if product_id else []

        vectors.query.side_effect = find
        api.fresh.return_value = ([
            {"_id": BOOK, "name": "Sách thiếu nhi", "price": 200000,
             "moderationStatus": "approved", "images": []},
            {"_id": BAG, "name": "Balo trẻ em", "price": 700000,
             "moderationStatus": "approved", "images": []},
        ], {(BOOK, ""): 5, (BAG, ""): 5})
        api.review_summaries.return_value = {"items": []}
        result = await ProductRAG(api, llm, vectors)._text_candidates({
            "message": "quà sinh nhật cho bé dưới 500000đ",
            "turn_understanding": {"explore_need": True},
            "plan": {"intent": "search", "query": "quà sinh nhật cho bé", "max_price": 500000},
        })
        self.assertEqual([card["id"] for card in result["products"]], [BOOK])
        self.assertEqual(len(llm.embed_queries.await_args.args[0]), 3)
        llm.structured.assert_awaited_once()
        llm.shopping_research.assert_awaited_once()
        self.assertIn("untrusted_web_ideas", llm.structured.await_args.args[0][1]["content"])

    async def test_shopping_research_requires_grounding(self):
        client = ModelClients.__new__(ModelClients)
        client.llm = MagicMock()
        call = client.llm.bind_tools.return_value.ainvoke = AsyncMock()
        call.return_value = SimpleNamespace(text="Mua sản phẩm X", response_metadata={})
        self.assertEqual(await client.shopping_research("quà cho bé"), ("", []))
        call.return_value = SimpleNamespace(text="Sách và đồ chơi", response_metadata={
            "grounding_metadata": {"grounding_chunks": [{"web": {"uri": "https://example.com"}}],
                                   "grounding_supports": [{}]},
        })
        self.assertEqual(await client.shopping_research("quà cho bé"),
                         ("Sách và đồ chơi", ["https://example.com"]))

    def test_lexical_terms_keep_product_models(self):
        self.assertIn("iphone", lexical_terms("Tìm iPhone 15 Pro"))
