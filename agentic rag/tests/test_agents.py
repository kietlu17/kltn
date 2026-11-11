"""Supervisor + product agent + order agent, LLM-first."""

import unittest
from types import SimpleNamespace

from langgraph.checkpoint.memory import MemorySaver

from app.agents import OrderAgent, ProductAgent
from app.config import AgenticSettings
from app.graph import AgenticShoppingGraph
from app.models import GeminiGateway
from app.rerank import adaptive_top_k, product_document
from app.taxonomy import build_catalog_tree
from app.schemas import (
    AgentPlan,
    CandidateJudgement,
    CandidateRanking,
    OrderDecision,
    SearchFilters,
    SemanticConstraint,
    SemanticReference,
    SemanticTask,
    SemanticTurn,
    WebResearch,
    WebSource,
)
from test_graph import PRODUCT_ID, VARIANT_ID, FakeMarketplace, FakeRetriever, state

PHONE = "1" * 24
CASE = "2" * 24
CHARGER = "3" * 24
NAMES = {PHONE: "Điện thoại Samsung Galaxy A55", CASE: "Ốp lưng Galaxy A55", CHARGER: "Củ sạc nhanh 25W"}


def search_turn(query="điện thoại samsung", **task):
    return SemanticTurn(
        tasks=[SemanticTask(intent="product_search", query=query, **task)],
        confidence=0.95,
        focus_update="replace",
    )


class CatalogRetriever:
    def __init__(self, by_query=None):
        self.by_query = by_query or {}
        self.calls = []

    async def search(self, query, filters, limit=None, sort_by="relevance"):
        self.calls.append((query, filters.model_dump()))
        ids = self.by_query.get(query, [PHONE, CASE, CHARGER])
        return [{"productId": product_id, "vectorScore": 0.8} for product_id in ids]


class CatalogMarketplace(FakeMarketplace):
    async def hydrate_products(self, hits, _filters, _limit):
        return [
            {"id": hit["productId"], "name": NAMES.get(hit["productId"], "Sản phẩm"), "price": 100000,
             "variants": [], "specifications": []}
            for hit in hits
        ]


class JudgeModels:
    """A chat model that ranks, researches and answers."""

    def __init__(self, turn=None, grades=None, research=None, fail_rank=False):
        self.turn = turn
        self.grades = grades or {}
        self.research = research or WebResearch()
        self.fail_rank = fail_rank
        self.decide_calls = 0
        self.rank_calls = []
        self.web_calls = []
        self.answer_payloads = []

    async def decide(self, *_args, **_kwargs):
        self.decide_calls += 1
        return self.turn

    async def rank_candidates(self, need, constraints, products):
        self.rank_calls.append((need, constraints, [item["id"] for item in products]))
        if self.fail_rank:
            raise TimeoutError()
        return CandidateRanking(results=[
            CandidateJudgement(index=index, relevance=self.grades.get(item["id"], 0), reason=f"lý do {index}")
            for index, item in enumerate(products, 1)
        ])

    async def web_research(self, question):
        self.web_calls.append(question)
        return self.research

    async def verify_candidates(self, *_args, **_kwargs):
        raise AssertionError("the LLM judge replaces the separate verifier")

    async def answer(self, _message, _plan, result, products, _history):
        self.answer_payloads.append(result)
        return f"LLM trả lời về {len(products)} sản phẩm."


def product_agent(models, retriever=None, **settings):
    return ProductAgent(
        AgenticSettings(gemini_api_key="test", **settings),
        models,
        retriever or CatalogRetriever(),
        CatalogMarketplace(),
    )


def retrieve_state(turn, query="điện thoại samsung", filters=None):
    return {
        "query": query, "message": query, "request": {}, "warnings": [], "retrieval_rounds": 0,
        "semantic_turn": turn.model_dump(),
        "plan": AgentPlan(query=query, filters=filters or SearchFilters()).model_dump(),
    }


class LlmRankingTests(unittest.IsolatedAsyncioTestCase):
    async def test_judge_drops_other_kinds_and_decides_top_k(self):
        models = JudgeModels(grades={PHONE: 3, CASE: 1, CHARGER: 0})
        result = await product_agent(models).retrieve(retrieve_state(search_turn()))
        self.assertEqual([item["id"] for item in result["products"]], [PHONE])
        self.assertIn("LLM_RANKED", result["warnings"])
        self.assertFalse(result["tool_result"]["partialMatch"])
        self.assertEqual(result["tool_result"]["ranking"][0]["reason"], "lý do 1")
        # The need comes from the semantic task, not the raw message.
        self.assertEqual(models.rank_calls[0][0], "điện thoại samsung")

    async def test_only_partial_matches_are_flagged(self):
        models = JudgeModels(grades={PHONE: 1, CASE: 1})
        result = await product_agent(models).retrieve(retrieve_state(search_turn()))
        self.assertEqual([item["id"] for item in result["products"]], [PHONE, CASE])
        self.assertTrue(result["tool_result"]["partialMatch"])

    async def test_hard_spec_needs_proof_from_the_judge(self):
        class SpecModels(JudgeModels):
            async def rank_candidates(self, need, constraints, products):
                self.rank_calls.append((need, constraints, [item["id"] for item in products]))
                return CandidateRanking(results=[
                    CandidateJudgement(index=1, relevance=3, verdict="match", evidence=["IP67"]),
                    CandidateJudgement(index=2, relevance=3, verdict="unknown"),
                ])

        models = SpecModels()
        waterproof = SemanticConstraint(key="water_resistance", operator="contains", value="chống nước")
        current = retrieve_state(search_turn(), filters=SearchFilters(spec_constraints=[waterproof]))
        result = await product_agent(models).retrieve(current)
        self.assertEqual([item["id"] for item in result["products"]], [PHONE])
        self.assertEqual(models.rank_calls[0][1][0]["key"], "water_resistance")
        verdict = next(item for item in result["tool_result"]["verification"] if item["productId"] == PHONE)
        self.assertEqual(verdict["evidence"], ["IP67"])

    async def test_rank_failure_falls_back_to_rule_ranking(self):
        models = JudgeModels(fail_rank=True)
        result = await product_agent(models).retrieve(
            retrieve_state(search_turn(), filters=SearchFilters(product_type="điện thoại"))
        )
        self.assertIn("RANK_FALLBACK", result["warnings"])
        # The rule path keeps only names of the requested kind.
        self.assertEqual([item["id"] for item in result["products"]], [PHONE])

    async def test_latency_first_mode_never_calls_the_judge(self):
        models = JudgeModels(grades={PHONE: 3})
        await product_agent(models, llm_first=False).retrieve(retrieve_state(search_turn()))
        self.assertEqual(models.rank_calls, [])


class CrossEncoderTopKTests(unittest.TestCase):
    def test_adaptive_cut_drops_far_weaker_candidates(self):
        products = [{"id": "a", "rerankProb": 0.9}, {"id": "b", "rerankProb": 0.5}, {"id": "c", "rerankProb": 0.1}]
        self.assertEqual([item["id"] for item in adaptive_top_k(products, 5, 0.3)], ["a", "b"])

    def test_unsure_model_keeps_the_first_stage_top_k(self):
        products = [{"id": "a", "rerankProb": 0.1}, {"id": "b", "rerankProb": 0.05}]
        self.assertEqual(len(adaptive_top_k(products, 5, 0.3)), 2)
        self.assertEqual(len(adaptive_top_k([{"id": "a"}, {"id": "b"}], 1, 0.3)), 1)

    def test_document_carries_price_specs_and_variants(self):
        document = product_document({
            "name": "Tai nghe X", "brand": "Sony",
            "variants": [{"name": "Đen", "price": 500000}, {"name": "Trắng", "price": 550000}],
            "specifications": [{"name": "Chống ồn", "value": "ANC"}],
            "description": "<p>Pin 30 giờ</p>",
        })
        self.assertTrue(document.startswith("Tai nghe X | Sony | giá 500.000đ - 550.000đ"))
        self.assertIn("Chống ồn: ANC", document)
        self.assertIn("biến thể: Đen, Trắng", document)
        self.assertIn("Pin 30 giờ", document)


class WebResearchTests(unittest.IsolatedAsyncioTestCase):
    def graph(self, models, retriever=None):
        return AgenticShoppingGraph(
            AgenticSettings(gemini_api_key="test"),
            models,
            retriever or CatalogRetriever(),
            CatalogMarketplace(),
            checkpointer=MemorySaver(),
        )

    async def test_knowledge_question_runs_research_beside_the_search(self):
        research = WebResearch(
            summary="Galaxy A55 đạt chuẩn IP67.",
            sources=[WebSource(title="samsung.com", url="https://samsung.com/a55")],
        )
        turn = search_turn(web_research=True, research_query="Galaxy A55 có chống nước không")
        models = JudgeModels(turn, grades={PHONE: 3}, research=research)
        result = await self.graph(models).graph.ainvoke(
            state("A55 có chống nước không"), config={"configurable": {"thread_id": "web"}}
        )
        self.assertEqual(models.web_calls, ["Galaxy A55 có chống nước không"])
        self.assertEqual(models.answer_payloads[-1]["webResearch"]["summary"], "Galaxy A55 đạt chuẩn IP67.")
        self.assertEqual(result["sources"][-1]["url"], "https://samsung.com/a55")
        self.assertEqual(result["answer"], "LLM trả lời về 1 sản phẩm.")

    async def test_knowledge_comparison_is_answered_from_the_web_not_asked_back(self):
        research = WebResearch(summary="Snapdragon 8 Gen 3 nhỉnh hơn về GPU.",
                               sources=[WebSource(title="a.vn", url="https://a.vn")])
        turn = SemanticTurn(tasks=[SemanticTask(
            intent="compare_products", query="so sánh chip", web_research=True,
            research_query="Snapdragon 8 Gen 3 vs Dimensity 9300")], confidence=0.95)
        models = JudgeModels(turn, research=research)
        result = await self.graph(models).graph.ainvoke(
            state("chip snapdragon 8 gen 3 với dimensity 9300 cái nào mạnh hơn"),
            config={"configurable": {"thread_id": "chip"}},
        )
        self.assertEqual(result["route"], "general")
        self.assertEqual(result["answer"], "LLM trả lời về 0 sản phẩm.")
        self.assertEqual(models.answer_payloads[-1]["question"][:4], "chip")
        self.assertIn("webResearch", models.answer_payloads[-1])

    async def test_plain_search_does_not_search_the_web(self):
        models = JudgeModels(search_turn(), grades={PHONE: 3})
        await self.graph(models).graph.ainvoke(
            state("điện thoại samsung"), config={"configurable": {"thread_id": "plain"}}
        )
        self.assertEqual(models.web_calls, [])

    async def test_empty_catalog_result_is_expanded_with_web_queries(self):
        research = WebResearch(catalog_queries=["cần câu", "hộp đựng mồi"])
        retriever = CatalogRetriever({"quà cho bố thích câu cá": [], "cần câu": [PHONE], "hộp đựng mồi": []})
        models = JudgeModels(search_turn("quà cho bố thích câu cá"), grades={PHONE: 2}, research=research)
        result = await self.graph(models, retriever).graph.ainvoke(
            state("quà cho bố thích câu cá"), config={"configurable": {"thread_id": "expand"}}
        )
        self.assertIn("WEB_EXPANDED", result["warnings"])
        self.assertEqual(len(models.web_calls), 1)
        self.assertEqual([item["id"] for item in result["products"]], [PHONE])
        self.assertEqual(result["tool_result"]["expandedQueries"], ["cần câu", "hộp đựng mồi"])
        # The judge still grades against the original need.
        self.assertEqual(models.rank_calls[-1][0], "quà cho bố thích câu cá")


class WebResearchParsingTests(unittest.IsolatedAsyncioTestCase):
    async def test_grounded_answer_is_split_into_summary_queries_and_sources(self):
        class Response:
            text = "Nên chọn cần câu máy.\nTU_KHOA: cần câu; máy câu cá; hộp mồi"
            response_metadata = {"grounding_metadata": {
                "grounding_chunks": [{"web": {"uri": "https://a.vn/x", "title": "a.vn"}}],
                "grounding_supports": [{"segment": {}}],
            }}

        class WebModel:
            async def ainvoke(self, _messages):
                return Response()

        gateway = object.__new__(GeminiGateway)
        gateway.settings = AgenticSettings(gemini_api_key="test")
        gateway.web_llm = WebModel()
        gateway._web_cache = {}
        from collections import OrderedDict
        gateway._web_cache = OrderedDict()
        research = await gateway.web_research("quà cho bố thích câu cá")
        self.assertEqual(research.summary, "Nên chọn cần câu máy.")
        self.assertEqual(research.catalog_queries, ["cần câu", "máy câu cá", "hộp mồi"])
        self.assertEqual(research.sources[0].url, "https://a.vn/x")


class OrderModels:
    def __init__(self, decision=None, fail=False):
        self.decision = decision
        self.fail = fail
        self.contexts = []

    async def resolve_order(self, context):
        self.contexts.append(context)
        if self.fail:
            raise TimeoutError()
        return self.decision


class VariantCard(FakeMarketplace):
    async def product_card(self, product_id, filters=None):
        return {
            "id": product_id, "name": "Áo thun", "price": 200000,
            "variants": [
                {"id": "9" * 24, "name": "Đen / M", "price": 200000, "availableStock": 3},
                {"id": "8" * 24, "name": "Đen / L", "price": 200000, "availableStock": 3},
                {"id": "7" * 24, "name": "Trắng / L", "price": 200000, "availableStock": 0},
            ],
        }

    async def product(self, product_id):
        return {"name": "Áo thun", "variants": [{"id": VARIANT_ID, "name": "Đen / L"}]}


def order_agent(models, marketplace=None, **settings):
    return OrderAgent(AgenticSettings(gemini_api_key="test", **settings), models, marketplace or VariantCard())


def order_state(message, intent, product_id=PRODUCT_ID, **extra):
    current = state(message)
    current["semantic_turn"] = SemanticTurn(tasks=[SemanticTask(intent=intent)], confidence=0.95).model_dump()
    current["plan"] = AgentPlan(intent=intent, product_id=product_id, **extra).model_dump()
    return current


class OrderAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_picks_the_variant_from_the_real_list(self):
        models = OrderModels(OrderDecision(action="add", variant_index=2, quantity=2, confidence=0.9))
        result = await order_agent(models).prepare_cart(order_state("lấy màu đen size L 2 cái", "cart_add"))
        action = result["pending_action"]
        self.assertEqual(action["payload"], {"productId": PRODUCT_ID, "variantId": "8" * 24, "quantity": 2})
        self.assertIn("Đen / L", action["summary"])
        variants = models.contexts[0]["product"]["variants"]
        self.assertEqual([item["inStock"] for item in variants], [True, True, False])

    async def test_model_question_is_asked_when_the_variant_is_unclear(self):
        models = OrderModels(OrderDecision(action="clarify", clarification="Bạn lấy size M hay L?"))
        result = await order_agent(models).prepare_cart(order_state("lấy màu đen", "cart_add"))
        self.assertNotIn("pending_action", result)
        self.assertEqual(result["tool_result"]["clarification"], "Bạn lấy size M hay L?")

    async def test_model_outage_falls_back_to_variant_matching(self):
        current = order_state("lấy cái này", "cart_add")
        current["selected_options"] = {"colors": ["đen"], "sizes": ["M"]}
        result = await order_agent(OrderModels(fail=True)).prepare_cart(current)
        self.assertEqual(result["pending_action"]["payload"]["variantId"], "9" * 24)

    async def test_removal_without_reference_is_matched_against_the_cart(self):
        models = OrderModels(OrderDecision(action="remove", line_index=1, confidence=0.9))
        result = await order_agent(models).prepare_cart(order_state("bỏ cái áo khỏi giỏ", "cart_remove", product_id=None))
        action = result["pending_action"]
        self.assertEqual(action["kind"], "cart_remove")
        self.assertEqual(action["payload"]["variantId"], VARIANT_ID)
        self.assertEqual(models.contexts[0]["cart_lines"][0]["name"], "Áo thun")

    async def test_relative_quantity_update_uses_the_current_line(self):
        models = OrderModels(OrderDecision(action="update", line_index=1, quantity=2, confidence=0.9))
        result = await order_agent(models).prepare_cart(order_state("thêm 1 cái nữa", "cart_update"))
        self.assertEqual(result["pending_action"]["payload"]["quantity"], 2)
        self.assertEqual(models.contexts[0]["cart_lines"][0]["quantity"], 1)

    async def test_payment_method_comes_from_the_semantic_plan(self):
        current = order_state("thanh toán khi nhận hàng giúp mình", "checkout", product_id=None, payment_method="cod")
        result = await order_agent(OrderModels()).prepare_checkout(current)
        self.assertEqual(result["tool_result"]["paymentMethod"], "cod")


class SupervisorRoutingTests(unittest.IsolatedAsyncioTestCase):
    def graph(self, models, **settings):
        return AgenticShoppingGraph(
            AgenticSettings(gemini_api_key="test", **settings),
            models, FakeRetriever(), FakeMarketplace(), checkpointer=MemorySaver(),
        )

    async def test_llm_first_asks_the_model_even_for_a_parseable_search(self):
        models = JudgeModels(search_turn("tai nghe bluetooth"), grades={PRODUCT_ID: 3})
        result = await self.graph(models).understand(state("tìm tai nghe bluetooth dưới 500k"))
        self.assertEqual(models.decide_calls, 1)
        self.assertNotIn("PARSED_SEARCH", result["warnings"])

    async def test_model_failure_still_uses_the_rule_fast_path(self):
        class Down(JudgeModels):
            async def decide(self, *_args, **_kwargs):
                raise TimeoutError()

        current = state("xl")
        current["active_product_id"] = PRODUCT_ID
        result = await self.graph(Down()).understand(current)
        self.assertIn("MODEL_UNAVAILABLE", result["warnings"])
        self.assertEqual(result["semantic_turn"]["tasks"][0]["intent"], "product_detail")

    async def test_cart_removal_is_routed_to_the_order_agent_without_a_reference(self):
        turn = SemanticTurn(tasks=[SemanticTask(intent="cart_remove")], confidence=0.95)
        planned = await self.graph(JudgeModels(turn)).plan({**state("bỏ cái áo"), "semantic_turn": turn.model_dump()})
        self.assertEqual(planned["plan"]["intent"], "cart_remove")
        self.assertEqual(AgenticShoppingGraph._main_route({**planned}), "prepare_cart")

    async def test_order_id_and_payment_are_planned(self):
        graph = self.graph(JudgeModels())
        turn = SemanticTurn(tasks=[SemanticTask(intent="order_status", order_id=42)], confidence=0.95)
        planned = await graph.plan({**state("đơn 42 tới đâu rồi"), "semantic_turn": turn.model_dump()})
        self.assertEqual(planned["plan"]["order_id"], 42)
        turn = SemanticTurn(tasks=[SemanticTask(intent="checkout", constraints=[
            SemanticConstraint(key="payment_method", value="bank_transfer")])], confidence=0.95)
        planned = await graph.plan({**state("chuyển khoản nhé"), "semantic_turn": turn.model_dump()})
        self.assertEqual(planned["plan"]["payment_method"], "bank_transfer")
        self.assertEqual(planned["plan"]["filters"]["spec_constraints"], [])

    async def test_variant_answer_is_written_by_the_model_from_verified_facts(self):
        from test_graph import BASIC_ID, VariantMarketplace

        class Models(JudgeModels):
            pass

        turn = SemanticTurn(
            tasks=[SemanticTask(intent="product_detail", references=[SemanticReference(kind="active")],
                                requested_attributes=["size"])],
            conversation_action="continue", confidence=0.95,
        )
        models = Models(turn)
        graph = AgenticShoppingGraph(
            AgenticSettings(gemini_api_key="test"), models, FakeRetriever(), VariantMarketplace(),
            checkpointer=MemorySaver(),
        )
        current = state("màu đen có size XL không")
        current["focused_products"] = [{"id": BASIC_ID, "name": "Áo Thun Nam Dream Team"}]
        current["active_product_id"] = BASIC_ID
        result = await graph.graph.ainvoke(current, config={"configurable": {"thread_id": "facts"}})
        self.assertEqual(result["answer"], "LLM trả lời về 1 sản phẩm.")
        self.assertIn("size XL", models.answer_payloads[-1]["verifiedFacts"])


class CategoryBranchTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_sees_the_tree_and_its_branch_is_used_exactly(self):
        women, men = "a" * 24, "b" * 24

        class TreeMarketplace(FakeMarketplace):
            async def categories(self):
                return [
                    {"id": "c" * 24, "name": "Thời trang", "parentId": None},
                    {"id": "d" * 24, "name": "Nữ", "parentId": "c" * 24},
                    {"id": "e" * 24, "name": "Nam", "parentId": "c" * 24},
                    {"id": women, "name": "Áo thun nữ", "parentId": "d" * 24},
                    {"id": men, "name": "Áo thun nam", "parentId": "e" * 24},
                ]

        class Models(JudgeModels):
            async def decide(self, *args, **kwargs):
                self.seen_paths = kwargs.get("category_paths")
                return search_turn("áo thun", constraints=[
                    SemanticConstraint(key="category_path", value="Thời trang › Nữ › Áo thun nữ")])

        models = Models()
        graph = AgenticShoppingGraph(
            AgenticSettings(gemini_api_key="test"), models, FakeRetriever(), TreeMarketplace(),
            checkpointer=MemorySaver(),
        )
        understood = await graph.understand(state("áo thun cho vợ"))
        self.assertIn("Thời trang › Nữ › Áo thun nữ", models.seen_paths)
        planned = await graph.plan({**state("áo thun cho vợ"), **understood})
        self.assertEqual(planned["plan"]["filters"]["category_ids"], [women])

    async def test_a_picked_branch_keeps_same_kind_siblings_of_other_shops(self):
        muji, yody = "a" * 24, "b" * 24
        tree = build_catalog_tree([
            {"id": "c" * 24, "name": "Thời trang", "parentId": None},
            {"id": "d" * 24, "name": "Nữ", "parentId": "c" * 24},
            {"id": muji, "name": "Áo Thun", "parentId": "d" * 24},
            {"id": yody, "name": "Áo thun nữ", "parentId": "d" * 24},
            {"id": "e" * 24, "name": "Quần short nữ", "parentId": "d" * 24},
        ])
        filters = SearchFilters(category_path="Thời trang › Nữ › Áo Thun")
        self.assertEqual(AgenticShoppingGraph._resolve_categories(tree, filters), [muji, yody])

    def test_a_wrong_branch_is_relaxed_when_nothing_is_found(self):
        from app.conversation import _apply_relaxation, _next_relaxation

        filters = SearchFilters(category_ids=["a" * 24], category_path="Điện tử › Laptop", max_price=1_000_000)
        self.assertEqual(_next_relaxation(filters, []), "category")
        relaxed = _apply_relaxation(filters, "category")
        self.assertEqual((relaxed.category_ids, relaxed.category_path, relaxed.max_price), ([], None, 1_000_000))
        self.assertEqual(_next_relaxation(relaxed, ["category"]), "price")



WOBURN = "4" * 24
REZO = "5" * 24
REZO_PRO = "6" * 24


class NamedRetriever(FakeRetriever):
    async def search(self, query, filters, limit=None, sort_by="relevance"):
        self.calls.append((query, filters.model_dump(), limit, sort_by))
        return [
            {"productId": REZO_PRO, "payload": {"text": "Tên sản phẩm: Loa Bluetooth Rezo Play Pro 2\nGiá"}},
            {"productId": REZO, "payload": {"text": "Tên sản phẩm: Loa Bluetooth Rezo Play\nGiá"}},
            {"productId": CASE, "payload": {"text": "Tên sản phẩm: Loa Bluetooth Marshall Acton IV"}},
        ]


class ConversationFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_compare_with_a_product_not_on_screen_looks_it_up(self):
        turn = SemanticTurn(
            tasks=[SemanticTask(intent="compare_products", requested_attributes=["price"], references=[
                SemanticReference(kind="name", name="loa bluetooth rezo play"),
                SemanticReference(kind="focused_index", index=1),
            ])],
            conversation_action="continue", confidence=0.9,
        )
        graph = AgenticShoppingGraph(
            AgenticSettings(gemini_api_key="test"), JudgeModels(turn), NamedRetriever(),
            FakeMarketplace(), checkpointer=MemorySaver(),
        )
        current = {**state("so với loa bluetooth rezo play thì cái nào rẻ hơn"), "semantic_turn": turn.model_dump()}
        current["focused_products"] = [{"id": WOBURN, "name": "Loa Bluetooth Marshall Woburn III"}]
        planned = await graph.plan(current)
        self.assertEqual(planned["plan"]["intent"], "product_search")
        self.assertEqual(sorted(planned["plan"]["product_ids"]), sorted([WOBURN, REZO]))
        self.assertFalse(planned["plan"].get("clarification"))

    async def test_named_product_is_compared_with_the_list_on_screen(self):
        turn = SemanticTurn(
            tasks=[SemanticTask(intent="compare_products", references=[
                SemanticReference(kind="active"),
                SemanticReference(kind="name", name="loa bluetooth rezo play"),
            ])],
            conversation_action="continue", confidence=0.9,
        )
        graph = AgenticShoppingGraph(
            AgenticSettings(gemini_api_key="test"), JudgeModels(turn), NamedRetriever(),
            FakeMarketplace(), checkpointer=MemorySaver(),
        )
        current = {**state("so với rezo play thì cái nào rẻ hơn"), "semantic_turn": turn.model_dump()}
        current["focused_products"] = [
            {"id": WOBURN, "name": "Loa Bluetooth Marshall Woburn III"},
            {"id": PHONE, "name": "Loa Bluetooth Marshall Emberton II"},
        ]
        planned = await graph.plan(current)
        self.assertEqual(planned["plan"]["intent"], "product_search")
        self.assertEqual(planned["plan"]["product_ids"], [REZO, WOBURN, PHONE])

    async def test_unknown_name_still_asks_which_product(self):
        turn = SemanticTurn(
            tasks=[SemanticTask(intent="compare_products", references=[
                SemanticReference(kind="name", name="loa sony xb100"),
                SemanticReference(kind="active"),
            ])],
            conversation_action="continue", confidence=0.9,
        )
        graph = AgenticShoppingGraph(
            AgenticSettings(gemini_api_key="test"), JudgeModels(turn), NamedRetriever(),
            FakeMarketplace(), checkpointer=MemorySaver(),
        )
        current = {**state("so với loa sony xb100"), "semantic_turn": turn.model_dump(),
                   "active_product_id": WOBURN}
        planned = await graph.plan(current)
        self.assertEqual(planned["plan"]["intent"], "general")

    def test_attribute_question_drops_the_previous_search_filters(self):
        carried = [
            SemanticConstraint(key="color", value="trắng"),
            SemanticConstraint(key="size", value="L"),
            SemanticConstraint(key="product_type", value="áo thun nam"),
        ]
        task = SemanticTask(intent="product_search", requested_attributes=["color"], constraints=carried)
        guarded = AgenticShoppingGraph._detail_task_guard(task, [WOBURN], "mẫu basic có mấy màu")
        self.assertEqual(guarded.intent, "product_detail")
        self.assertEqual([item.key for item in guarded.constraints], ["product_type"])
        # A colour/size the user says in this turn is a real variant question.
        asked = SemanticTask(intent="product_detail", requested_attributes=["size"], constraints=carried)
        kept = AgenticShoppingGraph._detail_task_guard(asked, [WOBURN], "màu trắng có size L không")
        self.assertEqual(len(kept.constraints), 3)

    def test_yes_to_more_info_gives_the_overview_not_the_same_attribute(self):
        history = [
            {"role": "user", "content": "mẫu basic có mấy màu"},
            {"role": "assistant", "content": "Có 6 màu. Bạn có muốn xem thêm thông tin về sản phẩm này không?"},
        ]
        task = SemanticTask(intent="product_detail", requested_attributes=["color"])
        guarded = AgenticShoppingGraph._detail_task_guard(task, [WOBURN], "có", history)
        self.assertEqual(guarded.requested_attributes, ["specification"])
        # "có" to an offer about sizes keeps the size question.
        history[0]["content"] = "mẫu basic có màu đen không"
        sized = SemanticTask(intent="product_detail", requested_attributes=["size"])
        self.assertEqual(
            AgenticShoppingGraph._detail_task_guard(sized, [WOBURN], "có", history).requested_attributes, ["size"]
        )

    def test_comparison_price_differences_are_computed_not_left_to_the_model(self):
        facts = GeminiGateway._price_facts(
            {"product_ids": [WOBURN, REZO]},
            [{"name": "Woburn III", "price": 15990000}, {"name": "Rezo Play", "price": 490000}],
        )
        self.assertEqual(facts, ["Rẻ nhất: Rezo Play (490.000đ)",
                                 "Woburn III (15.990.000đ) đắt hơn Rezo Play 15.500.000đ"])
        self.assertIsNone(GeminiGateway._price_facts({"product_ids": []}, [{"price": 1}, {"price": 2}]))

    def test_missing_catalog_attributes_are_named_for_web_lookup(self):
        card = {"name": "Loa Woburn III", "variants": [{"id": None, "name": "Loa Woburn III"}],
                "specifications": [{"name": "Tổng công suất", "value": "150 W"}]}
        self.assertEqual(ProductAgent._missing_attributes(["color", "specification", "price"], card), ["màu sắc"])
        card["variants"] = [{"id": VARIANT_ID, "name": "Đen"}]
        self.assertEqual(ProductAgent._missing_attributes(["color"], card), [])

    def test_turn_history_keeps_the_offer_at_the_end_of_a_long_reply(self):
        reply = "Thông số: " + "x" * 900 + " Bạn có muốn xem thêm các mẫu loa Marshall khác không?"
        compact = GeminiGateway._dialogue_history([{"role": "assistant", "content": reply}], 6)
        self.assertIn("loa Marshall khác không?", compact[0]["content"])
        self.assertTrue(compact[0]["content"].startswith("Thông số:"))

if __name__ == "__main__":
    unittest.main()
