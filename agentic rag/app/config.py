import hashlib
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


load_dotenv()


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    return max(minimum, min(maximum, value))


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    value = float(os.getenv(name, str(default)))
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class AgenticSettings:
    semantic_decision_v2: bool = field(
        default_factory=lambda: os.getenv(
            "AGENTIC_SEMANTIC_DECISION_V2", "true"
        ).strip().casefold() in {"1", "true", "yes", "on"}
    )
    gemini_api_key: str = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip(), repr=False
    )
    gemini_model: str = field(
        default_factory=lambda: os.getenv("AGENTIC_GEMINI_MODEL", "gemini-3.5-flash-lite")
    )
    # Chat model provider: "gemini" (Google API) or "openai" (any
    # OpenAI-compatible gateway). Embeddings always stay on Gemini so the
    # catalog index does not have to be rebuilt.
    llm_provider: str = field(
        default_factory=lambda: os.getenv("AGENTIC_LLM_PROVIDER", "gemini").strip().casefold()
    )
    llm_base_url: str = field(default_factory=lambda: os.getenv("AGENTIC_LLM_BASE_URL", "").strip())
    llm_api_key: str = field(
        default_factory=lambda: os.getenv("AGENTIC_LLM_API_KEY", "").strip(), repr=False
    )
    llm_model: str = field(default_factory=lambda: os.getenv("AGENTIC_LLM_MODEL", "").strip())
    reasoning_effort: str = field(
        default_factory=lambda: os.getenv("AGENTIC_REASONING_EFFORT", "none").strip()
    )

    @property
    def chat_model(self) -> str:
        return self.llm_model if self.llm_provider == "openai" and self.llm_model else self.gemini_model
    embedding_model: str = field(
        default_factory=lambda: os.getenv("AGENTIC_EMBEDDING_MODEL", "gemini-embedding-001")
    )
    embedding_dimensions: int = field(
        default_factory=lambda: _bounded_int(
            "AGENTIC_EMBEDDING_DIMENSIONS", 768, 128, 4096
        )
    )
    qdrant_url: str = field(
        default_factory=lambda: os.getenv("QDRANT_URL", "http://localhost:6333")
    )
    qdrant_collection_override: str = field(
        default_factory=lambda: os.getenv("AGENTIC_QDRANT_COLLECTION", "").strip()
    )
    product_url: str = field(
        default_factory=lambda: os.getenv(
            "PRODUCT_SERVICE_URL", "http://localhost:3004"
        ).rstrip("/")
    )
    inventory_url: str = field(
        default_factory=lambda: os.getenv(
            "INVENTORY_SERVICE_URL", "http://localhost:3007"
        ).rstrip("/")
    )
    review_url: str = field(
        default_factory=lambda: os.getenv(
            "REVIEW_SERVICE_URL", "http://localhost:3008"
        ).rstrip("/")
    )
    cart_url: str = field(
        default_factory=lambda: os.getenv(
            "CART_SERVICE_URL", "http://localhost:3005"
        ).rstrip("/")
    )
    order_url: str = field(
        default_factory=lambda: os.getenv(
            "ORDER_SERVICE_URL", "http://localhost:3006"
        ).rstrip("/")
    )
    voucher_url: str = field(
        default_factory=lambda: os.getenv(
            "VOUCHER_SERVICE_URL", "http://localhost:3013"
        ).rstrip("/")
    )
    user_url: str = field(
        default_factory=lambda: os.getenv(
            "USER_SERVICE_URL", "http://localhost:3002"
        ).rstrip("/")
    )
    data_dir: str = field(
        default_factory=lambda: os.getenv("AGENTIC_DATA_DIR", "./data")
    )
    request_timeout: float = field(
        default_factory=lambda: _bounded_float(
            "AGENTIC_REQUEST_TIMEOUT_SECONDS", 30, 1, 180
        )
    )
    model_timeout: float = field(
        default_factory=lambda: _bounded_float(
            "AGENTIC_MODEL_TIMEOUT_SECONDS", 90, 5, 300
        )
    )
    thinking_level: str = field(
        default_factory=lambda: os.getenv("AGENTIC_THINKING_LEVEL", "minimal").strip()
    )
    turn_deadline: float = field(
        default_factory=lambda: _bounded_float(
            "AGENTIC_TURN_DEADLINE_SECONDS", 8, 3, 120
        )
    )
    max_llm_calls: int = field(
        default_factory=lambda: _bounded_int("AGENTIC_MAX_LLM_CALLS", 4, 1, 10)
    )
    decide_timeout: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_DECIDE_TIMEOUT_SECONDS", 4, 1, 60)
    )
    # How long a plain search waits for the semantic model before it runs
    # on the deterministic parse instead.
    decide_hedge: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_DECIDE_HEDGE_SECONDS", 1.5, 0, 30)
    )
    verify_timeout: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_VERIFY_TIMEOUT_SECONDS", 3, 1, 60)
    )
    answer_timeout: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_ANSWER_TIMEOUT_SECONDS", 4, 1, 60)
    )
    embed_timeout: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_EMBED_TIMEOUT_SECONDS", 3, 0.5, 30)
    )
    retrieval_limit: int = field(
        default_factory=lambda: _bounded_int("AGENTIC_RETRIEVAL_LIMIT", 30, 6, 100)
    )
    result_limit: int = field(
        default_factory=lambda: _bounded_int("AGENTIC_RESULT_LIMIT", 6, 1, 12)
    )
    min_score: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_MIN_SCORE", 0.35, 0, 1)
    )
    max_retrieval_rounds: int = field(
        default_factory=lambda: _bounded_int(
            "AGENTIC_MAX_RETRIEVAL_ROUNDS", 2, 1, 3
        )
    )
    session_ttl: int = field(
        default_factory=lambda: _bounded_int(
            "AGENTIC_SESSION_TTL_SECONDS", 86400, 300, 604800
        )
    )
    action_ttl: int = field(
        default_factory=lambda: _bounded_int(
            "AGENTIC_ACTION_TTL_SECONDS", 600, 60, 3600
        )
    )

    @property
    def collection(self) -> str:
        if self.qdrant_collection_override:
            return self.qdrant_collection_override
        # Owned by app.indexer; a distinct identity keeps chatbot-service's
        # indexer from ever writing the same collection.
        identity = (
            f"agentic-v1:gemini:{self.embedding_model}:"
            f"{self.embedding_dimensions}:chunked-hybrid"
        )
        return f"catalog_{hashlib.sha256(identity.encode()).hexdigest()[:12]}"

