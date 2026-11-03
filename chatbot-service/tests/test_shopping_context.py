"""Regression coverage for multi-turn shopping constraints and numeric sock sizes."""
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from qdrant_client import AsyncQdrantClient, models as qmodels

from src.agents.product import ProductAgent, RetrievalDecision, _explicit_variant_terms
from src.agents.clothing_size import ClothingSizeEstimate, SIZE_DISCLAIMER
from src.agents.conversation import MarketplaceTurn
from src.agents.intent import TurnIntent
from src.agents.state import SearchPlan
from src.core.settings import Settings
from src.product.catalog import VectorCatalog, eligible_cards, infer_product_type, offer_fits_foot, query_metadata
from src.main import app


def item(pid, name, variant):
    return {"_id": pid, "name": name, "moderationStatus": "approved", "price": 97000,
            "variants": [{"_id": "v", "name": variant, "price": 97000}]}


class ShoppingContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.agent = ProductAgent(AsyncMock(), AsyncMock(), AsyncMock())

    async def conversation(self, messages, previous=None):
        plans = []
        for message in messages:
            result = await self.agent.understand({"message": message, "previous_plan": previous or {}})
            previous = result["plan"]
            plans.append(previous)
        return plans

    async def test_sock_size_and_correction_keep_all_requirements(self):
        for length in (24, 29):
            with self.subTest(length=length):
                plans = await self.conversation([
                    "tất nam trắng", "size nào phù hợp với tôi", f"chân tôi {length} cm",
                    "nhưng tôi đang hỏi tất mà", "nhưng tôi là nam",
                ])
                for plan in plans:
                    self.assertEqual(plan["product_type"], "tat")
                    self.assertEqual(plan["audience"], "nam")
                    self.assertEqual(plan["variant_terms"], ["trắng"])
                self.assertEqual(plans[-1]["foot_length_cm"], length)
                self.assertEqual(plans[-1]["dialogue_act"], "size_advice")
                self.assertNotIn(str(length), plans[2]["query"])

    async def test_incremental_sock_request_and_english_size_question(self):
        plans = await self.conversation([
            "tôi muốn mua tất", "tất nam", "tất trắng", "how do I know sock size?", "tôi đo được 24cm",
        ])
        self.assertEqual(plans[-1]["audience"], "nam")
        self.assertEqual(plans[-1]["variant_terms"], ["trắng"])
        self.assertEqual(plans[-1]["foot_length_cm"], 24)
        self.assertEqual(plans[-1]["product_type"], "tat")

    async def test_shirt_measurements_stay_on_white_womens_shirts(self):
        plans = await self.conversation([
            "áo sơ mi nữ", "màu trắng", "size nào phù hợp với tôi", "tôi cao 1m6, nặng 50kg", "vòng ngực 85cm",
        ])
        for plan in plans:
            self.assertEqual(plan["product_type"], "ao_so_mi")
            self.assertEqual(plan["audience"], "nu")
        plan = plans[-1]
        self.assertEqual(plan["height_cm"], 160)
        self.assertEqual(plan["weight_kg"], 50)
        self.assertEqual(plan["bust_cm"], 85)
        self.assertIsNone(plan["foot_length_cm"])
        self.assertEqual(plan["variant_terms"], ["trắng"])
        self.assertEqual(plan["query"], "áo sơ mi nữ; màu trắng")
        self.assertEqual(query_metadata(plan)["product_type"], "ao_so_mi")

    async def test_explicit_replacements_and_new_topic(self):
        plans = await self.conversation([
            "tất nam trắng dưới 200k", "chân tôi 29 cm", "chân tôi 26cm",
            "màu đen", "không phải nam, tôi là nữ", "giờ tìm tai nghe bluetooth",
        ])
        self.assertEqual(plans[2]["foot_length_cm"], 26)
        self.assertEqual(plans[3]["variant_terms"], ["đen"])
        self.assertNotIn("trắng", plans[3]["query"])
        self.assertEqual(query_metadata(plans[4])["audiences"], ["nu", "unisex"])
        self.assertEqual(plans[4]["max_price"], 200000)
        self.assertEqual(plans[-1]["product_type"], "tai_nghe")
        for key in ("foot_length_cm", "height_cm", "weight_kg", "audience", "max_price"):
            self.assertIsNone(plans[-1][key])
        self.assertEqual(plans[-1]["variant_terms"], [])

    async def test_legacy_checkpoint_gets_structured_requirements(self):
        plans = await self.conversation(["chân tôi 29cm"], SearchPlan(query="tất nam trắng", variant_terms=["trắng"]).model_dump())
        self.assertEqual(plans[0]["product_type"], "tat")
        self.assertEqual(plans[0]["audience"], "nam")
        self.assertEqual(plans[0]["foot_length_cm"], 29)

    async def test_new_image_and_unknown_product_clear_old_requirements(self):
        previous = (await self.conversation(["tất nam trắng", "chân tôi 29cm"]))[-1]
        unknown = (await self.conversation(["tìm máy pha cà phê"], previous))[-1]
        self.assertIsNone(unknown["product_type"])
        self.assertEqual(unknown["variant_terms"], [])
        self.agent.models.describe.return_value = "Áo sơ mi"
        image = await self.agent.understand({"message": "màu đen", "image": "bytes", "previous_plan": previous})
        self.assertIsNone(image["plan"]["foot_length_cm"])
        self.assertIsNone(image["plan"]["audience"])

    async def test_real_graph_filters_wrong_categories_and_does_not_guess_size(self):
        products = [item("a", "Áo sơ mi nữ", "Trắng / M"), item("b", "Quần nữ", "Trắng / M 40-50kg"),
                    item("c", "Áo sơ mi nam", "Trắng / M"), item("d", "Áo sơ mi nữ", "Đen / M")]
        self.agent.api.fresh.return_value = (products, {(p["_id"], "v"): 5 for p in products})
        self.agent.api.review_summaries.return_value = {"items": []}
        self.agent.models.embed_queries.return_value = [[1., 0., 0.]]
        self.agent.vectors.query.return_value = [SimpleNamespace(payload={"productId": p["_id"]}) for p in products]
        self.agent.models.structured.return_value = RetrievalDecision(action="accept", product_ids=["a"], answer="Cần đối chiếu bảng size của mẫu áo sơ mi.")
        previous = (await self.conversation(["áo sơ mi nữ", "màu trắng", "size nào phù hợp với tôi"]))[-1]
        result = await self.agent.graph.ainvoke({"message": "tôi cao 1m6, nặng 50kg", "previous_plan": previous})
        self.assertEqual(result["products"], [])
        self.assertIn("sản phẩm cụ thể", result["answer"])
        self.assertEqual(result["plan"]["height_cm"], 160)
        self.agent.models.structured.assert_not_awaited()
        cards = await self.agent.rag._fresh_cards([p["_id"] for p in products], result["plan"])
        self.assertEqual([p["id"] for p in cards], ["a"])

    async def test_no_size_match_does_not_offer_slippers_or_womens_socks(self):
        products = [item("a", "Tất nam", "Trắng / 25-27cm"), item("b", "Tất nữ", "Trắng / 23-25cm"),
                    item("c", "Dép nam", "Trắng / 24cm")]
        self.agent.api.fresh.return_value = (products, {(p["_id"], "v"): 5 for p in products})
        self.agent.models.embed_queries.return_value = [[1., 0., 0.]]
        self.agent.vectors.query.return_value = [SimpleNamespace(payload={"productId": p["_id"]}) for p in products]
        previous = (await self.conversation(["tất nam trắng", "size nào phù hợp với tôi"]))[-1]
        for length in (24, 29):
            result = await self.agent.graph.ainvoke({"message": f"chân tôi {length} cm", "previous_plan": previous})
            self.assertEqual(result["products"], [])
            self.assertIn(f"{length}cm", result["answer"])
            self.assertIn("tất nam trắng", result["answer"])
        fitted = await self.agent.graph.ainvoke({"message": "chân tôi 26cm", "previous_plan": previous})
        self.assertEqual([p["id"] for p in fitted["products"]], ["a"])
        self.assertIn("26cm", fitted["answer"])
        self.agent.models.structured.assert_not_awaited()

    async def test_existing_qdrant_sock_payloads_remain_searchable(self):
        client = AsyncQdrantClient(":memory:")
        catalog = VectorCatalog(Settings(embedding_dimensions=3), client=client)
        try:
            await catalog.ensure(3)
            await catalog.upsert([qmodels.PointStruct(id=i, vector=[1., 0., 0.], payload={
                "productId": str(i), "productType": kind, "kind": "text",
            }) for i, kind in enumerate(("khac", "tat", "giay"), 1)])
            hits = await catalog.query([1., 0., 0.], metadata={"product_type": "tat"})
            self.assertEqual({h.payload["productType"] for h in hits}, {"khac", "tat"})
        finally:
            await client.close()


class SizeAndColorTests(unittest.TestCase):
    def test_cm_range_containment_and_unknown_sizes(self):
        for name, length, expected in [
            ("Trắng / 25-27cm", 26, True), ("Trắng / 25-27cm", 24, False),
            ("Trắng / 25-27cm", 29, False), ("Trắng / 25–27 cm", 27, True),
            ("Trắng / 23.5-25cm", 24, True), ("Trắng / 24.0cm", 24, True),
            ("Trắng / 38-40", 24, False), ("Trắng / free size", 24, False),
        ]:
            with self.subTest(name=name, length=length):
                self.assertEqual(offer_fits_foot({"name": name}, length), expected)

    def test_same_variant_must_match_color_stock_and_size(self):
        product = item("a", "Tất nam", "Trắng / 25-27cm")
        product["variants"] += [{"_id": "black", "name": "Đen / 23-25cm", "price": 97000}]
        stock = {("a", "v"): 5, ("a", "black"): 5}
        plan = {"product_type": "tat", "audience": "nam", "variant_terms": ["trắng"], "foot_length_cm": 24}
        self.assertEqual(eligible_cards([product], stock, ["a"], plan), [])
        plan["foot_length_cm"] = 26
        self.assertEqual(eligible_cards([product], stock, ["a"], plan)[0]["variants"][0]["id"], "v")

    def test_measurement_verbs_are_not_red(self):
        self.assertEqual(_explicit_variant_terms("how do I know sock size?"), [])
        self.assertEqual(_explicit_variant_terms("tôi đo được 24cm"), [])
        self.assertEqual(_explicit_variant_terms("màu đỏ"), ["đỏ"])
        self.assertEqual(infer_product_type("tất cả sản phẩm"), "khac")
        self.assertEqual(infer_product_type("tìm dép"), "giay")
        self.assertEqual(infer_product_type("vỏ điện thoại"), "dien_thoai")


class ShoppingCheckpointTests(unittest.TestCase):
    def test_size_clarification_survives_restart_and_isolated_session(self):
        api, models, vectors = AsyncMock(), AsyncMock(), AsyncMock()
        pid = "a" * 24
        api.fresh.return_value = ([item(pid, "Áo sơ mi nữ", "Trắng / M")], {(pid, "v"): 5})
        api.product.return_value = item(pid, "Áo sơ mi nữ", "Trắng / M")
        api.review_summaries.return_value = {"items": []}
        models.embed_queries.return_value = [[1., 0., 0.]]
        vectors.query.return_value = [SimpleNamespace(payload={"productId": pid})]

        async def answer(messages, schema):
            if schema is ClothingSizeEstimate:
                return ClothingSizeEstimate(size="S–M", reasoning="Đây là ước lượng theo vóc dáng.")
            request = json.loads(messages[1]["content"])
            if request["untrusted_user_request"] == "size nào phù hợp với tôi":
                return RetrievalDecision(action="clarify", clarification="Bạn cho biết chiều cao và cân nặng nhé.")
            return RetrievalDecision(action="accept", product_ids=[pid], answer="Áo sơ mi nữ màu trắng.")

        models.structured.side_effect = answer
        models.understand_intent.return_value = TurnIntent()

        def interpret(payload):
            message = payload["untrusted_message"]
            if message == "áo sơ mi nữ":
                return MarketplaceTurn(operation="new_search", subject="áo sơ mi", audience="nu")
            if message == "màu trắng":
                return MarketplaceTurn(operation="refine", variant_terms=["trắng"])
            if message == "size nào phù hợp với tôi":
                return MarketplaceTurn(operation="ask_product", selected_product_ids=[pid], needs_fit=True)
            if message == "tôi cao 1m6, nặng 50kg":
                return MarketplaceTurn(operation="provide_details", buyer={"height_cm": 160, "weight_kg": 50})
            return MarketplaceTurn(operation="new_search")

        models.interpret_turn.side_effect = interpret
        with tempfile.TemporaryDirectory() as temp, \
                patch("src.main.Settings", return_value=Settings(data_dir=temp, gemini_api_key="test")), \
                patch("src.main.CatalogAPI", return_value=api), \
                patch("src.main.ModelClients", return_value=models), \
                patch("src.main.VectorCatalog", return_value=vectors):
            with TestClient(app) as client:
                sid = None
                for message in ("áo sơ mi nữ", "màu trắng", "size nào phù hợp với tôi"):
                    response = client.post("/assistant/chat", json={"message": message, "sessionId": sid})
                    self.assertEqual(response.status_code, 200, response.text)
                    sid = response.json()["sessionId"]
                self.assertEqual(response.json()["products"], [])
            with TestClient(app) as client:
                response = client.post("/assistant/chat", json={"message": "tôi cao 1m6, nặng 50kg", "sessionId": sid})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn(SIZE_DISCLAIMER, response.json()["answer"])
                snapshot = client.portal.call(app.state.agent.graph.aget_state, {"configurable": {"thread_id": sid}})
                plan = snapshot.values["plan"]
                self.assertEqual((plan["product_type"], plan["audience"], plan["variant_terms"]), ("ao_so_mi", "nu", ["trắng"]))
                self.assertEqual((plan["height_cm"], plan["weight_kg"]), (160, 50))
                other = client.post("/assistant/chat", json={"message": "hello"}).json()
                other_state = client.portal.call(app.state.agent.graph.aget_state, {"configurable": {"thread_id": other["sessionId"]}})
                self.assertIsNone(other_state.values["plan"]["product_type"])
                self.assertIsNone(other_state.values["plan"]["height_cm"])
