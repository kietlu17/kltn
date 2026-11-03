from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langgraph.channels import UntrackedValue
from pydantic import BaseModel, Field, model_validator


Intent = Literal[
    "browse_categories",
    "product_search",
    "product_detail",
    "cart_view",
    "cart_add",
    "cart_update",
    "cart_remove",
    "checkout",
    "order_status",
    "policy",
    "clarify",
    "out_of_scope",
    "multi",
    "general",
]

ShoppingPhase = Literal["exploring", "detailing", "narrowing", "selling"]
SortBy = Literal["relevance", "price_asc", "price_desc"]
SearchMode = Literal["standard", "similar", "refine"]
DialogueAct = Literal[
    "unknown",
    "new_search",
    "browse_catalog",
    "ask_attribute",
    "select_variant",
    "compare_products",
    "size_advice",
    "purchase",
    "cart_operation",
    "checkout",
    "order_status",
    "confirmation",
    "general",
]

SemanticIntent = Literal[
    "browse_categories",
    "product_search",
    "product_detail",
    "compare_products",
    "policy",
    "cart_view",
    "cart_add",
    "cart_update",
    "cart_remove",
    "checkout",
    "order_status",
    "general",
    "clarify",
    "out_of_scope",
]


class SemanticReference(BaseModel):
    kind: Literal["active", "focused_index", "name"]
    index: int | None = Field(default=None, ge=1, le=20)
    name: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def validate_reference(self):
        if self.kind == "focused_index" and self.index is None:
            raise ValueError("focused_index requires index")
        if self.kind == "name" and not self.name.strip():
            raise ValueError("name reference requires name")
        self.name = self.name.strip()
        return self


class SemanticConstraint(BaseModel):
    key: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,100}$")
    operator: Literal["eq", "any", "lt", "lte", "gt", "gte", "contains"] = "eq"
    value: str | float | list[str]
    unit: str = Field(default="", max_length=30)
    strength: Literal["hard", "soft"] = "hard"
    source: Literal["explicit", "conversation", "inferred"] = "explicit"


class SemanticTask(BaseModel):
    intent: SemanticIntent
    query: str = Field(default="", max_length=1000)
    references: list[SemanticReference] = Field(default_factory=list, max_length=6)
    requested_attributes: list[str] = Field(default_factory=list, max_length=12)
    constraints: list[SemanticConstraint] = Field(default_factory=list, max_length=30)
    sort_by: SortBy = "relevance"
    result_limit: int | None = Field(default=None, ge=1, le=20)
    quantity: int = Field(default=1, ge=1, le=100)

    @model_validator(mode="after")
    def normalize_task(self):
        self.requested_attributes = list(
            dict.fromkeys(value.strip().casefold() for value in self.requested_attributes if value.strip())
        )
        return self


class SemanticTurn(BaseModel):
    tasks: list[SemanticTask] = Field(default_factory=list, min_length=1, max_length=3)
    conversation_action: Literal["new", "continue", "switch", "resume", "clarify"] = "new"
    focus_update: Literal["keep", "replace", "clear"] = "keep"
    confidence: float = Field(default=0, ge=0, le=1)
    needs_clarification: bool = False
    clarification_question: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_clarification(self):
        if self.needs_clarification and not self.clarification_question.strip():
            self.clarification_question = "Bạn có thể nói rõ hơn sản phẩm hoặc nhu cầu cần hỗ trợ không?"
        return self


class SearchFilters(BaseModel):
    category_id: str | None = Field(default=None, max_length=100)
    category_path: str | None = Field(default=None, max_length=300)
    category_ids: list[
        Annotated[str, Field(pattern=r"^[a-fA-F0-9]{24}$")]
    ] = Field(default_factory=list, max_length=1000)
    product_type: str | None = Field(default=None, max_length=80)
    audience: Literal["nam", "nu", "tre_em", "unisex"] | None = None
    brand: str | None = Field(default=None, max_length=100)
    colors: list[str] = Field(default_factory=list, max_length=8)
    sizes: list[str] = Field(default_factory=list, max_length=8)
    min_price: float | None = Field(default=None, ge=0, le=1e12)
    max_price: float | None = Field(default=None, ge=0, le=1e12)
    in_stock: bool = True
    exclude_product_ids: list[
        Annotated[str, Field(pattern=r"^[a-fA-F0-9]{24}$")]
    ] = Field(default_factory=list, max_length=50)
    spec_constraints: list[SemanticConstraint] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_prices(self):
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price must not exceed max_price")
        self.colors = list(dict.fromkeys(x.strip().casefold() for x in self.colors if x.strip()))
        self.sizes = list(dict.fromkeys(x.strip().upper() for x in self.sizes if x.strip()))
        self.exclude_product_ids = list(dict.fromkeys(self.exclude_product_ids))
        return self


class ConstraintDelta(BaseModel):
    key: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,100}$")
    action: Literal["set", "remove"] = "set"
    operator: Literal["eq", "any", "lt", "lte", "gt", "gte"] = "eq"
    value: str | float | list[str] | None = None
    strength: Literal["hard", "soft"] = "soft"


class SearchConstraint(BaseModel):
    key: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,100}$")
    operator: Literal["eq", "any", "lt", "lte", "gt", "gte"] = "eq"
    value: str | float | list[str]
    source: Literal[
        "explicit", "conversation", "anchor_product", "planner"
    ] = "conversation"
    strength: Literal["hard", "soft"] = "soft"


class SearchContext(BaseModel):
    mode: SearchMode = "standard"
    anchor_product_id: str | None = Field(
        default=None, pattern=r"^[a-fA-F0-9]{24}$"
    )
    anchor_product_name: str = Field(default="", max_length=300)
    semantic_query: str = Field(default="", max_length=1000)
    constraints: list[SearchConstraint] = Field(default_factory=list, max_length=40)
    exclude_product_ids: list[
        Annotated[str, Field(pattern=r"^[a-fA-F0-9]{24}$")]
    ] = Field(default_factory=list, max_length=50)
    relaxed_keys: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def normalize_context(self):
        by_key: dict[str, SearchConstraint] = {}
        for constraint in self.constraints:
            constraint.key = constraint.key.casefold()
            by_key[constraint.key] = constraint
        self.constraints = list(by_key.values())
        self.exclude_product_ids = list(dict.fromkeys(self.exclude_product_ids))
        self.relaxed_keys = list(dict.fromkeys(self.relaxed_keys))
        return self


class AgentPlan(BaseModel):
    intent: Intent = "product_search"
    query: str = Field(default="", max_length=1000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    product_id: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{24}$")
    product_ids: list[
        Annotated[str, Field(pattern=r"^[a-fA-F0-9]{24}$")]
    ] = Field(default_factory=list, max_length=6)
    variant_id: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{24}$")
    quantity: int = Field(default=1, ge=1, le=100)
    order_id: int | None = Field(default=None, ge=1)
    clarification: str = Field(default="", max_length=500)
    sort_by: SortBy = "relevance"
    result_limit: int | None = Field(default=None, ge=1, le=20)


class TurnUnderstanding(BaseModel):
    dialogue_act: DialogueAct = "unknown"
    refers_to_active_product: bool = False
    product_names: list[str] = Field(default_factory=list, max_length=6)
    colors: list[str] = Field(default_factory=list, max_length=8)
    sizes: list[str] = Field(default_factory=list, max_length=8)
    requested_attribute: Literal[
        "color", "size", "price", "stock", "fit", "specification", "other"
    ] | None = None
    confirmation: Literal["yes", "no"] | None = None
    sort_by: SortBy = "relevance"
    result_limit: int | None = Field(default=None, ge=1, le=20)
    search_mode: SearchMode = "standard"
    price_relation: Literal["cheaper", "more_expensive"] | None = None
    inherit_constraints: bool = False
    constraint_deltas: list[ConstraintDelta] = Field(default_factory=list, max_length=20)
    confidence: float = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def normalize_options(self):
        self.product_names = list(
            dict.fromkeys(value.strip() for value in self.product_names if value.strip())
        )
        self.colors = list(
            dict.fromkeys(value.strip().casefold() for value in self.colors if value.strip())
        )
        self.sizes = list(
            dict.fromkeys(value.strip().upper() for value in self.sizes if value.strip())
        )
        return self


class ProductVariant(BaseModel):
    id: str | None = None
    name: str = ""
    price: float = 0
    availableStock: float = 0
    imageUrl: str = ""


class ProductCard(BaseModel):
    id: str
    name: str
    price: float
    imageUrl: str = ""
    shopId: str = ""
    url: str = ""
    description: str = ""
    score: float | None = None
    variants: list[ProductVariant] = Field(default_factory=list)
    specifications: list[dict[str, str]] = Field(default_factory=list)


class PolicySource(BaseModel):
    number: int = Field(ge=1)
    title: str = Field(default="", max_length=500)
    url: str = Field(default="", max_length=2000)


class CandidateVerification(BaseModel):
    productId: str = Field(pattern=r"^[a-fA-F0-9]{24}$")
    verdict: Literal["match", "no_match", "unknown"]
    evidence: list[str] = Field(default_factory=list, max_length=12)
    reason: str = Field(default="", max_length=500)


class VerificationBatch(BaseModel):
    results: list[CandidateVerification] = Field(default_factory=list, max_length=30)


class PendingAction(BaseModel):
    id: str
    kind: Literal["cart_add", "cart_update", "cart_remove", "checkout_confirm"]
    summary: str
    payload: dict = Field(default_factory=dict)
    secret: str = ""
    expires_at: float

    def public(self) -> dict:
        return self.model_dump(exclude={"payload", "secret"})


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=2000)
    sessionId: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{43}$")
    referenceProductId: str | None = Field(
        default=None, pattern=r"^[a-fA-F0-9]{24}$"
    )
    variantId: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{24}$")
    quantity: int | None = Field(default=None, ge=1, le=100)
    addressId: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{24}$")
    paymentMethod: Literal["cod", "bank_transfer"] | None = None
    voucherCode: str | None = Field(default=None, max_length=40)
    confirmActionId: str | None = Field(default=None, min_length=8, max_length=128)
    cancelActionId: str | None = Field(default=None, min_length=8, max_length=128)

    @model_validator(mode="after")
    def require_input(self):
        if not any(
            [
                self.message.strip(),
                self.referenceProductId,
                self.confirmActionId,
                self.cancelActionId,
            ]
        ):
            raise ValueError("Nhập yêu cầu hoặc chọn một hành động.")
        return self


class ChatResponse(BaseModel):
    sessionId: str
    answer: str
    products: list[ProductCard] = Field(default_factory=list)
    route: str
    retrievalRounds: int = 0
    pendingAction: dict | None = None
    actionResult: dict | list | None = None
    warnings: list[str] = Field(default_factory=list)
    sources: list[PolicySource] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    handoff: bool = False


class AgentState(TypedDict, total=False):
    message: str
    user_id: str
    role: str
    session_id: str
    history: list[dict]
    request: Annotated[dict, UntrackedValue(dict)]
    understanding: dict
    semantic_turn: dict
    search_context: dict
    plan: dict
    query: str
    retrieval_rounds: int
    retrieval_hits: Annotated[list[dict], UntrackedValue(list)]
    products: Annotated[list[dict], UntrackedValue(list)]
    render_product_cards: bool
    tool_result: Annotated[dict | list, UntrackedValue(dict)]
    answer: Annotated[str, UntrackedValue(str)]
    pending_action: dict | None
    focused_products: list[dict]
    active_product_id: str | None
    selected_options: dict[str, list[str]]
    shopping_phase: ShoppingPhase
    route: str
    warnings: list[str]
    sources: list[dict]
    suggestions: Annotated[list[str], UntrackedValue(list)]
    handoff: Annotated[bool, UntrackedValue(bool)]
    skipped_tasks: Annotated[list[str], UntrackedValue(list)]
    policy_appendix: Annotated[str, UntrackedValue(str)]
    policy_sources: Annotated[list[dict], UntrackedValue(list)]
    clarify_count: int
    last_clarify_key: str
    session_expires_at: float
    committed: bool

