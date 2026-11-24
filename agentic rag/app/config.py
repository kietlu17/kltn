import hashlib
import os
from urllib.parse import urlsplit
from dataclasses import dataclass, field

from dotenv import load_dotenv


load_dotenv()


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    return max(minimum, min(maximum, value))


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    value = float(os.getenv(name, str(default)))
    return max(minimum, min(maximum, value))


def _llm_api_key() -> str:
    """gpt_key is an OpenAI key: never send it to a third-party gateway."""
    key = os.getenv("AGENTIC_LLM_API_KEY", "").strip()
    host = urlsplit(os.getenv("AGENTIC_LLM_BASE_URL", "").strip()).hostname
    return key or (os.getenv("gpt_key", "").strip() if host == "api.openai.com" else "")


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
        default_factory=_llm_api_key, repr=False
    )
    llm_model: str = field(default_factory=lambda: os.getenv("AGENTIC_LLM_MODEL", "").strip())
    reasoning_effort: str = field(
        default_factory=lambda: os.getenv("AGENTIC_REASONING_EFFORT", "none").strip()
    )
    # A stronger model for turn understanding (plan) only; answers, ranking
    # and order resolution keep llm_model. Same OpenAI-compatible gateway.
    decide_model: str = field(default_factory=lambda: os.getenv("AGENTIC_DECIDE_MODEL", "").strip())
    decide_reasoning_effort: str = field(
        default_factory=lambda: os.getenv("AGENTIC_DECIDE_REASONING_EFFORT", "").strip()
    )

    # The model that writes the reply the customer reads. Empty keeps the chat
    # model; a stronger one here changes how the assistant sounds far more
    # than it changes cost, since it runs once per turn.
    answer_model: str = field(default_factory=lambda: os.getenv("AGENTIC_ANSWER_MODEL", "").strip())
    # Classification, ranking and verification stay at 0; the reply uses the
    # temperature Gemini 3 models are tuned for (1.0) so it does not read canned.
    answer_temperature: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_ANSWER_TEMPERATURE", 1.0, 0, 2)
    )
    # "graph": every turn runs the fixed pipeline. "hybrid": advice turns
    # (search, compare, multi-part questions) are run by a tool-calling
    # advisor that decides what to look up; cart, checkout, orders and policy
    # stay on the graph, and a failed advisor turn falls back to it.
    agentic_mode: str = field(
        default_factory=lambda: os.getenv("AGENTIC_MODE", "graph").strip().casefold()
    )
    # Tool-calling model of the advisor; empty uses the answer model.
    advisor_model: str = field(default_factory=lambda: os.getenv("AGENTIC_ADVISOR_MODEL", "").strip())
    advisor_max_steps: int = field(
        default_factory=lambda: _bounded_int("AGENTIC_ADVISOR_MAX_STEPS", 4, 1, 8)
    )
    advisor_step_timeout: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_ADVISOR_STEP_TIMEOUT_SECONDS", 12, 2, 60)
    )
    # Messages (user + assistant) the reply model reads as the conversation.
    answer_history_messages: int = field(
        default_factory=lambda: _bounded_int("AGENTIC_ANSWER_HISTORY_MESSAGES", 16, 2, 40)
    )
    # Session memory. The transcript keeps at most history_max messages;
    # beyond that the oldest are folded into a rolling summary until only
    # history_keep remain, so a summary call runs every few turns, not each.
    history_keep_messages: int = field(
        default_factory=lambda: _bounded_int("AGENTIC_HISTORY_KEEP_MESSAGES", 12, 4, 40)
    )
    history_max_messages: int = field(
        default_factory=lambda: _bounded_int("AGENTIC_HISTORY_MAX_MESSAGES", 20, 6, 60)
    )
    summary_enabled: bool = field(
        default_factory=lambda: os.getenv("AGENTIC_SUMMARY_ENABLED", "true").strip().casefold()
        in {"1", "true", "yes", "on"}
    )
    summary_timeout: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_SUMMARY_TIMEOUT_SECONDS", 15, 2, 60)
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
            "AGENTIC_TURN_DEADLINE_SECONDS", 15, 3, 120
        )
    )
    max_llm_calls: int = field(
        default_factory=lambda: _bounded_int("AGENTIC_MAX_LLM_CALLS", 6, 1, 12)
    )
    # LLM-first: every turn is decided, ranked and answered by the model; the
    # deterministic parsers, fast path and templates only run when the model
    # fails or the turn budget is spent. false restores the latency-first
    # mode (rule fast path, hedged parse, template answers).
    llm_first: bool = field(
        default_factory=lambda: os.getenv("AGENTIC_LLM_FIRST", "true").strip().casefold()
        in {"1", "true", "yes", "on"}
    )
    # Product agent web search (Gemini grounded Google Search) for questions
    # the catalog cannot answer. It always uses the Gemini key.
    web_search_enabled: bool = field(
        default_factory=lambda: os.getenv("AGENTIC_WEB_SEARCH", "true").strip().casefold()
        in {"1", "true", "yes", "on"}
    )
    web_search_model: str = field(
        default_factory=lambda: os.getenv("AGENTIC_WEB_SEARCH_MODEL", "").strip()
    )
    # "gemini": grounded Google Search with the Gemini key (sources cited).
    # "gateway": the OpenAI-compatible gateway model answers from its own
    # knowledge (no live search, no sources) when the Gemini key has no quota.
    web_search_provider: str = field(
        default_factory=lambda: os.getenv("AGENTIC_WEB_SEARCH_PROVIDER", "gemini").strip().casefold()
    )
    web_search_timeout: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_WEB_SEARCH_TIMEOUT_SECONDS", 7, 1, 60)
    )
    decide_timeout: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_DECIDE_TIMEOUT_SECONDS", 4, 1, 60)
    )
    # With a separate (slower) decide model: after this many seconds without
    # an answer, the default chat model is asked too and the first valid
    # turn wins, so a slow gateway never drops the turn to the rule parser.
    decide_fallback_after: float = field(
        default_factory=lambda: _bounded_float(
            "AGENTIC_DECIDE_FALLBACK_AFTER_SECONDS", 2.5, 0, 60
        )
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
        default_factory=lambda: _bounded_float("AGENTIC_ANSWER_TIMEOUT_SECONDS", 8, 1, 60)
    )
    embed_timeout: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_EMBED_TIMEOUT_SECONDS", 3, 0.5, 30)
    )
    retrieval_limit: int = field(
        default_factory=lambda: _bounded_int("AGENTIC_RETRIEVAL_LIMIT", 30, 6, 100)
    )
    # Top-k products shown per search, after re-ranking.
    result_limit: int = field(
        default_factory=lambda: _bounded_int("AGENTIC_RESULT_LIMIT", 5, 1, 12)
    )
    # Local model server (CLIP image embeddings + cross-encoder re-ranker).
    model_server_url: str = field(
        default_factory=lambda: os.getenv(
            "AGENTIC_MODEL_SERVER_URL", "http://image-embedding:3022"
        ).strip()
    )
    rerank_enabled: bool = field(
        default_factory=lambda: os.getenv("AGENTIC_RERANK", "true").strip().casefold()
        in {"1", "true", "yes", "on"}
    )
    # Hybrid search returns this many candidates; the cross-encoder keeps top-k.
    rerank_candidates: int = field(
        default_factory=lambda: _bounded_int("AGENTIC_RERANK_CANDIDATES", 20, 2, 50)
    )
    rerank_timeout: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_RERANK_TIMEOUT_SECONDS", 2, 0.2, 30)
    )
    # llm: the cross-encoder pre-sorts, then the chat model grades the short
    #      list against the need (and ambiguous specs) and decides the top-k.
    # cross_encoder: blended cross-encoder score with an adaptive cut-off.
    # off: hybrid order only.
    rerank_mode: str = field(
        default_factory=lambda: os.getenv("AGENTIC_RERANK_MODE", "llm").strip().casefold()
    )
    llm_rerank_candidates: int = field(
        default_factory=lambda: _bounded_int("AGENTIC_LLM_RERANK_CANDIDATES", 10, 3, 20)
    )
    rank_timeout: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_RANK_TIMEOUT_SECONDS", 4, 1, 60)
    )
    # Share of the final cross-encoder score taken from its own probability;
    # the rest comes from the hybrid (dense + BM25) rank.
    rerank_weight: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_RERANK_WEIGHT", 0.75, 0, 1)
    )
    # Cross-encoder top-k keeps candidates scoring at least this share of the
    # best one, so a clear winner is not padded with unrelated products.
    rerank_relative_cutoff: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_RERANK_RELATIVE_CUTOFF", 0.3, 0, 1)
    )
    image_model: str = field(
        default_factory=lambda: os.getenv("AGENTIC_IMAGE_MODEL", "openai/clip-vit-base-patch32")
    )
    image_revision: str = field(
        default_factory=lambda: os.getenv(
            "AGENTIC_IMAGE_REVISION", "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"
        )
    )
    image_min_score: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_IMAGE_MIN_SCORE", 0.65, 0, 1)
    )
    image_timeout: float = field(
        default_factory=lambda: _bounded_float("AGENTIC_IMAGE_TIMEOUT_SECONDS", 10, 1, 120)
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

