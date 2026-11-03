import unittest
from types import SimpleNamespace

from app.config import AgenticSettings
from app.retrieval import StructuredProductRetriever, _search_terms
from app.schemas import SearchFilters


class Point:
    def __init__(self, product_id, score=None, chunk="base"):
        self.payload = {"productId": product_id, "chunkType": chunk, "text": product_id}
        self.score = score


class FacetClient:
    values = {
        "productType": ["ao_thun", "dien_thoai", "tai_nghe"],
        "audience": ["nam", "nu", "unisex"],
        "colors": ["trang", "den", "xanh"],
        "sizes": ["M", "L", "XL", "2XL"],
        "brand": ["YODY", "Apple"],
    }

    async def facet(self, _collection, key, **_kwargs):
        return SimpleNamespace(
            hits=[SimpleNamespace(value=value) for value in self.values.get(key, [])]
        )


class OrderedClient(FacetClient):
    values = {**FacetClient.values, "productType": [*FacetClient.values["productType"], "loa"]}

    def __init__(self):
        self.scroll_filter = None
        self.order_by = None

    async def scroll(self, _collection, **kwargs):
        self.scroll_filter = kwargs["scroll_filter"]
        self.order_by = kwargs["order_by"]
        return [Point("speaker-expensive"), Point("speaker-cheaper")], None


class HybridClient(FacetClient):
    def __init__(self, sparse=True):
        self.sparse = sparse
        self.calls = []

    async def get_collection(self, _collection):
        sparse = {"bm25": object()} if self.sparse else None
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(sparse_vectors=sparse)))

    async def query_points_groups(self, _collection, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            groups=[
                SimpleNamespace(id="p1", hits=[Point("p1", 0.9), Point("p1", 0.8, "specs")]),
                SimpleNamespace(id="p2", hits=[Point("p2", 0.7)]),
            ]
        )


class EmbeddingModels:
    async def embed_query(self, _query):
        return [0.1, 0.2]


class ProductContextClient:
    async def scroll(self, _collection, **_kwargs):
        return [
            SimpleNamespace(
                payload={
                    "productId": "a" * 24,
                    "productType": "ao_thun",
                    "audience": ["nam"],
                    "colors": ["den"],
                    "sizes": ["L"],
                    "minPrice": 200000,
                    "maxPrice": 250000,
                    "text": "Áo thun nam màu đen",
                }
            ),
            SimpleNamespace(
                payload={
                    "productId": "a" * 24,
                    "productType": "ao_thun",
                    "audience": ["nam"],
                    "colors": ["trang"],
                    "sizes": ["M", "L"],
                    "minPrice": 190000,
                    "maxPrice": 260000,
                    "text": "Áo thun nam màu trắng",
                }
            ),
        ], None


class UnknownTypeContextClient:
    async def scroll(self, _collection, **_kwargs):
        return [
            SimpleNamespace(
                payload={
                    "productId": "b" * 24,
                    "productType": "khac",
                    "minPrice": 450000,
                    "maxPrice": 450000,
                    "text": (
                        "Tên sản phẩm: Loa Bluetooth Xiaomi Essential\n"
                        "Mô tả: Có thể điều khiển bằng điện thoại."
                    ),
                }
            )
        ], None

    async def facet(self, _collection, key, **_kwargs):
        values = ["khac", "loa", "dien_thoai"] if key == "productType" else []
        return SimpleNamespace(
            hits=[SimpleNamespace(value=value) for value in values]
        )


class RetrievalTests(unittest.TestCase):
    def test_filter_keeps_hard_constraints_out_of_vector_scoring(self):
        filters = SearchFilters(
            category_id="cat-1",
            audience="nu",
            colors=["trắng"],
            sizes=["M"],
            min_price=100000,
            max_price=500000,
        )
        built = StructuredProductRetriever._build_filter(filters)
        keys = [condition.key for condition in built.must]
        self.assertIn("categoryId", keys)
        self.assertIn("audience", keys)
        self.assertIn("colors", keys)
        self.assertIn("sizes", keys)
        self.assertIn("minPrice", keys)
        self.assertIn("maxPrice", keys)

    def test_parent_category_expands_to_match_any_descendant_id(self):
        category_ids = ["a" * 24, "b" * 24]
        built = StructuredProductRetriever._build_filter(
            SearchFilters(category_path="Quần áo", category_ids=category_ids)
        )
        category = next(item for item in built.must if item.key == "categoryId")
        self.assertEqual(category.match.any, category_ids)

    def test_lexical_terms_remove_generic_shopping_words(self):
        self.assertEqual(_search_terms("Tôi muốn tìm áo sơ mi trắng"), ["ao", "so", "mi", "trang"])

    def test_lexical_terms_remove_price_superlative_words(self):
        self.assertEqual(_search_terms("loa mắt nhất là bao nhiêu tiền"), ["loa"])

    def test_excluded_anchor_product_becomes_qdrant_must_not(self):
        product_id = "a" * 24
        built = StructuredProductRetriever._build_filter(
            SearchFilters(exclude_product_ids=[product_id])
        )
        excluded = next(item for item in built.must_not if item.key == "productId")
        self.assertEqual(excluded.match.any, [product_id])


class TaxonomyResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_product_context_aggregates_all_indexed_variant_groups(self):
        retriever = StructuredProductRetriever(
            AgenticSettings(gemini_api_key="test"),
            models_gateway=SimpleNamespace(),
            client=ProductContextClient(),
        )

        context = await retriever.product_context("a" * 24)

        self.assertEqual(context["productType"], "ao_thun")
        self.assertEqual(context["audience"], ["nam"])
        self.assertEqual(context["colors"], ["den", "trang"])
        self.assertEqual(context["sizes"], ["L", "M"])
        self.assertEqual(context["minPrice"], 190000)
        self.assertEqual(context["maxPrice"], 260000)

    async def test_product_context_repairs_unknown_type_from_live_vocabulary(self):
        retriever = StructuredProductRetriever(
            AgenticSettings(gemini_api_key="test"),
            models_gateway=SimpleNamespace(),
            client=UnknownTypeContextClient(),
        )

        context = await retriever.product_context("b" * 24)

        self.assertEqual(context["productType"], "loa")

    async def test_ranked_search_uses_live_product_type_and_price_index(self):
        client = OrderedClient()
        retriever = StructuredProductRetriever(
            AgenticSettings(gemini_api_key="test"),
            models_gateway=SimpleNamespace(),
            client=client,
        )

        hits = await retriever.search(
            "loa mắt nhất",
            SearchFilters(),
            limit=6,
            sort_by="price_desc",
        )

        product_type = next(
            item for item in client.scroll_filter.must if item.key == "productType"
        )
        self.assertEqual(product_type.match.value, "loa")
        self.assertEqual(client.order_by.key, "maxPrice")
        self.assertEqual(client.order_by.direction.value, "desc")
        self.assertEqual(
            [item["productId"] for item in hits],
            ["speaker-expensive", "speaker-cheaper"],
        )

    async def test_hybrid_search_fuses_dense_and_bm25_grouped_by_product(self):
        client = HybridClient()
        retriever = StructuredProductRetriever(
            AgenticSettings(gemini_api_key="test"),
            models_gateway=EmbeddingModels(),
            client=client,
        )

        hits = await retriever.search("áo thun đỏ", SearchFilters(), limit=6)

        call = client.calls[0]
        self.assertEqual(call["group_by"], "productId")
        self.assertEqual([item.using for item in call["prefetch"]], [None, "bm25"])
        self.assertEqual(call["query"].fusion.value, "rrf")
        self.assertEqual([hit["productId"] for hit in hits], ["p1", "p2"])
        self.assertEqual(len(hits[0]["evidence"]), 2)

    async def test_collection_without_sparse_vector_uses_grouped_dense(self):
        client = HybridClient(sparse=False)
        retriever = StructuredProductRetriever(
            AgenticSettings(gemini_api_key="test"),
            models_gateway=EmbeddingModels(),
            client=client,
        )

        hits = await retriever.search("áo thun", SearchFilters(), limit=6)

        self.assertNotIn("prefetch", client.calls[0])
        self.assertEqual(client.calls[0]["query"], [0.1, 0.2])
        self.assertEqual(hits[0]["sources"], ["dense"])

    async def test_natural_facets_resolve_against_live_catalog_vocabulary(self):
        retriever = StructuredProductRetriever(
            AgenticSettings(gemini_api_key="test"),
            models_gateway=SimpleNamespace(),
            client=FacetClient(),
        )
        resolved = await retriever._resolve_catalog_filters(
            SearchFilters(
                product_type="áo thun",
                audience="nam",
                colors=["trắng"],
                sizes=["2xl"],
                brand="yody",
            )
        )
        self.assertEqual(resolved.product_type, "ao_thun")
        self.assertEqual(resolved.audience, "nam")
        self.assertEqual(resolved.colors, ["trang"])
        self.assertEqual(resolved.sizes, ["2XL"])
        self.assertEqual(resolved.brand, "YODY")

    async def test_unknown_taxonomy_values_fall_back_to_semantic_search(self):
        retriever = StructuredProductRetriever(
            AgenticSettings(gemini_api_key="test"),
            models_gateway=SimpleNamespace(),
            client=FacetClient(),
        )
        resolved = await retriever._resolve_catalog_filters(
            SearchFilters(
                category_id="thoi-trang-nam",
                product_type="mat hang chua co trong taxonomy",
                colors=["mau hiem chua duoc lap chi muc"],
            )
        )
        self.assertIsNone(resolved.category_id)
        self.assertIsNone(resolved.product_type)
        self.assertEqual(resolved.colors, [])


if __name__ == "__main__":
    unittest.main()

