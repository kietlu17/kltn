import unittest
from types import SimpleNamespace

from app.graph import AgenticShoppingGraph
from app.retrieval import StructuredProductRetriever
from app.schemas import (
    AgentPlan,
    CandidateVerification,
    SemanticConstraint,
    SemanticReference,
    SemanticTask,
    SemanticTurn,
    VerificationBatch,
)
from app.specs import normalize_specifications, verify_spec_constraints


FIRST = "1" * 24
SECOND = "2" * 24


class SemanticRegressionTests(unittest.IsolatedAsyncioTestCase):
    def test_laptop_weight_is_grounded_in_specs_not_clothing_size(self):
        state = {
            "semantic_turn": SemanticTurn(
                tasks=[
                    SemanticTask(
                        intent="product_detail",
                        references=[SemanticReference(kind="focused_index", index=1)],
                        requested_attributes=["battery_life", "weight"],
                    )
                ],
                conversation_action="continue",
                confidence=0.98,
            ).model_dump(),
            "products": [
                {
                    "id": FIRST,
                    "name": "Laptop mẫu đầu",
                    "price": 15000000,
                    "variants": [{"name": "Mặc định", "availableStock": 2}],
                    "specifications": [
                        {"name": "Trọng lượng", "value": "1.62 kg"},
                        {"name": "Pin", "value": "47 Wh"},
                    ],
                }
            ],
        }
        answer = AgenticShoppingGraph._product_attribute_answer(state)
        self.assertIn("Trọng lượng: 1.62 kg", answer)
        # Missing specs are named in plain language, never as internal keys.
        self.assertIn("chưa có trong thông số", answer)
        self.assertNotIn("battery_life", answer)
        self.assertNotIn("bảng size", answer)

    def test_compare_resolves_stable_display_ordinals(self):
        task = SemanticTask(
            intent="compare_products",
            references=[
                SemanticReference(kind="focused_index", index=1),
                SemanticReference(kind="focused_index", index=2),
            ],
        )
        resolved = AgenticShoppingGraph._semantic_references(
            task,
            {
                "focused_products": [
                    {"id": FIRST, "name": "Mẫu đầu"},
                    {"id": SECOND, "name": "Mẫu thứ hai"},
                ]
            },
        )
        self.assertEqual(resolved, [FIRST, SECOND])

    async def test_low_confidence_fails_closed_without_product_search(self):
        class Models:
            async def decide(self, *_args, **_kwargs):
                return SemanticTurn(
                    tasks=[SemanticTask(intent="product_search", query="xyzxyz")],
                    confidence=0.2,
                )

        agent = object.__new__(AgenticShoppingGraph)
        agent.models = Models()
        understood = await agent.understand(
            {
                "message": "xyzxyz 123 ???",
                "history": [],
                "focused_products": [],
                "selected_options": {},
                "shopping_phase": "exploring",
                "warnings": [],
            }
        )
        turn = SemanticTurn.model_validate(understood["semantic_turn"])
        self.assertTrue(turn.needs_clarification)
        self.assertEqual(turn.conversation_action, "clarify")
        self.assertIn("LOW_CONFIDENCE", understood["warnings"])

    async def test_untyped_semantic_search_rejects_wrong_product_kind(self):
        class Retriever:
            async def search(self, *_args, **_kwargs):
                return [{"productId": FIRST, "vectorScore": 0.9}]

        class Marketplace:
            async def hydrate_products(self, *_args, **_kwargs):
                return [{"id": FIRST, "name": "Loa Bluetooth", "specifications": []}]

        class Models:
            async def verify_candidates(self, _query, constraints, _products):
                self.seen_scope = any(
                    item["key"] == "semantic_product_scope" for item in constraints
                )
                return VerificationBatch(
                    results=[
                        CandidateVerification(
                            productId=FIRST,
                            verdict="no_match",
                            evidence=["Tên sản phẩm: Loa Bluetooth"],
                        )
                    ]
                )

        agent = object.__new__(AgenticShoppingGraph)
        agent.settings = SimpleNamespace(
            retrieval_limit=30, result_limit=6, max_retrieval_rounds=2
        )
        agent.retriever = Retriever()
        agent.marketplace = Marketplace()
        agent.models = Models()
        result = await agent.retrieve(
            {
                "query": "điện thoại dưới 5 triệu",
                "message": "Tìm điện thoại dưới 5 triệu",
                "plan": AgentPlan(query="điện thoại dưới 5 triệu").model_dump(),
                "semantic_turn": SemanticTurn(
                    tasks=[
                        SemanticTask(
                            intent="product_search", query="điện thoại dưới 5 triệu"
                        )
                    ],
                    confidence=0.98,
                ).model_dump(),
                "retrieval_rounds": 0,
            }
        )
        # Scope alone is settled on product names without a model call.
        self.assertFalse(hasattr(agent.models, "seen_scope"))
        self.assertEqual(result["products"], [])
        self.assertEqual(result["tool_result"]["found"], 0)

    def test_hard_numeric_specs_require_evidence(self):
        constraint = SemanticConstraint(
            key="ram", operator="gte", value=16, unit="GB", strength="hard"
        )
        match = verify_spec_constraints(
            {"specifications": [{"name": "RAM", "value": "16 GB"}]},
            [constraint],
        )
        unknown = verify_spec_constraints({"specifications": []}, [constraint])
        self.assertEqual(match.verdict, "match")
        self.assertEqual(unknown.verdict, "unknown")

    def test_nested_qdrant_filter_keeps_spec_key_and_value_together(self):
        from app.schemas import SearchFilters

        query_filter = StructuredProductRetriever._build_filter(
            SearchFilters(
                spec_constraints=[
                    SemanticConstraint(
                        key="battery_capacity",
                        operator="gte",
                        value=5000,
                        unit="mAh",
                    )
                ]
            )
        )
        nested = [item for item in query_filter.must if item.__class__.__name__ == "NestedCondition"]
        self.assertEqual(len(nested), 1)
        self.assertEqual(nested[0].nested.key, "specs")

    def test_spec_normalization_preserves_raw_evidence(self):
        facts = normalize_specifications(
            [
                {"name": "Ổ cứng", "value": "SSD 1 TB"},
                {"name": "Trọng lượng", "value": "1650 g"},
            ]
        )
        self.assertEqual(facts[0]["numericValue"], 1024)
        self.assertEqual(facts[0]["unit"], "GB")
        self.assertEqual(facts[1]["numericValue"], 1.65)
        self.assertEqual(facts[1]["rawValue"], "1650 g")

    def test_battery_energy_is_not_mislabeled_as_capacity(self):
        facts = normalize_specifications([{"name": "Pin", "value": "47 Wh"}])
        self.assertEqual(facts[0]["key"], "battery_energy")
        self.assertEqual(facts[0]["numericValue"], 47)
        self.assertEqual(facts[0]["unit"], "Wh")


if __name__ == "__main__":
    unittest.main()
