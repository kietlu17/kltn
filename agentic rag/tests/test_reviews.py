"""Buyers' reviews reach the product cards and the models that advise."""

import base64
import json
import unittest

import httpx

from app.config import AgenticSettings
from app.marketplace import MarketplaceClient
from app.models import GeminiGateway
from app.agents.advisor import _brief, _full
from app.agents.product import ProductAgent
from app.schemas import SearchFilters, SemanticTask, SemanticTurn

PRODUCT = "6" * 24
SETTINGS = dict(gemini_api_key="test")


def transport(review_status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/products/batch"):
            return httpx.Response(200, json=[{
                "_id": PRODUCT, "name": "Áo thun nam basic", "price": 199000, "moderationStatus": "approved",
                "variants": [], "specifications": [],
            }])
        if path.endswith("/inventory/products"):
            return httpx.Response(200, json={"items": [{"productId": PRODUCT, "variantId": "", "availableStock": 5}]})
        if path.endswith("/reviews/products/insights"):
            if review_status != 200:
                return httpx.Response(review_status, json={"message": "down"})
            return httpx.Response(200, json={"items": [{
                "productId": PRODUCT, "averageRating": 4.33, "reviewCount": 12,
                "ratingCounts": {"1": 0, "2": 1, "3": 1, "4": 3, "5": 7},
                "highlights": [
                    {"rating": 5, "comment": "Vải mềm mát. Form hơi nhỏ, nên lấy tăng 1 size.", "userName": "An"},
                    {"rating": 2, "comment": "Giặt lần đầu hơi co một chút.", "userName": "Bình"},
                ],
            }]})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def client(review_status=200):
    settings = AgenticSettings(**SETTINGS)
    return MarketplaceClient(settings, http=httpx.AsyncClient(transport=transport(review_status)))


class ReviewCardTests(unittest.IsolatedAsyncioTestCase):
    async def test_cards_carry_rating_and_highlights(self):
        cards = await client().hydrate_products([{"productId": PRODUCT}], SearchFilters(), 5)
        card = cards[0]
        self.assertEqual(card["rating"], 4.3)
        self.assertEqual(card["reviewCount"], 12)
        self.assertEqual(card["ratingCounts"]["5"], 7)
        self.assertIn("tăng 1 size", card["reviewHighlights"][0]["comment"])
        self.assertNotIn("userName", card["reviewHighlights"][0])

    async def test_review_outage_keeps_the_search_working(self):
        cards = await client(review_status=503).hydrate_products([{"productId": PRODUCT}], SearchFilters(), 5)
        self.assertEqual(cards[0]["name"], "Áo thun nam basic")
        self.assertIsNone(cards[0]["rating"])
        self.assertEqual(cards[0]["reviewHighlights"], [])


class ReviewPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_answer_model_and_advisor_see_the_reviews(self):
        card = (await client().hydrate_products([{"productId": PRODUCT}], SearchFilters(), 5))[0]
        sent = {}

        class Model:
            async def ainvoke(self, messages):
                sent["data"] = messages[-1].content

                class Reply:
                    text = "ok"
                return Reply()

        gateway = object.__new__(GeminiGateway)
        gateway.settings = AgenticSettings(**SETTINGS)
        gateway.llm = gateway.answer_llm = Model()
        await gateway.answer("áo nào được khen nhiều", {}, {}, [card], [])
        payload = json.loads(sent["data"].split("nhìn thấy]\n", 1)[1])
        described = payload["products"][0]
        self.assertEqual(described["rating"], 4.3)
        self.assertEqual(described["reviewCount"], 12)
        self.assertTrue(described["reviewHighlights"][0].startswith("5★"))
        self.assertEqual(_brief(card)["review_count"], 12)
        self.assertEqual(len(_full(card)["reviews"]), 2)

    async def test_answer_model_receives_the_shoppers_photo(self):
        sent = {}

        class Model:
            async def ainvoke(self, messages):
                sent["content"] = messages[-1].content

                class Reply:
                    text = "ok"
                return Reply()

        gateway = object.__new__(GeminiGateway)
        gateway.settings = AgenticSettings(**SETTINGS)
        gateway.llm = gateway.answer_llm = Model()
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 40).decode()
        await gateway.answer("giống ảnh này", {}, {}, [], [], image=png)
        self.assertEqual(sent["content"][1]["image_url"]["url"], f"data:image/png;base64,{png}")

    def test_review_question_is_left_to_the_answer_model(self):
        turn = SemanticTurn(
            tasks=[SemanticTask(intent="product_detail", requested_attributes=["reviews"])], confidence=0.9
        )
        state = {
            "semantic_turn": turn.model_dump(),
            "products": [{"id": PRODUCT, "name": "Áo", "variants": [{"id": "1" * 24, "name": "Đen / L"}]}],
            "message": "áo này đánh giá thế nào",
            "plan": {},
        }
        self.assertIsNone(ProductAgent._product_attribute_answer(state))
        self.assertEqual(ProductAgent._missing_attributes(["reviews"], {"specifications": []}), [])


if __name__ == "__main__":
    unittest.main()
