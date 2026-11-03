"""Marketplace state contracts: semantic patches, reducer, graph and persistence."""
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.agents.conversation import (MarketplaceContext, MarketplaceTurn, transition, project_plan,
                                     load_context, remember_size, reconcile_fallback)
from src.agents.product import ProductAgent, RetrievalDecision
from src.agents.router import RouterAgent
from src.agents.size_search import ClothingSearchEstimate


PID, OTHER = "a" * 24, "b" * 24


def step(context, **kwargs):
    return transition(context, MarketplaceTurn(**kwargs), allowed_ids=[PID, OTHER])


class MarketplaceReducerTests(unittest.TestCase):
    def test_clothing_discovery_is_a_task_not_a_measurement_intent(self):
        ctx = step(MarketplaceContext(), operation="new_search", subject="áo thun", audience="nam", needs_fit=True)
        self.assertEqual(ctx.task, "find_products")
        self.assertEqual(ctx.awaiting, ["height_cm", "weight_kg"])
        ctx = step(ctx, operation="provide_details", buyer={"height_cm": 170})
        self.assertEqual(ctx.awaiting, ["weight_kg"])
        ctx = step(ctx, operation="provide_details", buyer={"weight_kg": 60})
        self.assertEqual(ctx.awaiting, [])
        plan = project_plan(ctx)
        self.assertEqual(plan["dialogue_act"], "size_search")
        self.assertEqual(plan["audience"], "nam")
        self.assertIsNone(plan["sizing_product_id"])

    def test_electronics_and_housewares_use_generic_attributes(self):
        ctx = step(MarketplaceContext(), operation="new_search", subject="laptop", max_price=20000000,
                   attributes=[{"name": "RAM", "value": "16GB"}, {"name": "mục đích", "value": "lập trình"}])
        ctx = step(ctx, operation="refine", attributes=[{"name": "RAM", "value": "32GB"}])
        self.assertEqual(ctx.requirements.attributes, {"RAM": "32GB", "mục đích": "lập trình"})
        self.assertEqual(ctx.requirements.max_price, 20000000)
        self.assertEqual(ctx.awaiting, [])
        self.assertIn("32GB", project_plan(ctx)["query"])
        ctx = step(ctx, operation="new_search", subject="máy pha cà phê", attributes=[{"name": "dung tích", "value": "1.5 lít"}])
        self.assertEqual(ctx.requirements.attributes, {"dung tích": "1.5 lít"})
        self.assertIsNone(ctx.requirements.max_price)
        self.assertEqual(project_plan(ctx)["dialogue_act"], "search")
        self.assertIsNone(project_plan(ctx)["product_type"])

    def test_explicit_removal_and_topic_change_clear_stale_state(self):
        ctx = step(MarketplaceContext(), operation="new_search", subject="áo sơ mi", audience="nu",
                   variant_terms=["trắng"], needs_fit=True, buyer={"height_cm": 160, "weight_kg": 50}, max_price=200000)
        ctx = step(ctx, operation="select_product", selected_product_ids=[PID])
        ctx = step(ctx, operation="refine", clear_fields=["max_price", "variant_terms"])
        self.assertIsNone(ctx.requirements.max_price)
        self.assertEqual(ctx.requirements.variant_terms, [])
        self.assertEqual(ctx.buyer.height_cm, 160)
        ctx = step(ctx, operation="new_search", subject="tai nghe", attributes=[{"name": "kết nối", "value": "Bluetooth"}])
        self.assertFalse(ctx.needs_fit)
        self.assertIsNone(ctx.buyer.height_cm)
        self.assertIsNone(ctx.requirements.audience)
        self.assertEqual(ctx.selected_product_ids, [])
        self.assertEqual(project_plan(ctx)["dialogue_act"], "search")

    def test_size_cache_survives_browse_and_budget_but_invalidates_body_or_audience(self):
        ctx = step(MarketplaceContext(), operation="new_search", subject="áo thun", audience="nam", needs_fit=True,
                   buyer={"height_cm": 170, "weight_kg": 60})
        plan = remember_size({**project_plan(ctx), "estimated_sizes": ["M"], "size_estimate_source": "model"})
        ctx = load_context(plan)
        shown = step(ctx, operation="show_results")
        self.assertEqual(shown.derived_size.sizes, ["M"])
        budget = step(shown, operation="refine", max_price=200000)
        self.assertEqual(budget.derived_size.sizes, ["M"])
        self.assertEqual(step(budget, operation="provide_details", buyer={"weight_kg": 80}).derived_size.sizes, [])
        self.assertEqual(step(budget, operation="refine", audience="nu").derived_size.sizes, [])
        fallback = reconcile_fallback(plan, {**plan, "context": {}, "estimated_sizes": []}, "xem mẫu")
        self.assertEqual(fallback["estimated_sizes"], ["M"])

    def test_selected_products_are_grounded_and_compare_does_not_become_similar(self):
        ctx = step(MarketplaceContext(), operation="new_search", subject="điện thoại")
        unknown = step(ctx, operation="ask_product", selected_product_ids=["c" * 24])
        self.assertEqual(unknown.awaiting, ["selected_product_ids"])
        self.assertEqual(unknown.selected_product_ids, [])
        compared = step(ctx, operation="compare", selected_product_ids=[PID, OTHER])
        self.assertEqual(compared.task, "compare_products")
        self.assertEqual(project_plan(compared)["intent"], "search")
        self.assertIsNone(project_plan(compared)["reference_product_id"])
        self.assertEqual(step(compared, operation="show_results").selected_product_ids, [])

    def test_legacy_checkpoint_and_conflicting_price_correction(self):
        old = load_context({"query": "tai nghe", "product_type": "tai_nghe", "min_price": 500000})
        self.assertEqual(old.version, 1)
        ctx = step(old, operation="refine", max_price=200000)
        self.assertIsNone(ctx.requirements.min_price)
        self.assertEqual(ctx.requirements.max_price, 200000)

    def test_product_fact_question_does_not_inherit_fit_subtask(self):
        ctx = step(MarketplaceContext(), operation="new_search", subject="áo thun", needs_fit=True)
        facts = step(ctx, operation="ask_product", selected_product_ids=[PID])
        self.assertFalse(facts.needs_fit)
        self.assertEqual(facts.awaiting, [])
        self.assertEqual(project_plan(facts)["dialogue_act"], "search")
        sizing = step(ctx, operation="ask_product", selected_product_ids=[PID], needs_fit=True)
        self.assertTrue(sizing.needs_fit)
        self.assertEqual(sizing.awaiting, ["height_cm", "weight_kg"])


class MarketplaceGraphTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.models, self.api = AsyncMock(), AsyncMock()
        self.agent = ProductAgent(self.api, self.models, AsyncMock())
        self.cards = [{"id": PID, "name": "Áo thun nam", "variants": [{"name": "M"}]}]
        self.agent.rag.chain = SimpleNamespace(ainvoke=AsyncMock(return_value={"products": self.cards}))

    async def turn(self, message, patch, previous=None, **kwargs):
        self.models.interpret_turn.return_value = MarketplaceTurn(**patch)
        return await self.agent.graph.ainvoke({"message": message, "previous_plan": previous or {}, **kwargs})

    async def test_interpreter_to_reducer_to_retrieval_and_reused_estimate(self):
        first = await self.turn("muốn mua áo mà chưa rõ size", {"operation": "new_search", "subject": "áo thun", "audience": "nam", "needs_fit": True})
        self.assertIn("chiều cao", first["answer"])
        self.assertNotIn("sản phẩm", first["answer"])
        self.models.structured.return_value = ClothingSearchEstimate(sizes=["M"])
        second = await self.turn("170cm 60kg", {
            "operation": "provide_details", "buyer": {"height_cm": 170, "weight_kg": 60},
        }, first["plan"])
        self.assertEqual(second["products"], self.cards)
        self.assertEqual(self.models.structured.await_count, 1)
        third = await self.turn("cho xem thêm", {"operation": "show_results"}, second["plan"])
        self.assertEqual(third["plan"]["estimated_sizes"], ["M"])
        self.assertEqual(self.models.structured.await_count, 1)
        self.assertIn("size M", third["answer"])

    async def test_product_question_fetches_selected_phone_without_vector_search(self):
        self.api.product.return_value = {"_id": PID, "name": "Điện thoại 256GB", "moderationStatus": "approved", "price": 10000000}
        self.models.structured.return_value = RetrievalDecision(action="accept", product_ids=[PID], answer="Mẫu này có 256GB.")
        result = await self.turn("bộ nhớ của mẫu đầu tiên?", {"operation": "ask_product", "selected_product_ids": [PID]},
                                 previous_products=[{"id": PID, "name": "Điện thoại 256GB"}])
        self.assertEqual(result["retrieval_mode"], "selected_products")
        self.api.product.assert_awaited_once_with(PID)
        self.agent.rag.chain.ainvoke.assert_not_awaited()
        self.assertIn("256GB", result["answer"])

    async def test_new_topic_clears_focus_and_numeric_device_specs_do_not_trigger_size(self):
        first = await self.agent.understand({"message": "áo sơ mi nữ trắng"})
        self.models.interpret_turn.return_value = MarketplaceTurn(operation="new_search", subject="máy pha cà phê", attributes=[{"name": "dung tích", "value": "1.5L"}])
        result = await self.agent.understand({"message": "đổi sang máy pha cà phê 1.5L", "previous_plan": first["plan"], "focused_product_id": PID})
        self.assertEqual(result["focused_product_ids"], [])
        self.assertIsNone(result["plan"]["audience"])
        self.assertEqual(result["plan"]["dialogue_act"], "search")
        self.assertIn("1.5L", result["plan"]["query"])

    async def test_context_survives_sqlite_checkpoint_and_agent_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = temp + "/context.sqlite"
            config = {"configurable": {"thread_id": "shopper-one"}}
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                router = RouterAgent(self.agent, checkpointer=saver)
                self.models.interpret_turn.return_value = MarketplaceTurn(operation="new_search", subject="áo thun", audience="nam", needs_fit=True)
                first = await router.graph.ainvoke({"message": "mua áo chưa biết size"}, config)
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                restarted = RouterAgent(self.agent, checkpointer=saver)
                snapshot = await restarted.graph.aget_state(config)
                self.assertEqual(snapshot.values["plan"]["context"]["awaiting"], ["height_cm", "weight_kg"])
                self.models.structured.return_value = ClothingSearchEstimate(sizes=["M"])
                self.models.interpret_turn.return_value = MarketplaceTurn(
                    operation="provide_details", buyer={"height_cm": 170, "weight_kg": 60},
                )
                second = await restarted.graph.ainvoke({"message": "170cm 60kg", "previous_plan": snapshot.values["plan"], "answer": "", "products": []}, config)
                self.assertEqual(second["plan"]["context"]["task"], "find_products")
                self.assertEqual(second["products"], self.cards)

    async def test_transaction_confirmation_bypasses_semantic_interpreter(self):
        from src.agents.intent import TurnIntent
        self.agent.commerce_agent = SimpleNamespace()
        self.models.understand_intent.return_value = TurnIntent(commerce_intent="confirm_checkout")
        result = await self.agent.plan({"message": "xác nhận đặt hàng", "pending_action": {
            "type": "checkout_confirmation", "quoteId": "trusted-quote"}})
        self.assertEqual(result["flow"], "commerce")
        self.assertEqual(result["commerce_intent"], "confirm_checkout")
        self.models.interpret_turn.assert_not_awaited()

    async def test_commerce_read_path_updates_canonical_task(self):
        from src.agents.intent import TurnIntent
        self.agent.commerce_agent = SimpleNamespace(_references=lambda state: [PID, OTHER])
        self.models.understand_intent.return_value = TurnIntent(commerce_intent="compare_products")
        result = await self.agent.plan({"message": "so sánh hai mẫu", "previous_products": [
            {"id": PID, "name": "Điện thoại A"}, {"id": OTHER, "name": "Điện thoại B"}]})
        self.assertEqual(result["plan"]["context"]["task"], "compare_products")
        self.assertEqual(result["plan"]["context"]["selected_product_ids"], [PID, OTHER])
        self.assertEqual(result["flow"], "commerce")

    async def test_semantic_comparison_followup_preempts_keyword_read_path(self):
        from src.agents.intent import TurnIntent
        self.agent.commerce_agent = SimpleNamespace(
            _references=lambda state: [PID, OTHER],
            execute=AsyncMock(),
        )
        self.models.understand_intent.return_value = TurnIntent(commerce_intent="compare_products")
        previous = project_plan(step(MarketplaceContext(), operation="compare",
                                     selected_product_ids=[PID, OTHER]))
        products = {
            PID: {"_id": PID, "name": "Loa Monster", "price": 3190000,
                  "description": "Khối lượng 2 kg", "moderationStatus": "approved"},
            OTHER: {"_id": OTHER, "name": "Loa AW-Ride", "price": 370000,
                    "description": "Khối lượng 0.313 kg", "moderationStatus": "approved"},
        }
        self.api.product.side_effect = lambda product_id: products[product_id]
        self.models.interpret_turn.return_value = MarketplaceTurn(
            operation="compare", response_mode="recommend_one",
            selected_product_ids=[PID, OTHER],
        )
        self.models.structured.return_value = RetrievalDecision(
            action="accept", product_ids=[OTHER],
            answer="AW-Ride nhẹ hơn theo khối lượng catalog: 0,313 kg so với 2 kg.",
        )
        result = await self.agent.graph.ainvoke({
            "message": "Tôi đặt trên bàn học, theo bạn nên lấy mẫu nào?",
            "previous_plan": previous,
            "previous_products": [{"id": PID, "name": "Loa Monster"},
                                  {"id": OTHER, "name": "Loa AW-Ride"}],
            "focused_product_ids": [PID, OTHER],
            "history": [{"role": "user", "content": "So sánh hai loa"}],
        })
        self.assertEqual(result["plan"]["context"]["response_mode"], "recommend_one")
        self.assertEqual(result["focused_product_ids"], [OTHER])
        self.assertEqual(result["products"], [])
        self.assertIn("AW-Ride nhẹ hơn", result["answer"])
        self.agent.commerce_agent.execute.assert_not_awaited()
        self.agent.rag.chain.ainvoke.assert_not_awaited()
