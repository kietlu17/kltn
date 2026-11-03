import unittest

from app.config import AgenticSettings
from app.models import GeminiGateway, gemini_response_schema
from app.schemas import (
    AgentPlan,
    CandidateVerification,
    SemanticTurn,
    TurnUnderstanding,
    VerificationBatch,
)


def keywords(node, found=None):
    found = set() if found is None else found
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            keywords(value, found)
    elif isinstance(node, list):
        for value in node:
            keywords(value, found)
    return found


class FakeRunnable:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    async def ainvoke(self, _messages):
        self.calls += 1
        result = self.outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class StructuredOutputTests(unittest.IsolatedAsyncioTestCase):
    def test_response_schemas_drop_only_keywords_gemini_rejects(self):
        for schema in (SemanticTurn, TurnUnderstanding, AgentPlan, VerificationBatch):
            found = keywords(gemini_response_schema(schema))
            self.assertNotIn("maxItems", found)
            self.assertNotIn("minItems", found)
        self.assertIn("pattern", keywords(gemini_response_schema(VerificationBatch)))

    async def test_list_limits_removed_from_the_schema_are_still_validated(self):
        gateway = GeminiGateway(AgenticSettings(gemini_api_key="test"))
        too_many = {
            "results": [
                CandidateVerification(productId="1" * 24, verdict="match").model_dump()
            ] * 31
        }
        gateway._structured_runnables[VerificationBatch] = FakeRunnable([too_many])
        with self.assertRaises(ValueError):
            await gateway._structured("verify", 5, [], VerificationBatch)

    async def test_decide_retries_once_on_transient_provider_error(self):
        gateway = GeminiGateway(AgenticSettings(gemini_api_key="test"))
        turn = {"tasks": [{"intent": "product_search", "query": "loa"}], "confidence": 0.9}
        runnable = FakeRunnable([RuntimeError("503 UNAVAILABLE"), turn])
        gateway._structured_runnables[SemanticTurn] = runnable
        result = await gateway._structured("decide", 5, [], SemanticTurn)
        self.assertEqual(result.tasks[0].query, "loa")
        self.assertEqual(runnable.calls, 2)


if __name__ == "__main__":
    unittest.main()
