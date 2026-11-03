import base64
import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from PIL import Image
from qdrant_client import AsyncQdrantClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from src.agents.product import ProductAgent, ProductState, RetrievalDecision
from src.agents.order import OrderAgent
from src.agents.router import RouterAgent
from src.agents.state import ChatState, SearchPlan, explicit_price_limits
from src.core.settings import Settings
from src.infrastructure.clients import CatalogAPI, normalize_image
from src.main import (ChatRequest, app, compact_history, compact_session_products,
                      latest_committed_state, prune_context, purge_expired_checkpoints)
from src.product.catalog import (VectorCatalog, content_hash, eligible_cards, infer_product_type,
                                 product_documents, variant_metadata)
from src.product.indexer import CatalogIndexer
from src.product.rag import ProductRAG

PRODUCT_ID = "a" * 24
SECOND_ID = "b" * 24
VARIANT_ID = "c" * 24


def product(product_id=PRODUCT_ID):
    return {"_id": product_id, "name": "Áo cotton", "description": "Thoáng mát", "detail": "<p>Vải mềm</p>",
            "price": 200000, "quantity": 100, "shopId": "shop-1", "categoryId": "fashion",
            "moderationStatus": "approved", "images": [], "variants": []}


def stub_graph(handler):
    """Keep endpoint tests focused on their API contract while emulating thread state."""
    graph = AsyncMock()
    checkpoints = {}

    async def get_state(config):
        return SimpleNamespace(values=checkpoints.get(config["configurable"]["thread_id"], {}),
                               config=config, parent_config=None)

    async def invoke(state, config=None, **kwargs):
        result = await handler(state)
        thread_id = config["configurable"]["thread_id"]
        checkpoints[thread_id] = {**checkpoints.get(thread_id, {}), **state, **result}
        return result

    async def update_state(config, update):
        checkpoints[config["configurable"]["thread_id"]].update(update)

    graph.aget_state.side_effect = get_state
    graph.ainvoke.side_effect = invoke
    graph.aupdate_state.side_effect = update_state
    return graph, checkpoints


class CatalogTests(unittest.TestCase):
    def test_model_number_is_not_treated_as_a_bare_size(self):
        item = {**product(), "name": "Điện thoại", "variants": [
            {"_id": "phone-15", "name": "iPhone 15", "price": 10000000},
        ]}
        self.assertEqual(variant_metadata(item["variants"][0], item)["sizes"], [])
        self.assertIn("iPhone 15", product_documents(item)[1][1].page_content)

    def test_product_type_keeps_ba_lo_distinct_from_ba_lo_shirt(self):
        self.assertEqual(infer_product_type("Ba Lô laptop nam"), "balo")
        self.assertEqual(infer_product_type("Áo ba lỗ nam"), "khac")

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

    def test_context_fields_expire_independently(self):
        state = prune_context({
            "history": [{"role": "user", "content": "tai nghe"}],
            "plan": {"query": "tai nghe"},
            "remembered_products": [{"id": PRODUCT_ID, "name": "Tai nghe"}],
            "visual_description": "Tai nghe màu đen",
            "image_vector": [1.0],
            "image_namespace": "images",
            "pending_action": {"type": "checkout_confirmation"},
            "_context_expires": {"visual": 0, "pending_action": 0, "shopping": time.time() + 60},
        }, time.time())
        self.assertEqual(state["plan"]["query"], "tai nghe")
        self.assertEqual(state["remembered_products"][0]["id"], PRODUCT_ID)
        self.assertEqual(state["visual_description"], "")
        self.assertIsNone(state["pending_action"])

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


class CheckpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_order_details_stay_out_of_checkpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "checkpoints.sqlite")
            config = {"configurable": {"thread_id": "owned-order"}}
            child = StateGraph(ProductState)
            child.add_node("answer", lambda state: {"answer": "ok"})
            child.add_edge(START, "answer")
            child.add_edge("answer", END)
            commerce = AsyncMock()
            commerce.user_orders.return_value = [{
                "id": 79, "status": "pending_payment",
                "products": [{"name": "PRIVATE_ORDER_ITEM"}],
            }]
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                from src.agents.intent import TurnIntent
                product = SimpleNamespace(
                    graph=child.compile(),
                    models=SimpleNamespace(understand_intent=AsyncMock(return_value=TurnIntent(route="order"))),
                )
                router = RouterAgent(product,
                                     order_agent=OrderAgent(commerce), checkpointer=saver)
                result = await router.graph.ainvoke({
                    "message": "don 79", "authenticated_user_id": "buyer-one",
                    "actor_role": "buyer",
                }, config=config, durability="exit")
                self.assertIn("79", result["answer"])
                for checkpoint in [item async for item in saver.alist(None)]:
                    values = checkpoint.checkpoint.get("channel_values", {})
                    self.assertNotIn("order_context", values)
                    self.assertNotIn("order_list", values)
                    self.assertNotIn("answer", values)

    async def test_expired_checkpoint_is_deleted_without_touching_active_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "checkpoints.sqlite")
            builder = StateGraph(ChatState)
            builder.add_node("answer", lambda state: {"answer": "ok"})
            builder.add_edge(START, "answer")
            builder.add_edge("answer", END)
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                graph = builder.compile(checkpointer=saver)
                for thread_id in ("expired", "busy"):
                    config = {"configurable": {"thread_id": thread_id}}
                    await graph.ainvoke({"message": "hi"}, config=config, durability="exit")
                    await graph.aupdate_state(config, {
                        "turn_committed": True, "session_expires_at": 0,
                    })
                await purge_expired_checkpoints(graph, saver, {"busy"}, time.time())
                self.assertFalse((await graph.aget_state({
                    "configurable": {"thread_id": "expired"}
                })).values)
                self.assertTrue((await graph.aget_state({
                    "configurable": {"thread_id": "busy"}
                })).values)

    async def test_nested_product_graph_keeps_image_out_of_all_checkpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "checkpoints.sqlite")
            config = {"configurable": {"thread_id": "image-search"}}
            child = StateGraph(ProductState)

            child.add_node("retrieve", lambda state: {
                "products": [{"id": PRODUCT_ID, "detail": "PRIVATE"}],
            })

            def answer(state):
                self.assertEqual(state["image"], "RAW_IMAGE_SECRET")
                self.assertEqual(state["products"][0]["id"], PRODUCT_ID)
                return {"answer": "ok"}

            child.add_node("answer", answer)
            child.add_edge(START, "retrieve")
            child.add_edge("retrieve", "answer")
            child.add_edge("answer", END)
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                router = RouterAgent(SimpleNamespace(graph=child.compile()), checkpointer=saver)
                await router.graph.ainvoke({"message": "find image", "image": "RAW_IMAGE_SECRET"},
                                           config=config, durability="exit")
                checkpoints = [item async for item in saver.alist(None)]
                self.assertTrue(checkpoints)
                for checkpoint in checkpoints:
                    self.assertNotIn("image", checkpoint.checkpoint.get("channel_values", {}))
                    self.assertNotIn("products", checkpoint.checkpoint.get("channel_values", {}))

    async def test_state_survives_reopen_without_checkpointing_raw_image(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "checkpoints.sqlite")
            config = {"configurable": {"thread_id": "buyer-conversation"}}
            builder = StateGraph(ChatState)
            builder.add_node("answer", lambda state: {
                "answer": "Đã tìm thấy áo", "history": [{"role": "user", "content": state["message"]}],
            })
            builder.add_edge(START, "answer")
            builder.add_edge("answer", END)
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                graph = builder.compile(checkpointer=saver)
                await graph.ainvoke({"message": "tìm áo", "image": "RAW_IMAGE_SECRET"},
                                    config=config, durability="exit")
                snapshot = await graph.aget_state(config)
                self.assertEqual(snapshot.values["history"][0]["content"], "tìm áo")
                self.assertNotIn("image", snapshot.values)
                self.assertNotIn("answer", snapshot.values)
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                graph = builder.compile(checkpointer=saver)
                snapshot = await graph.aget_state(config)
                self.assertNotIn("answer", snapshot.values)
                self.assertNotIn("image", snapshot.values)

    async def test_failed_exit_does_not_replace_last_successful_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "checkpoints.sqlite")
            config = {"configurable": {"thread_id": "buyer-conversation"}}
            builder = StateGraph(ChatState)

            def answer(state):
                if state["message"] == "fail":
                    raise RuntimeError("dependency failed")
                return {"answer": "ok"}

            builder.add_node("answer", answer)
            builder.add_edge(START, "answer")
            builder.add_edge("answer", END)
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                graph = builder.compile(checkpointer=saver)
                await graph.ainvoke({"message": "works"}, config=config, durability="exit")
                await graph.aupdate_state(config, {"turn_committed": True})
                with self.assertRaises(RuntimeError):
                    await graph.ainvoke({"message": "fail", "turn_committed": False},
                                        config=config, durability="exit")
                snapshot = await latest_committed_state(graph, config)
                self.assertEqual(snapshot.values["message"], "works")
                self.assertNotIn("answer", snapshot.values)
                await graph.ainvoke({"message": "retry", "turn_committed": False},
                                    config=snapshot.config, durability="exit")
                await graph.aupdate_state(config, {"turn_committed": True})
                self.assertEqual((await latest_committed_state(graph, config)).values["message"],
                                 "retry")


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
        points, _ = await self.vectors.client.scroll(self.settings.collection, with_payload=True,
                                                     with_vectors=False, limit=20)
        base = next(point for point in points if point.payload["chunkType"] == "base")
        self.assertIn("Nội dung mới", base.payload["text"])
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

        products[SECOND_ID] = {**products[SECOND_ID], "price": 350000}
        result = await self.indexer.process_events([("product.updated", SECOND_ID)])
        self.assertEqual(result["metadataUpdated"], 1)
        self.assertEqual(self.models.embed_documents.await_count, 2)

        await self.indexer.process_events([("product.deleted", PRODUCT_ID)])
        self.assertEqual(await self.vectors.product_ids(), {SECOND_ID})

    async def test_color_groups_share_vectors_across_sizes_and_refresh_metadata(self):
        item = {**product(), "name": "Áo thun nam", "variants": [
            {"_id": "black-l", "name": "Đen / L", "price": 250000},
            {"_id": "black-xl", "name": "Đen / XL", "price": 300000},
            {"_id": "white-m", "name": "Trắng / M", "price": 200000},
        ]}
        self.api.product.return_value = item
        await self.indexer.process_events([("product.created", PRODUCT_ID)])
        self.assertEqual(len(self.models.embed_documents.await_args.args[0]), 3)

        async def payloads():
            points, _ = await self.vectors.client.scroll(
                self.settings.collection, with_payload=True, with_vectors=False, limit=20)
            return [point.payload for point in points]

        initial = await payloads()
        self.assertEqual({p["chunkType"] for p in initial}, {"base", "variant_group"})
        black = next(p for p in initial if p.get("variantGroup") == "den")
        self.assertEqual(black["sizes"], ["L", "XL"])
        self.assertEqual(set(black["variantIds"]), {"black-l", "black-xl"})
        self.assertEqual((black["minPrice"], black["maxPrice"]), (250000, 300000))
        matches = await self.vectors.query(
            [1.0, 0.0, 0.0], kind="text",
            metadata={"product_type": "ao_thun", "colors": ["den"], "sizes": ["XL"]})
        self.assertEqual([point.payload.get("variantGroup") for point in matches], ["den"])
        no_match = await self.vectors.query(
            [1.0, 0.0, 0.0], kind="text", metadata={"colors": ["trang"], "sizes": ["XL"]})
        self.assertEqual(no_match, [])

        item["variants"].append({"_id": "black-xxl", "name": "Đen / XXL", "price": 350000})
        self.assertEqual(content_hash(item, self.settings.max_images),
                         content_hash({**item, "variants": item["variants"][:-1]},
                                      self.settings.max_images))
        result = await self.indexer.process_events([("product.updated", PRODUCT_ID)])
        self.assertEqual(result["metadataUpdated"], 1)
        self.assertEqual(self.models.embed_documents.await_count, 1)
        black = next(p for p in await payloads() if p.get("variantGroup") == "den")
        self.assertEqual(black["sizes"], ["L", "XL", "XXL"])
        self.assertEqual(black["maxPrice"], 350000)
        self.assertEqual(set(black["variantIds"]), {"black-l", "black-xl", "black-xxl"})
        matches = await self.vectors.query(
            [1.0, 0.0, 0.0], kind="text", metadata={"colors": ["den"], "sizes": ["XXL"]})
        self.assertEqual([point.payload.get("variantGroup") for point in matches], ["den"])

        item["variants"] = item["variants"][:-2] + item["variants"][-1:]
        await self.indexer.process_events([("product.updated", PRODUCT_ID)])
        self.assertEqual(self.models.embed_documents.await_count, 2)
        self.assertEqual(len(await payloads()), 2)

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

    def test_checkpoint_restores_conversation_after_service_restart(self):
        first = self.client.post("/assistant/chat", json={"message": "chao"})
        self.assertEqual(first.status_code, 200)
        session_id = first.json()["sessionId"]
        self.client.__exit__(None, None, None)
        self.client = TestClient(app)
        self.client.__enter__()
        from src.agents.intent import TurnIntent
        app.state.agent.product_agent.models.understand_intent = AsyncMock(
            return_value=TurnIntent(route="order"),
        )
        second = self.client.post("/assistant/chat", json={
            "message": "don hang cua toi o dau", "sessionId": session_id,
        })
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["route"], "order")
        self.assertEqual(second.json()["sessionId"], session_id)
        config = {"configurable": {"thread_id": session_id}}
        snapshot = self.client.portal.call(app.state.agent.graph.aget_state, config)
        self.assertEqual([item["content"] for item in snapshot.values["history"] if item["role"] == "user"],
                         ["chao", "don hang cua toi o dau"])

    def test_checkpoint_enforces_owner_and_expiry(self):
        headers = {"x-user-id": "buyer-one", "x-user-role": "buyer"}
        first = self.client.post("/assistant/chat", json={"message": "chao"}, headers=headers)
        self.assertEqual(first.status_code, 200)
        session_id = first.json()["sessionId"]
        config = {"configurable": {"thread_id": session_id}}
        other = self.client.post("/assistant/chat", json={
            "message": "chao", "sessionId": session_id,
        }, headers={"x-user-id": "buyer-two", "x-user-role": "buyer"})
        self.assertEqual(other.status_code, 403)
        self.client.portal.call(app.state.agent.graph.aupdate_state, config,
                                {"session_expires_at": 0})
        expired = self.client.post("/assistant/chat", json={
            "message": "chao", "sessionId": session_id,
        }, headers=headers)
        self.assertEqual(expired.status_code, 410)

    def test_legacy_session_is_imported_into_checkpoint(self):
        session_id = "m" * 43
        with sqlite3.connect(os.path.join(self.temp.name, "sessions.sqlite")) as connection:
            connection.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, state TEXT, expires REAL)")
            connection.execute("INSERT INTO sessions VALUES (?,?,?)", (
                session_id,
                json.dumps({
                    "history": [{"role": "user", "content": "tim ao thun"}],
                    "plan": {"intent": "search", "query": "tim ao thun"},
                    "user_id": "buyer-one",
                }),
                time.time() + 3600,
            ))
        self.client.__exit__(None, None, None)
        self.client = TestClient(app)
        self.client.__enter__()
        config = {"configurable": {"thread_id": session_id}}
        snapshot = self.client.portal.call(app.state.agent.graph.aget_state, config)
        self.assertEqual(snapshot.values["history"][0]["content"], "tim ao thun")
        self.assertEqual(snapshot.values["authenticated_user_id"], "buyer-one")
        response = self.client.post("/assistant/chat", json={
            "message": "chao", "sessionId": session_id,
        }, headers={"x-user-id": "buyer-one", "x-user-role": "buyer"})
        self.assertEqual(response.status_code, 200)

    def test_cart_action_tokens_are_valid_confirmation_ids(self):
        token = "cart_action:AbCdEfGhIjKlMnOp"
        self.assertEqual(ChatRequest(confirmActionId=token).confirmActionId, token)
        self.assertEqual(ChatRequest(cancelActionId=token).cancelActionId, token)

    def test_chat_session_reuse_and_no_shared_history(self):
        async def answer(state):
            return {"answer": "Xin chào", "products": [], "plan": {"intent": "clarify"}}

        graph, _ = stub_graph(answer)
        app.state.agent.graph = graph
        one = self.client.post("/assistant/chat", json={"message": "Chào"}).json()
        two = self.client.post("/assistant/chat", json={"message": "Mua áo", "sessionId": one["sessionId"]}).json()
        self.assertEqual(one["sessionId"], two["sessionId"])
        self.assertEqual(len(graph.ainvoke.call_args.args[0]["history"]), 2)
        self.client.post("/assistant/chat", json={"message": "Khách khác"})
        self.assertEqual(graph.ainvoke.call_args.args[0]["history"], [])

    def test_dependency_failure_does_not_save_failed_turn(self):
        graph, checkpoints = stub_graph(AsyncMock(side_effect=httpx.ConnectError("gemini down")))
        app.state.agent.graph = graph
        result = self.client.post("/assistant/chat", json={"message": "Mua áo"})
        self.assertEqual(result.status_code, 503)
        self.assertEqual(app.state.active_requests, 0)
        self.assertEqual(app.state.busy_sessions, set())
        self.assertEqual(checkpoints, {})
        graph.aupdate_state.assert_not_awaited()

    def test_order_focus_survives_count_question_without_caching_order_list(self):
        seen_states = []

        async def invoke(state):
            seen_states.append(state)
            if state["message"] == "Đơn #79 ở đâu?":
                return {"answer": "Đơn #79 chờ thanh toán.", "products": [], "focused_order_id": "79"}
            return {"answer": "Bạn có 2 đơn hàng.", "products": []}

        graph, _ = stub_graph(invoke)
        app.state.agent.graph = graph
        headers = {"x-user-id": "buyer-1", "x-user-role": "buyer"}
        first = self.client.post("/assistant/chat", json={"message": "Đơn #79 ở đâu?"}, headers=headers).json()
        self.client.post("/assistant/chat", json={
            "message": "Tôi có mấy đơn hàng?", "sessionId": first["sessionId"],
        }, headers=headers)
        self.client.post("/assistant/chat", json={
            "message": "Đơn đó ở đâu?", "sessionId": first["sessionId"],
        }, headers=headers)
        self.assertEqual(seen_states[1]["focused_order_id"], "79")
        self.assertEqual(seen_states[2]["focused_order_id"], "79")
        self.assertNotIn("order_list", seen_states[2])

    def test_named_product_focus_and_card_fields_survive_followups(self):
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

        graph, _ = stub_graph(invoke)
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
