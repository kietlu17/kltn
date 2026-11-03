import re
import unicodedata
from typing import Annotated, Literal, TypedDict

from langgraph.channels import UntrackedValue
from pydantic import BaseModel, Field, model_validator


def explicit_price_limits(message: str) -> dict:
    """Enforce unambiguous shopper price caps even when the planner omits them."""
    text = unicodedata.normalize("NFD", message.lower()).replace("đ", "d")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    limits = {}
    pattern = r"\b(duoi|khong qua|toi da|tren|toi thieu)\s+([0-9]+(?:[.,][0-9]+)*)\s*(trieu|nghin|ngan|tr|k|vnd|dong|d)?\b"
    for match in re.finditer(pattern, text):
        direction, number, unit = match.groups()
        if unit in {"trieu", "tr", "nghin", "ngan", "k"}:
            value = float(number.replace(",", ".")) if number.count(",") + number.count(".") <= 1 else None
            multiplier = 1_000_000 if unit in {"trieu", "tr"} else 1000
        else:
            value = float(number.replace(".", "").replace(",", ""))
            multiplier = 1
        if value is not None and value * multiplier <= 1e12:
            limits["min_price" if direction in {"tren", "toi thieu"} else "max_price"] = value * multiplier
    return limits


class SearchPlan(BaseModel):
    # Canonical, versioned shopping state; other fields adapt it to existing tools.
    context: dict = Field(default_factory=dict)
    intent: Literal["search", "similar", "clarify"] = "search"
    query: str = Field(default="", max_length=1500)
    min_price: float | None = Field(default=None, ge=0, le=1e12)
    max_price: float | None = Field(default=None, ge=0, le=1e12)
    variant_terms: list[str] = Field(default_factory=list, max_length=8)
    reference_product_id: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{24}$")
    clarification: str = Field(default="", max_length=500)
    use_previous_image: bool = False
    # Persistent shopping requirements; measurements never imply a gender/category.
    product_type: str | None = Field(default=None, max_length=60)
    audience: Literal["nam", "nu", "tre_em", "unisex"] | None = None
    dialogue_act: Literal["search", "size_advice", "size_search"] = "search"
    foot_length_cm: float | None = Field(default=None, ge=5, le=50)
    height_cm: float | None = Field(default=None, ge=40, le=250)
    weight_kg: float | None = Field(default=None, ge=2, le=400)
    bust_cm: float | None = Field(default=None, ge=30, le=250)
    sizing_product_id: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{24}$")
    estimated_sizes: list[Literal["XS", "S", "M", "L", "XL", "XXL", "XXXL"]] = Field(default_factory=list, max_length=3)
    size_estimate_source: Literal["", "model", "web"] = ""
    size_estimate_sources: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def ordered_prices(self):
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError("Invalid price range")
        return self


class ChatState(TypedDict, total=False):
    message: str
    route_name: str
    # Shopper image bytes are needed during a run, but must never enter a checkpoint.
    image: Annotated[str | None, UntrackedValue(str)]
    reference_product_id: str | None
    history: list[dict]
    previous_plan: Annotated[dict, UntrackedValue(dict)]
    previous_products: Annotated[list[dict], UntrackedValue(list)]
    focused_product_id: str
    focused_product_ids: list[str]
    focused_order_id: str
    visual_description: str
    plan: dict
    turn_understanding: Annotated[dict, UntrackedValue(dict)]
    remembered_products: list[dict]
    products: Annotated[list[dict], UntrackedValue(list)]
    answer: Annotated[str, UntrackedValue(str)]
    session_id: str
    authenticated_user_id: str
    actor_role: str
    variant_id: str | None
    address_id: str | None
    payment_method: str | None
    voucher_code: str | None
    action_request_id: str | None
    confirm_action_id: str | None
    cancel_action_id: str | None
    pending_action: dict | None
    action_result: Annotated[dict, UntrackedValue(dict)]
    commerce_intent: str
    session_expires_at: float
    _context_expires: dict[str, float]
    turn_committed: bool
