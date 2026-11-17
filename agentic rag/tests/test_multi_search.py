"""One message, several products: "áo thun nam đen XL và 1 cái tất"."""

import unittest

from langgraph.checkpoint.memory import MemorySaver

from app.config import AgenticSettings
from app.graph import AgenticShoppingGraph
from app.schemas import SemanticConstraint, SemanticTask, SemanticTurn
from test_agents import CatalogMarketplace, CatalogRetriever, JudgeModels
from test_graph import state

SHIRTS = [f"{index}" * 24 for index in "12345"]
SOCKS = ["a" * 24, "b" * 24]


class Shop(CatalogMarketplace):
    async def hydrate_products(self, hits, _filters, limit):
        names = {**{item: f"Áo thun nam {n}" for n, item in enumerate(SHIRTS, 1)},
                 **{item: f"Tất cổ ngắn {n}" for n, item in enumerate(SOCKS, 1)}}
        return [
            {"id": hit["productId"], "name": names.get(hit["productId"], "Sản phẩm"), "price": 50000,
             "variants": [], "specifications": []}
            for hit in hits
        ][:limit]


def two_searches():
    return SemanticTurn(
        tasks=[
            SemanticTask(intent="product_search", query="áo thun nam", constraints=[
                SemanticConstraint(key="color", value="đen"), SemanticConstraint(key="size", value="XL")]),
            SemanticTask(intent="product_search", query="tất"),
        ],
        confidence=0.95,
        focus_update="replace",
    )


def build(retriever):
    return AgenticShoppingGraph(
        AgenticSettings(gemini_api_key="test", agentic_mode="graph"),
        JudgeModels(two_searches(), grades={item: 3 for item in SHIRTS}), retriever, Shop(),
        checkpointer=MemorySaver(),
    )


class MultiSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_product_of_the_message_is_searched_too(self):
        retriever = CatalogRetriever({"áo thun nam": SHIRTS, "tất": SOCKS})
        result = await build(retriever).graph.ainvoke(
            state("tôi muốn mua 1 cái áo thun nam đen xl và 1 cái tất"),
            config={"configurable": {"thread_id": "multi"}},
        )
        ids = [item["id"] for item in result["products"]]
        self.assertTrue(set(SOCKS) <= set(ids))
        self.assertTrue(any(item in ids for item in SHIRTS))
        self.assertIn("“tất”", result["answer"])
        self.assertNotIn("Còn phần", result["answer"])
        # The socks are not filtered by the shirt's colour and size.
        sock_call = next(call for call in retriever.calls if call[0] == "tất")
        self.assertEqual(sock_call[1]["colors"], [])
        # "thêm cái tất" can refer to the listed socks next turn.
        self.assertTrue(set(SOCKS) <= {item["id"] for item in result["focused_products"]})

    async def test_nothing_found_for_the_second_product_is_said(self):
        retriever = CatalogRetriever({"áo thun nam": SHIRTS, "tất": []})
        result = await build(retriever).graph.ainvoke(
            state("áo thun nam đen xl và 1 cái tất"), config={"configurable": {"thread_id": "none"}},
        )
        self.assertIn("chưa tìm thấy “tất”", result["answer"])


if __name__ == "__main__":
    unittest.main()
