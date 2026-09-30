import base64
import io
import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from qdrant_client import AsyncQdrantClient

from src.agents.product import ProductAgent, RetrievalDecision
from src.agents.state import SearchPlan, explicit_price_limits
from src.core.settings import Settings
from src.infrastructure.clients import CatalogAPI, normalize_image
from src.main import ChatRequest, Sessions, app, compact_history, compact_session_products
from src.product.catalog import VectorCatalog, content_hash, eligible_cards
from src.product.indexer import CatalogIndexer
from src.product.rag import ProductRAG

PRODUCT_ID = "a" * 24
SECOND_ID = "b" * 24
VARIANT_ID = "c" * 24


def product(product_id=PRODUCT_ID):
    return {"_id": product_id, "name": "Áo cotton", "description": "Thoáng mát", "detail": "<p>Vải mềm</p>",
            "price": 200000, "quantity": 100, "shopId": "shop-1", "categoryId": "fashion",
            "moderationStatus": "approved", "images": [], "variants": []}


class CatalogTests(unittest.TestCase):
    def test_explicit_vietnamese_budgets(self):
        for message, cap in [("tai nghe dưới 500 nghìn đồng", 500000),
                             ("không quá 1,5 triệu", 1500000),
                             ("tối đa 500.000 đồng", 500000), ("dưới 500k", 500000)]:
            self.assertEqual(explicit_price_limits(message), {"max_price": cap})
        self.assertEqual(explicit_price_limits("áo size 40"), {})

    def test_live_inventory_wins_over_stale_product_quantity(self):
        self.assertEqual(eligible_cards([product()], {(PRODUCT_ID, ""): 0}, [PRODUCT_ID], {}), [])
        self.assertEqual(eligible_cards([product()], {}, [PRODUCT_ID], {}), [])

    def test_budget_applies_to_same_available_variant(self):
        item = product()
        item["variants"] = [
            {"_id": VARIANT_ID, "name": "Đen L", "price": 400000},
            {"_id": "d" * 24, "name": "Trắng M", "price": 100000},
        ]
        stock = {(PRODUCT_ID, VARIANT_ID): 1, (PRODUCT_ID, "d" * 24): 10}
        plan = {"max_price": 300000, "variant_terms": ["Đen", "L"]}
        self.assertEqual(eligible_cards([item], stock, [PRODUCT_ID], plan), [])
        plan["max_price"] = 500000
        cards = eligible_cards([item], stock, [PRODUCT_ID], plan)
        self.assertEqual(cards[0]["price"], 400000)
        self.assertEqual(cards[0]["variants"][0]["id"], VARIANT_ID)

    def test_moderation_reference_and_exact_variant_filtering(self):
        removed = {**product(), "moderationStatus": "removed"}
        stock = {(PRODUCT_ID, ""): 10}
        self.assertEqual(eligible_cards([removed], stock, [PRODUCT_ID], {}), [])
        self.assertEqual(eligible_cards([product()], stock, [PRODUCT_ID], {}, exclude=PRODUCT_ID), [])
        item = {**product(), "variants": [{"_id": VARIANT_ID, "name": "Đen XL", "price": 200000}]}
        self.assertEqual(eligible_cards([item], {(PRODUCT_ID, VARIANT_ID): 10}, [PRODUCT_ID],
                                        {"variant_terms": ["L"]}), [])

    def test_price_only_changes_do_not_reembed(self):
        original = product()
        changed = {**original, "price": 900000, "quantity": 0, "updatedAt": "new"}
        self.assertEqual(content_hash(original, 5), content_hash(changed, 5))
        self.assertNotEqual(content_hash(original, 5), content_hash({**changed, "detail": "new details"}, 5))

    def test_valid_image_and_invalid_content(self):
        output = io.BytesIO()
        Image.new("RGB", (32, 32), "red").save(output, "PNG")
        encoded = normalize_image(output.getvalue(), 5 * 1024 * 1024)
        self.assertTrue(base64.b64decode(encoded).startswith(b"\xff\xd8"))
        with self.assertRaises(ValueError):
            normalize_image(b"not an image", 100)
        with self.assertRaises(ValueError):
            normalize_image(b"a" * 101, 100)

    def test_sessions_are_isolated_expire_and_survive_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=directory)
            sessions = Sessions(settings)
            sessions.save("one", {"history": ["private"]})
            self.assertEqual(sessions.load(None), {})
            with self.assertRaises(HTTPException):
                sessions.load("two")
            sessions.db.close()
            sessions = Sessions(settings)
            self.assertEqual(sessions.load("one")["history"], ["private"])
            sessions.db.execute("UPDATE sessions SET expires=0")
            sessions.db.commit()
            with self.assertRaises(HTTPException):
                sessions.load("one")
            sessions.db.close()

    def test_session_context_fields_expire_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions = Sessions(Settings(data_dir=directory))
            sessions.save("one", {
                "history": [{"role": "user", "content": "tai nghe"}],
                "plan": {"query": "tai nghe"},
                "products": [{"id": PRODUCT_ID, "name": "Tai nghe"}],
                "visual_description": "Tai nghe màu đen",
                "image_vector": [1.0],
                "image_namespace": "images",
                "pending_action": {"type": "checkout_confirmation"},
                "_context_expires": {"visual": 0, "pending_action": 0, "shopping": time.time() + 60},
            })

            state = sessions.load("one")

            self.assertEqual(state["plan"]["query"], "tai nghe")
            self.assertNotIn("visual_description", state)
            self.assertNotIn("pending_action", state)
            sessions.db.close()

    def test_context_compaction_limits_history_and_product_payloads(self):
        with patch.dict(os.environ, {
            "CHATBOT_CONTEXT_HISTORY_MESSAGES": "2",
            "CHATBOT_CONTEXT_HISTORY_CHARS": "1000",
            "CHATBOT_SESSION_PRODUCT_LIMIT": "1",
        }):
            history = compact_history([
                {"role": "user", "content": "cũ"},
                {"role": "assistant", "content": "trả lời cũ"},
                {"role": "user", "content": "mới"},
            ])
            products = compact_session_products([{
                "id": PRODUCT_ID,
                "name": "Tai nghe",
                "price": 100000,
                "description": "x" * 5000,
                "variants": [{"id": VARIANT_ID}],
            }, {"id": SECOND_ID, "name": "Khác"}])

        self.assertEqual([item["content"] for item in history], ["trả lời cũ", "mới"])
        self.assertEqual(products, [{
            "id": PRODUCT_ID, "name": "Tai nghe", "price": 100000, "displayRank": 1,
        }])


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=self.temp.name, embedding_dimensions=3)
        self.vectors = VectorCatalog(self.settings, AsyncQdrantClient(location=":memory:"))
        self.api = AsyncMock()
        self.models = AsyncMock()
        self.models.embed_documents.side_effect = lambda texts: [[1.0, 0.0, 0.0] for _ in texts]
        self.models.embed_queries.side_effect = lambda texts: [[1.0, 0.0, 0.0] for _ in texts]
        self.api.all_products.return_value = [product()]
        self.indexer = CatalogIndexer(self.settings, self.api, self.models, self.vectors)

    async def asyncTearDown(self):
        self.indexer.db.close()
        await self.vectors.close()
        self.temp.cleanup()

    async def test_reconciliation_update_delete_and_rebuild(self):
        await self.indexer.reconcile()
        await self.indexer.reconcile()
        self.assertEqual(await self.vectors.product_ids(), {PRODUCT_ID})
        self.api.all_products.return_value = [{**product(), "description": "Nội dung mới"}]
        await self.indexer.reconcile()
        hits = await self.vectors.query([1.0, 0.0, 0.0])
        self.assertIn("Nội dung mới", hits[0].payload["text"])
        await self.vectors.client.delete_collection(self.settings.collection)
        await self.indexer.reconcile()
        self.api.all_products.return_value = []
        await self.indexer.reconcile()
        self.assertEqual(await self.vectors.product_ids(), set())

    async def test_failed_catalog_scan_preserves_index(self):
        await self.indexer.reconcile()
        self.api.all_products.side_effect = RuntimeError("page 2 unavailable")
        with self.assertRaises(RuntimeError):
            await self.indexer.reconcile()
        self.assertEqual(await self.vectors.product_ids(), {PRODUCT_ID})

    async def test_image_caption_cache_and_stale_point_cleanup(self):
        item = {**product(), "images": ["/uploads/a.png", "/uploads/b.png"]}
        self.api.all_products.return_value = [item]
        self.api.image.side_effect = lambda url: "bytes:" + url
        self.models.describe.return_value = "Áo đỏ cổ tròn"
        await self.indexer.reconcile()
        self.api.all_products.return_value = [{**item, "images": ["/uploads/b.png"]}]
        await self.indexer.reconcile()
        self.assertEqual((await self.vectors.client.count(self.settings.collection)).count, 2)
        self.assertEqual(self.models.describe.await_count, 2)

    async def test_zero_caption_limit_embeds_text_without_describing_images(self):
        settings = Settings(data_dir=self.temp.name, embedding_dimensions=3, max_caption_images=0)
        indexer = CatalogIndexer(settings, self.api, self.models, self.vectors)
        try:
            item = {**product(), "images": ["https://salt.tikicdn.com/product.jpg"]}
            self.api.product.return_value = item
            result = await indexer.process_events([("product.updated", PRODUCT_ID)])
            self.assertEqual(result["updated"], 1)
            self.api.image.assert_not_awaited()
            self.models.describe.assert_not_awaited()
            self.assertEqual(len(self.models.embed_documents.await_args.args[0]), 1)
        finally:
            indexer.db.close()

    async def test_product_events_batch_only_changed_products(self):
        products = {PRODUCT_ID: product(), SECOND_ID: product(SECOND_ID)}
        self.api.product.side_effect = lambda product_id: products.get(product_id)

        result = await self.indexer.process_events([
            ("product.created", PRODUCT_ID),
            ("product.created", SECOND_ID),
        ])
        self.assertEqual(result["updated"], 2)
        self.assertEqual(self.models.embed_documents.await_count, 1)
        self.assertEqual(len(self.models.embed_documents.await_args.args[0]), 2)

        await self.indexer.process_events([
            ("product.created", PRODUCT_ID),
            ("product.updated", SECOND_ID),
        ])
        self.assertEqual(self.models.embed_documents.await_count, 1)

        products[PRODUCT_ID] = {**product(), "description": "changed"}
        await self.indexer.process_events([("product.updated", PRODUCT_ID)])
        self.assertEqual(self.models.embed_documents.await_count, 2)
        self.assertEqual(len(self.models.embed_documents.await_args.args[0]), 1)

        await self.indexer.process_events([("product.deleted", PRODUCT_ID)])
        self.assertEqual(await self.vectors.product_ids(), {SECOND_ID})

    async def test_product_agent_filters_before_generation(self):
        await self.indexer.reconcile()
        self.models.structured.return_value = RetrievalDecision(
            action="accept", answer="Áo cotton này phù hợp ngân sách.", product_ids=[PRODUCT_ID]
        )
        self.api.fresh.return_value = ([product()], {(PRODUCT_ID, ""): 2})
        result = await ProductAgent(
            self.api, self.models, self.vectors, use_llm_evaluator=True
        ).graph.ainvoke(
            {"message": "Áo dưới 300k", "history": []})
        self.assertEqual(result["products"][0]["id"], PRODUCT_ID)
        self.assertEqual(result["answer"], "Áo cotton này phù hợp ngân sách.")

    async def test_image_description_and_new_topic_clear_visual_context(self):
        self.models.describe.return_value = "Áo đỏ cổ tròn"
        agent = ProductAgent(self.api, self.models, self.vectors)
        state = await agent.understand({"message": "tìm mẫu này màu đỏ", "image": "image-bytes"})
        self.assertEqual(state["visual_description"], "Áo đỏ cổ tròn")
        state = await agent.understand({"message": "giờ tìm laptop", "visual_description": "Áo đỏ cổ tròn"})
        self.assertEqual(state["visual_description"], "")

    async def test_followup_uses_only_known_product_reference(self):
        agent = ProductAgent(self.api, self.models, self.vectors)
        state = await agent.understand(
            {"message": "cái thứ hai", "previous_products": [{"id": SECOND_ID, "name": "Áo"}]})
        self.assertEqual(state["plan"]["reference_product_id"], SECOND_ID)
        state = await agent.understand({"message": "cái thứ hai", "previous_products": []})
        self.assertEqual(state["plan"]["intent"], "clarify")

    async def test_similar_retrieval_excludes_source(self):
        self.api.all_products.return_value = [product(), product(SECOND_ID)]
        await self.indexer.reconcile()
        self.api.product.return_value = product()
        self.api.fresh.return_value = (
            [product(), product(SECOND_ID)], {(PRODUCT_ID, ""): 10, (SECOND_ID, ""): 10})
        result = await ProductRAG(self.api, self.models, self.vectors).chain.ainvoke({
            "message": "Tương tự",
            "plan": SearchPlan(intent="similar", reference_product_id=PRODUCT_ID).model_dump(),
        })
        self.assertEqual([item["id"] for item in result["products"]], [SECOND_ID])

    async def test_image_host_restrictions(self):
        api = CatalogAPI(self.settings)
        with self.assertRaises(ValueError):
            await api.image("http://169.254.169.254/latest/meta-data")
        await api.close()


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        settings = Settings(data_dir=self.temp.name, gemini_api_key="test")
        self.patcher = patch("src.main.Settings", return_value=settings)
        self.patcher.start()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.patcher.stop()
        self.temp.cleanup()

    def test_validation_and_unknown_session(self):
        self.assertEqual(self.client.post("/assistant/chat", json={}).status_code, 422)
        self.assertEqual(self.client.post("/assistant/chat", json={"message": "hello", "sessionId": "x" * 43}).status_code, 410)
        self.assertEqual(self.client.post("/assistant/chat", json={"image": "not base64!"}).status_code, 400)
        self.assertEqual(self.client.get("/assistant/products/invalid/similar").status_code, 422)

    def test_cart_action_tokens_are_valid_confirmation_ids(self):
        token = "cart_action:AbCdEfGhIjKlMnOp"
        self.assertEqual(ChatRequest(confirmActionId=token).confirmActionId, token)
        self.assertEqual(ChatRequest(cancelActionId=token).cancelActionId, token)

    def test_chat_session_reuse_and_no_shared_history(self):
        graph = AsyncMock()
        graph.ainvoke.return_value = {"answer": "Xin chào", "products": [], "plan": {"intent": "clarify"}}
        app.state.agent.graph = graph
        one = self.client.post("/assistant/chat", json={"message": "Chào"}).json()
        two = self.client.post("/assistant/chat", json={"message": "Mua áo", "sessionId": one["sessionId"]}).json()
        self.assertEqual(one["sessionId"], two["sessionId"])
        self.assertEqual(len(graph.ainvoke.call_args.args[0]["history"]), 2)
        self.client.post("/assistant/chat", json={"message": "Khách khác"})
        self.assertEqual(graph.ainvoke.call_args.args[0]["history"], [])

    def test_dependency_failure_does_not_save_failed_turn(self):
        app.state.agent.graph = AsyncMock()
        app.state.agent.graph.ainvoke.side_effect = httpx.ConnectError("gemini down")
        result = self.client.post("/assistant/chat", json={"message": "Mua áo"})
        self.assertEqual(result.status_code, 503)
        self.assertEqual(app.state.active_requests, 0)
        self.assertEqual(app.state.busy_sessions, set())
        with sqlite3.connect(self.temp.name + "/sessions.sqlite") as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)

    def test_named_product_focus_and_card_fields_survive_followups(self):
        graph = AsyncMock()

        async def invoke(state):
            if state["message"] == "sách thiếu nhi":
                return {
                    "answer": "Gợi ý",
                    "products": [
                        {"id": PRODUCT_ID, "name": "I Love Christmas", "price": 191500, "imageUrl": "a.jpg", "variants": []},
                        {"id": SECOND_ID, "name": "I Love My Monster", "price": 209000, "imageUrl": "b.jpg", "variants": []},
                    ],
                    "plan": {"intent": "search"},
                }
            if state["message"].startswith("Love Christmas"):
                return {
                    "answer": "Chi tiết",
                    "products": state["previous_products"],
                    "plan": {"intent": "clarify"},
                }
            return {"answer": "Chi tiết", "products": [], "plan": {"intent": "clarify"}}

        graph.ainvoke.side_effect = invoke
        app.state.agent.graph = graph
        first = self.client.post("/assistant/chat", json={"message": "sách thiếu nhi"}).json()
        self.client.post("/assistant/chat", json={
            "message": "Love Christmas nói về gì",
            "sessionId": first["sessionId"],
        })
        self.client.post("/assistant/chat", json={
            "message": "thêm vào giỏ",
            "sessionId": first["sessionId"],
        })

        followup_state = graph.ainvoke.await_args_list[1].args[0]
        action_state = graph.ainvoke.await_args_list[2].args[0]
        self.assertEqual(followup_state["previous_products"][0]["price"], 191500)
        self.assertEqual(followup_state["previous_products"][0]["displayRank"], 1)
        self.assertNotIn("variants", followup_state["previous_products"][0])
        self.assertEqual(followup_state["focused_product_id"], PRODUCT_ID)
        self.assertEqual(action_state["focused_product_id"], PRODUCT_ID)


if __name__ == "__main__":
    unittest.main()
