import asyncio
import unittest
from types import SimpleNamespace

from langgraph.checkpoint.memory import MemorySaver

from app.budget import BudgetExceeded, bounded, start_turn
from app.config import AgenticSettings
from app.graph import (
    AgenticShoppingGraph,
    _apply_relaxation,
    _deterministic_turn,
    _next_relaxation,
)
from app.schemas import (
    AgentPlan,
    SearchFilters,
    SemanticConstraint,
    SemanticTask,
    SemanticTurn,
)
from test_graph import (
    BASIC_ID,
    PRODUCT_ID,
    FakeMarketplace,
    FakeModels,
    FakeRetriever,
    VariantMarketplace,
    state,
)


class SemanticModels(FakeModels):
    def __init__(self, turn=None):
        super().__init__()
        self.turn = turn
        self.decide_calls = 0
        self.answer_calls = 0

    async def decide(self, *_args, **_kwargs):
        self.decide_calls += 1
        return self.turn

    async def answer(self, *args, **kwargs):
        self.answer_calls += 1
        return await super().answer(*args, **kwargs)

    async def answer_policy(self, _question, _context):
        return "Đổi trả trong 7 ngày [Nguồn 1]"


class FakePolicy:
    async def retrieve(self, _question):
        return (
            [{"number": 1, "title": "Đổi trả", "text": "Đổi trả trong 7 ngày", "url": ""}],
            [{"number": 1, "title": "Đổi trả", "url": ""}],
        )


def build(models, marketplace=None, policy=None):
    return AgenticShoppingGraph(
        AgenticSettings(gemini_api_key="test"),
        models,
        FakeRetriever(),
        marketplace or FakeMarketplace(),
        policy=policy,
        checkpointer=MemorySaver(),
    )


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async def ok():
            return "ok"

        self.ok = ok

    async def test_call_limit_counts_generative_calls_only(self):
        budget = start_turn(max_calls=2, seconds=10)
        await bounded("decide", 1, self.ok())
        await bounded("embed", 1, self.ok())
        await bounded("answer", 1, self.ok())
        with self.assertRaises(BudgetExceeded):
            await bounded("verify", 1, self.ok())
        self.assertEqual(budget.calls, 2)
        self.assertTrue(budget.exhausted)

    async def test_slow_call_is_cut_by_its_timeout(self):
        start_turn(max_calls=4, seconds=10)
        with self.assertRaises(asyncio.TimeoutError):
            await bounded("answer", 0.05, asyncio.sleep(1))

    async def test_expired_deadline_blocks_every_call(self):
        start_turn(max_calls=4, seconds=0.1)
        with self.assertRaises(BudgetExceeded):
            await bounded("embed", 1, self.ok())


class FastPathTests(unittest.IsolatedAsyncioTestCase):
    def test_short_variant_pick_is_decided_without_model(self):
        turn = _deterministic_turn("xl", [], BASIC_ID, {})
        self.assertEqual(turn.tasks[0].intent, "product_detail")
        self.assertEqual(turn.tasks[0].constraints[0].value, ["XL"])

    def test_long_or_ambiguous_messages_go_to_the_model(self):
        self.assertIsNone(_deterministic_turn("xl", [], "", {}))
        self.assertIsNone(
            _deterministic_turn(
                "tôi muốn mua một chiếc điện thoại pin trâu chụp ảnh đẹp", [], BASIC_ID, {}
            )
        )

    async def test_variant_pick_skips_decide_and_answers_from_catalog(self):
        models = SemanticModels()
        agent = build(models, VariantMarketplace())
        current = state("xl")
        current["focused_products"] = [{"id": BASIC_ID, "name": "Áo Thun Nam Dream Team"}]
        current["active_product_id"] = BASIC_ID
        result = await agent.graph.ainvoke(
            current, config={"configurable": {"thread_id": "fast"}}
        )
        self.assertEqual(models.decide_calls, 0)
        self.assertEqual(models.answer_calls, 0)
        self.assertIn("FAST_PATH", result["warnings"])
        self.assertIn("size XL", result["answer"])

    async def test_yes_after_cart_offer_prepares_cart_without_model(self):
        models = SemanticModels()
        agent = build(models)
        current = state("có")
        current["history"] = [
            {"role": "assistant", "content": "Bạn có muốn thêm lựa chọn này vào giỏ không?"}
        ]
        current["focused_products"] = [{"id": PRODUCT_ID, "name": "Áo sơ mi trắng"}]
        current["active_product_id"] = PRODUCT_ID
        result = await agent.graph.ainvoke(
            current, config={"configurable": {"thread_id": "yes"}}
        )
        self.assertEqual(models.decide_calls, 0)
        self.assertEqual(result["pending_action"]["kind"], "cart_add")


class RelaxationTests(unittest.TestCase):
    def test_relaxes_soft_specs_then_price_then_color(self):
        filters = SearchFilters(
            max_price=1_000_000,
            colors=["den"],
            spec_constraints=[
                SemanticConstraint(key="ram", operator="gte", value=8, strength="soft")
            ],
        )
        relaxed: list[str] = []
        order = []
        while key := _next_relaxation(filters, relaxed):
            filters = _apply_relaxation(filters, key)
            relaxed.append(key)
            order.append(key)
        self.assertEqual(order, ["spec.soft", "price", "variant.color"])
        self.assertEqual(filters.max_price, 1_150_000)
        self.assertEqual(filters.colors, [])

    def test_nothing_to_relax_stops_the_retrieval_loop(self):
        agent = object.__new__(AgenticShoppingGraph)
        agent.settings = SimpleNamespace(max_retrieval_rounds=3)
        route = agent.route_after_retrieval(
            {
                "products": [],
                "retrieval_rounds": 1,
                "plan": AgentPlan(query="xyz").model_dump(),
                "search_context": {},
            }
        )
        self.assertEqual(route, "collect")


class VagueCustomerTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_clarification_escalates_to_handoff(self):
        models = SemanticModels(
            SemanticTurn(tasks=[SemanticTask(intent="product_search", query="?")], confidence=0.2)
        )
        agent = build(models)
        config = {"configurable": {"thread_id": "vague"}}
        first = await agent.graph.ainvoke(state("cái đó đó"), config=config)
        second = await agent.graph.ainvoke(state("ừ thì cái kia"), config=config)
        third = await agent.graph.ainvoke(state("nói chung là vậy"), config=config)

        self.assertEqual(first["route"], "clarify")
        self.assertEqual(first["suggestions"], ["Thời trang"])
        self.assertFalse(first["handoff"])
        self.assertIn("gợi ý nhanh", second["answer"])
        self.assertTrue(third["handoff"])
        self.assertEqual(third["clarify_count"], 3)

    async def test_successful_turn_resets_clarification_count(self):
        models = SemanticModels(
            SemanticTurn(tasks=[SemanticTask(intent="product_search", query="?")], confidence=0.2)
        )
        agent = build(models)
        config = {"configurable": {"thread_id": "reset"}}
        await agent.graph.ainvoke(state("cái đó đó"), config=config)
        models.turn = SemanticTurn(
            tasks=[SemanticTask(intent="product_search", query="áo sơ mi trắng")],
            confidence=0.95,
            focus_update="replace",
        )
        result = await agent.graph.ainvoke(state("áo sơ mi trắng"), config=config)
        self.assertEqual(result["clarify_count"], 0)

    async def test_medium_confidence_search_acts_on_stated_assumption(self):
        models = SemanticModels(
            SemanticTurn(
                tasks=[
                    SemanticTask(
                        intent="product_search",
                        query="áo sơ mi",
                        constraints=[SemanticConstraint(key="product_type", value="áo sơ mi")],
                    )
                ],
                confidence=0.6,
                focus_update="replace",
            )
        )
        agent = build(models)
        result = await agent.graph.ainvoke(
            state("cái áo hôm trước"), config={"configurable": {"thread_id": "assume"}}
        )
        self.assertEqual(result["route"], "product_search")
        self.assertTrue(result["answer"].startswith("Mình hiểu bạn đang tìm “áo sơ mi”"))
        self.assertIn("ASSUMED_INTENT", result["warnings"])

    async def test_multi_task_runs_policy_in_parallel_and_names_skipped_task(self):
        models = SemanticModels(
            SemanticTurn(
                tasks=[
                    SemanticTask(
                        intent="product_search",
                        query="áo sơ mi",
                        constraints=[SemanticConstraint(key="product_type", value="áo sơ mi")],
                    ),
                    SemanticTask(intent="cart_view"),
                    SemanticTask(intent="policy", query="chính sách đổi trả"),
                ],
                confidence=0.95,
                focus_update="replace",
            )
        )
        agent = build(models, policy=FakePolicy())
        result = await agent.graph.ainvoke(
            state("tìm áo sơ mi, xem giỏ và cho hỏi đổi trả"),
            config={"configurable": {"thread_id": "multi"}},
        )
        self.assertEqual(result["route"], "multi")
        self.assertIn("xem giỏ hàng", result["answer"])
        self.assertIn("Đổi trả trong 7 ngày [Nguồn 1]", result["answer"])
        self.assertEqual(result["sources"][0]["title"], "Đổi trả")


class VerifierFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_scope_check_keeps_only_name_grounded_products_without_model(self):
        class Retriever:
            async def search(self, *_args, **_kwargs):
                return [{"productId": "1" * 24}, {"productId": "2" * 24}]

        class Marketplace:
            async def hydrate_products(self, *_args, **_kwargs):
                return [
                    {"id": "1" * 24, "name": "Điện thoại Galaxy A07", "specifications": []},
                    {"id": "2" * 24, "name": "Loa Bluetooth", "specifications": []},
                ]

        class Models:
            async def verify_candidates(self, *_args, **_kwargs):
                raise BudgetExceeded("no calls left")

        agent = object.__new__(AgenticShoppingGraph)
        agent.settings = SimpleNamespace(retrieval_limit=30, result_limit=6, max_retrieval_rounds=2)
        agent.retriever = Retriever()
        agent.marketplace = Marketplace()
        agent.models = Models()
        result = await agent.retrieve(
            {
                "query": "điện thoại dưới 5 triệu",
                "message": "Tìm điện thoại dưới 5 triệu",
                "plan": AgentPlan(query="điện thoại dưới 5 triệu").model_dump(),
                "semantic_turn": SemanticTurn(
                    tasks=[SemanticTask(intent="product_search", query="điện thoại dưới 5 triệu")],
                    confidence=0.98,
                ).model_dump(),
                "retrieval_rounds": 0,
            }
        )
        # The broken verifier is never called: scope is checked on names.
        self.assertEqual([item["id"] for item in result["products"]], ["1" * 24])
        self.assertNotIn("UNVERIFIED", result["warnings"])


class ProductHeadTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_kind_without_a_category_keeps_only_that_kind(self):
        class Retriever:
            async def search(self, *_args, **_kwargs):
                return [{"productId": "1" * 24}, {"productId": "2" * 24}]

        class Marketplace:
            async def hydrate_products(self, *_args, **_kwargs):
                return [
                    {"id": "1" * 24, "name": "MUJI Dầu Thơm Nội Thất", "specifications": []},
                    {"id": "2" * 24, "name": "Nồi chiên không dầu 5L", "specifications": []},
                ]

        agent = object.__new__(AgenticShoppingGraph)
        agent.settings = SimpleNamespace(retrieval_limit=30, result_limit=6, max_retrieval_rounds=2)
        agent.retriever = Retriever()
        agent.marketplace = Marketplace()
        agent.models = SemanticModels()
        filters = SearchFilters(product_type="nồi chiên không dầu to")
        result = await agent.retrieve({
            "query": "nồi chiên không dầu loại to",
            "message": "nồi chiên ko dầu loại to",
            "plan": AgentPlan(query="nồi chiên", filters=filters).model_dump(),
            "retrieval_rounds": 0,
        })
        self.assertEqual([item["id"] for item in result["products"]], ["2" * 24])


class SlowModels(SemanticModels):
    def __init__(self, turn=None, delay=0.0, error=None):
        super().__init__(turn)
        self.delay = delay
        self.error = error

    async def decide(self, *_args, **_kwargs):
        self.decide_calls += 1
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.turn


def hedged(models):
    return AgenticShoppingGraph(
        AgenticSettings(gemini_api_key="test", decide_hedge=0.05),
        models,
        FakeRetriever(),
        FakeMarketplace(),
        checkpointer=MemorySaver(),
    )


class HedgedDecisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_model_does_not_delay_a_plain_search(self):
        agent = hedged(SlowModels(delay=5))
        loop = asyncio.get_running_loop()
        started = loop.time()
        result = await agent.understand(state("tìm tai nghe bluetooth dưới 500k"))
        self.assertLess(loop.time() - started, 1)
        self.assertIn("PARSED_SEARCH", result["warnings"])
        task = result["semantic_turn"]["tasks"][0]
        self.assertEqual(task["intent"], "product_search")
        prices = [item for item in task["constraints"] if item["key"] == "price"]
        self.assertEqual([(item["operator"], item["value"]) for item in prices], [("lte", 500000)])

    async def test_fast_model_answer_wins_over_the_parse(self):
        turn = SemanticTurn(
            tasks=[SemanticTask(intent="product_search", query="tai nghe chống ồn")],
            confidence=0.97,
        )
        result = await hedged(SlowModels(turn)).understand(
            state("tìm tai nghe bluetooth dưới 500k")
        )
        self.assertNotIn("PARSED_SEARCH", result["warnings"])
        self.assertEqual(result["semantic_turn"]["tasks"][0]["query"], "tai nghe chống ồn")

    async def test_model_outage_still_searches_instead_of_asking(self):
        for message in ["laptop văn phòng pin trâu", "quà sinh nhật cho bạn gái"]:
            result = await hedged(SlowModels(error=TimeoutError())).understand(state(message))
            self.assertIn("MODEL_UNAVAILABLE", result["warnings"])
            self.assertEqual(result["semantic_turn"]["tasks"][0]["intent"], "product_search")
            self.assertFalse(result["semantic_turn"]["needs_clarification"])

    async def test_policy_question_does_not_wait_for_a_slow_model(self):
        result = await hedged(SlowModels(delay=5)).understand(state("chính sách đổi trả thế nào"))
        self.assertIn("PARSED_SEARCH", result["warnings"])
        self.assertEqual(result["semantic_turn"]["tasks"][0]["intent"], "policy")

    async def test_unparsed_message_waits_for_the_model(self):
        turn = SemanticTurn(tasks=[SemanticTask(intent="cart_view")], confidence=0.95)
        result = await hedged(SlowModels(turn, delay=0.2)).understand(
            state("giỏ hàng của tôi có gì")
        )
        self.assertEqual(result["semantic_turn"]["tasks"][0]["intent"], "cart_view")


if __name__ == "__main__":
    unittest.main()


class BenchmarkRegressionTests(unittest.IsolatedAsyncioTestCase):
    def agent(self, products, models):
        class Retriever:
            async def search(self, *_args, **_kwargs):
                return [{"productId": item["id"]} for item in products]

        class Marketplace:
            async def hydrate_products(self, *_args, **_kwargs):
                return list(products)

        agent = object.__new__(AgenticShoppingGraph)
        agent.settings = SimpleNamespace(retrieval_limit=30, result_limit=6, max_retrieval_rounds=2)
        agent.retriever = Retriever()
        agent.marketplace = Marketplace()
        agent.models = models
        return agent

    async def test_hard_spec_without_structured_data_goes_to_the_verifier(self):
        from app.schemas import CandidateVerification, VerificationBatch

        products = [
            {"id": "1" * 24, "name": "Laptop Asus Vivobook 16 (Ultra 7, 16GB, 512GB)", "specifications": []},
            {"id": "2" * 24, "name": "Laptop Dell (8GB)", "specifications": []},
        ]

        class Models:
            sent = []

            async def verify_candidates(self, _query, _constraints, candidates):
                self.sent.extend(item["id"] for item in candidates)
                return VerificationBatch(results=[
                    CandidateVerification(
                        productId=item["id"], verdict="match" if "16GB" in item["name"] else "no_match", evidence=[]
                    )
                    for item in candidates
                ])

        ram = SemanticConstraint(key="ram", operator="gte", value=16, unit="GB")
        models = Models()
        result = await self.agent(products, models).retrieve({
            "query": "laptop ram 16gb", "message": "laptop ram 16gb dưới 20 triệu",
            "plan": AgentPlan(query="laptop", filters=SearchFilters(product_type="laptop", spec_constraints=[ram])).model_dump(),
            "retrieval_rounds": 0,
        })
        self.assertEqual(sorted(models.sent), ["1" * 24, "2" * 24])
        self.assertEqual([item["id"] for item in result["products"]], ["1" * 24])

    async def test_brand_missing_from_facets_still_filters_by_name(self):
        products = [
            {"id": "1" * 24, "name": "Tai nghe Sony WH-1000XM6", "specifications": []},
            {"id": "2" * 24, "name": "Tai nghe JBL Tune 530BT", "specifications": []},
        ]
        result = await self.agent(products, SemanticModels()).retrieve({
            "query": "tai nghe sony", "message": "tai nghe sony",
            "plan": AgentPlan(query="tai nghe", filters=SearchFilters(product_type="tai nghe", brand="Sony")).model_dump(),
            "retrieval_rounds": 0,
        })
        self.assertEqual([item["id"] for item in result["products"]], ["1" * 24])

    def test_cheapest_mid_conversation_is_left_to_the_model(self):
        self.assertIsNotNone(_deterministic_turn("cái nào rẻ nhất", [], "", {}))
        history = [{"role": "user", "content": "áo thun nam"}, {"role": "assistant", "content": "Mình tìm thấy 6 sản phẩm"}]
        self.assertIsNone(_deterministic_turn("cái nào rẻ nhất", history, "", {}))


class FollowUpGuardTests(unittest.TestCase):
    def test_new_product_kind_is_not_a_variant_pick_on_the_active_item(self):
        self.assertIsNone(_deterministic_turn("áo khoác không phải màu đen", [], BASIC_ID, {}))
        self.assertEqual(
            _deterministic_turn("màu đen", [], BASIC_ID, {}).tasks[0].intent, "product_detail"
        )

    def test_unconfirmable_hard_spec_is_relaxed_last(self):
        waterproof = SemanticConstraint(key="water_resistance", operator="contains", value="chống nước")
        filters = SearchFilters(brand="sony", spec_constraints=[waterproof])
        self.assertEqual(_next_relaxation(filters, []), "brand")
        self.assertEqual(_next_relaxation(filters, ["brand"]), "spec.hard")
        self.assertEqual(_apply_relaxation(filters, "spec.hard").spec_constraints, [])
