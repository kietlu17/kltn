from __future__ import annotations

import json
import re
import secrets
import time
import unicodedata

from langgraph.graph import END, START, StateGraph

from .config import AgenticSettings
from .retrieval import _search_terms
from .schemas import (
    AgentPlan,
    AgentState,
    ConstraintDelta,
    PendingAction,
    SearchConstraint,
    SearchContext,
    SearchFilters,
    SemanticConstraint,
    SemanticReference,
    SemanticTask,
    SemanticTurn,
    TurnUnderstanding,
)
from .specs import (
    canonical_spec_key,
    normalize_specifications,
    requires_semantic_verifier,
    verify_spec_constraints,
)
from .taxonomy import build_catalog_tree, compact_catalog_tree, resolve_category_ids


def _normalized(value: str) -> str:
    text = unicodedata.normalize("NFD", value.casefold()).replace("đ", "d")
    return "".join(char for char in text if not unicodedata.combining(char))


_REFERENCE_STOP_WORDS = {
    "toi", "muon", "can", "mua", "mau", "chon", "lay", "them", "vao", "gio",
    "san", "pham", "va", "voi", "so", "sanh", "cai", "con", "xem", "thong", "tin",
}


def _reference_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _normalized(value))
        if len(token) > 1 and token not in _REFERENCE_STOP_WORDS
    }


def _is_model_token(token: str) -> bool:
    return (
        token.isdigit() and len(token) >= 2
    ) or (
        len(token) >= 3
        and any(char.isalpha() for char in token)
        and any(char.isdigit() for char in token)
    )


def _focused_references(message: str, focused: list[dict]) -> list[dict]:
    """Resolve named follow-ups against products already shown to the user."""
    message_tokens = _reference_tokens(message)
    if not message_tokens:
        return []
    candidates = [
        item
        for item in focused
        if re.fullmatch(r"[a-fA-F0-9]{24}", str(item.get("id") or ""))
        and item.get("name")
    ]
    token_sets = [_reference_tokens(str(item["name"])) for item in candidates]
    frequencies = {
        token: sum(token in tokens for tokens in token_sets)
        for token in set().union(*token_sets) if token_sets
    }
    ranked: list[tuple[float, set[str], dict]] = []
    for item, name_tokens in zip(candidates, token_sets):
        matched = name_tokens & message_tokens
        message_model_tokens = {
            token for token in message_tokens if _is_model_token(token)
        }
        candidate_model_tokens = {
            token for token in name_tokens if _is_model_token(token)
        }
        matched_model_tokens = {
            token
            for token in matched
            if _is_model_token(token)
        }
        unique_name_tokens = {
            token
            for token in name_tokens
            if frequencies.get(token) == 1 and len(token) >= 3
        }
        unique_matches = matched & unique_name_tokens
        name_coverage = len(matched) / max(len(name_tokens), 1)
        if (
            message_model_tokens
            and candidate_model_tokens
            and not matched_model_tokens
        ):
            continue
        if not matched_model_tokens and not (
            unique_matches and name_coverage >= 0.6
        ):
            continue
        score = sum(1 / frequencies[token] for token in matched)
        score += len(matched) / max(len(name_tokens), 1)
        ranked.append((score, matched, item))

    # Prefer the most specific model name. For example, A07 is a subset of
    # A07 5G and must not be included when the user explicitly wrote "5G".
    specific = [
        entry
        for entry in ranked
        if not any(
            entry[1] < other[1]
            for other in ranked
            if other is not entry
        )
    ]
    specific.sort(key=lambda entry: entry[0], reverse=True)
    return [entry[2] for entry in specific[:6]]


def _requests_purchase(message: str) -> bool:
    text = _normalized(message)
    return any(
        re.search(pattern, text)
        for pattern in (
            r"\b(?:toi\s+)?muon\s+(?:mua|mau)\b",
            r"\bcho\s+toi\s+mua\b",
            r"\bdat\s+mua\b",
            r"\bchot\b",
            r"\bthem\b.{0,60}\b(?:vao\s+)?gio\b",
        )
    )


def _continues_active_product(message: str) -> bool:
    text = _normalized(message)
    if any(
        re.search(pattern, text)
        for pattern in (
            r"\btim\b",
            r"\bgoi y\b",
            r"\b(?:san pham|mau|loai) khac\b",
            r"\bcon\b.{0,40}\bnao\b",
            r"\bso sanh\b",
            r"\bshop ban\b",
        )
    ):
        return False
    if len(re.findall(r"[a-z0-9]+", text)) > 14:
        return False
    return any(
        re.search(pattern, text)
        for pattern in (
            r"\bbao nhieu\b",
            r"\bgia\b",
            r"\bmau\b",
            r"\bsize\b",
            r"\bkich thuoc\b",
            r"\bchat lieu\b",
            r"\bcon hang\b",
            r"\bbao hanh\b",
            r"\bthong so\b",
            r"\bbien the\b",
            r"\bdung tich\b",
            r"\bcong suat\b",
            r"\bxuat xu\b",
            r"\bpin\b",
            r"\bram\b",
            r"\bbo nho\b",
            r"\b(?:xs|s|m|l|xl|xxl|2xl|3xl|4xl)\b",
            r"\b(?:cao|nang|can nang)\b",
            r"\b\d+(?:[.,]\d+)?\s*(?:kg|cm)\b",
            r"\b\d+m\d{1,2}\b",
        )
    )


_SIZE_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:size\s*)?(4xl|3xl|2xl|xxl|xl|xs|s|m|l)(?![a-z0-9])"
)


def _size_tokens(value: str) -> list[str]:
    return list(
        dict.fromkeys(match.upper() for match in _SIZE_PATTERN.findall(_normalized(value)))
    )


def _variant_dimensions(variants: list[dict], product_name: str = "") -> dict:
    colors: dict[str, str] = {}
    sizes: dict[str, str] = {}
    records: list[dict] = []
    product_key = _normalized(product_name)
    for variant in variants:
        name = str(variant.get("name", "")).strip()
        # MarketplaceClient represents a product without real variants as one
        # offer whose name is the product name. It is not a color dimension.
        parts = (
            []
            if product_key and _normalized(name) == product_key
            else [
                part.strip()
                for part in re.split(r"\s*/\s*|\s*\|\s*", name)
                if part.strip()
            ]
        )
        variant_sizes = _size_tokens(name)
        for size in variant_sizes:
            sizes.setdefault(_normalized(size), size)
        color_label = ""
        for part in parts:
            cleaned = re.sub(r"^màu\s+", "", part, flags=re.I)
            cleaned = re.sub(r"\s+\d{3}$", "", cleaned).strip()
            if cleaned and not _size_tokens(cleaned):
                color_label = cleaned
                break
        color_key = _normalized(color_label)
        if color_key:
            colors.setdefault(color_key, color_label)
        records.append(
            {
                "variant": variant,
                "color": color_key,
                "sizes": {_normalized(size) for size in variant_sizes},
            }
        )
    return {"colors": colors, "sizes": sizes, "records": records}


def _variant_selection(
    message: str, variants: list[dict], product_name: str = ""
) -> dict[str, list[str]]:
    text = _normalized(message)
    dimensions = _variant_dimensions(variants, product_name)
    colors = [
        key
        for key in dimensions["colors"]
        if re.search(rf"(?<!\w){re.escape(key)}(?!\w)", text)
    ]
    sizes = [
        display
        for key, display in dimensions["sizes"].items()
        if re.search(rf"(?<!\w){re.escape(key)}(?!\w)", text)
    ]
    return {
        "colors": sorted(colors, key=len, reverse=True)[:1],
        "sizes": sizes[:1],
    }


def _has_size_chart(product: dict) -> bool:
    text = _normalized(product.get("description", ""))
    return bool(
        re.search(r"\b(?:bang size|size chart|huong dan chon size)\b", text)
        or re.search(r"\b\d{2,3}\s*(?:-|–|den)\s*\d{2,3}\s*kg\b", text)
    )


def _last_assistant_message(history: list[dict]) -> str:
    for item in reversed(history):
        if item.get("role") == "assistant":
            return str(item.get("content") or "")
    return ""


def _last_offer_is_add_to_cart(history: list[dict]) -> bool:
    text = _normalized(_last_assistant_message(history))
    return bool(
        re.search(r"\b(?:co muon|ban muon)\b.{0,80}\bthem\b.{0,40}\bgio\b", text)
        or re.search(r"\bthem lua chon nay vao gio\b", text)
    )


def _fallback_understanding(
    message: str, history: list[dict], active_product_id: str
) -> TurnUnderstanding:
    original = message.casefold().strip()
    text = _normalized(message).strip()
    active = bool(active_product_id)
    sizes = _size_tokens(message)
    color_match = re.search(r"\bmàu\s+([^\s,?.!]+)", original)
    colors: list[str] = []
    if color_match and color_match.group(1) not in {"gì", "nào", "những", "các"}:
        colors = [color_match.group(1)]

    short_reply = len(re.findall(r"[a-z0-9]+", text)) <= 4
    if short_reply and text in {"co", "dong y", "ok", "okay", "yes"}:
        return TurnUnderstanding(
            dialogue_act="confirmation",
            refers_to_active_product=active,
            confirmation="yes",
            confidence=0.99 if _last_offer_is_add_to_cart(history) else 0.65,
        )
    if short_reply and text in {"khong", "khong dau", "thoi", "huy", "no"}:
        return TurnUnderstanding(
            dialogue_act="confirmation",
            refers_to_active_product=active,
            confirmation="no",
            confidence=0.95,
        )
    similar_search = bool(
        re.search(r"\b(?:tuong tu|giong|thay the)\b", text)
        or re.search(r"\b(?:re|dat|mac)\s+hon\b", text)
    )
    if similar_search:
        price_relation = None
        if re.search(r"\bre\s+hon\b", text):
            price_relation = "cheaper"
        elif re.search(r"\b(?:dat|mac)\s+hon\b", text):
            price_relation = "more_expensive"
        return TurnUnderstanding(
            dialogue_act="new_search",
            refers_to_active_product=active,
            search_mode="similar",
            price_relation=price_relation,
            inherit_constraints=True,
            confidence=0.98,
        )
    price_desc = bool(
        re.search(r"\b(?:mac|mat|dat)\s+nhat\b", text)
        or re.search(r"\bgia\s+(?:cao|dat)\s+nhat\b", text)
    )
    price_asc = bool(
        re.search(r"\bre\s+nhat\b", text)
        or re.search(r"\bgia\s+thap\s+nhat\b", text)
    )
    if price_desc or price_asc:
        return TurnUnderstanding(
            dialogue_act="new_search",
            refers_to_active_product=False,
            requested_attribute="price",
            sort_by="price_desc" if price_desc else "price_asc",
            result_limit=1,
            confidence=0.99,
        )
    if _requests_purchase(message):
        return TurnUnderstanding(
            dialogue_act="purchase",
            refers_to_active_product=active,
            colors=colors,
            sizes=sizes,
            confidence=0.99,
        )
    if (
        re.search(r"\b(?:cao|nang|can nang|vua size|size phu hop|tu van size)\b", text)
        or re.search(r"\b\d+m\d{1,2}\b", text)
        or re.search(r"\b\d+(?:[.,]\d+)?\s*(?:kg|cm)\b", text)
    ):
        return TurnUnderstanding(
            dialogue_act="size_advice",
            refers_to_active_product=active,
            requested_attribute="fit",
            confidence=0.98,
        )
    asks_size = bool(
        re.search(r"\b(?:size|kich thuoc)\b", text)
        and re.search(r"\b(?:gi|nao|co|khong|ko)\b", text)
    )
    if active and asks_size:
        return TurnUnderstanding(
            dialogue_act="ask_attribute",
            refers_to_active_product=True,
            colors=colors,
            sizes=sizes,
            requested_attribute="size",
            confidence=0.97,
        )
    if active and (sizes or colors):
        return TurnUnderstanding(
            dialogue_act="select_variant",
            refers_to_active_product=True,
            colors=colors,
            sizes=sizes,
            confidence=0.97,
        )
    attribute_patterns = {
        "color": r"\bmau\b",
        "price": r"\b(?:gia|bao nhieu)\b",
        "stock": r"\bcon hang\b",
        "specification": r"\b(?:thong so|chat lieu|pin|ram|bo nho|cong suat)\b",
    }
    if active:
        for attribute, pattern in attribute_patterns.items():
            if re.search(pattern, text):
                return TurnUnderstanding(
                    dialogue_act="ask_attribute",
                    refers_to_active_product=True,
                    requested_attribute=attribute,
                    confidence=0.94,
                )
    if re.search(r"\bso sanh\b", text):
        return TurnUnderstanding(dialogue_act="compare_products", confidence=0.9)
    if re.search(r"\b(?:shop ban gi|danh muc|nganh hang)\b", text):
        return TurnUnderstanding(dialogue_act="browse_catalog", confidence=0.95)
    return TurnUnderstanding(dialogue_act="new_search", confidence=0.6)


def _asks_option_list(message: str, option: str) -> bool:
    text = _normalized(message)
    if option == "colors":
        return bool(
            re.search(r"\bmau\b", text)
            and re.search(r"\b(?:gi|nao|nhung|cac|co)\b", text)
            and not re.search(
                r"\b(?:den|trang|do|vang|hong|tim|cam|nau|xam|xanh)\b", text
            )
        )
    return bool(
        re.search(r"\b(?:size|kich thuoc)\b", text)
        and re.search(r"\b(?:gi|nao|nhung|cac|co)\b", text)
        and not re.search(r"\b(?:xs|s|m|l|xl|xxl|2xl|3xl)\b", text)
    )


def _merge_selected_options(
    message: str,
    previous: dict,
    filters: SearchFilters,
    continue_context: bool,
) -> dict[str, list[str]]:
    selected = {"colors": [], "sizes": []}
    for field in selected:
        incoming = list(getattr(filters, field))
        if not continue_context:
            selected[field] = incoming
        elif incoming:
            selected[field] = incoming
        elif _asks_option_list(message, field):
            selected[field] = []
        else:
            selected[field] = list(previous.get(field) or [])
        setattr(filters, field, selected[field])
    return selected


def _shopping_phase(intent: str, filters: SearchFilters, product_ids: list[str]) -> str:
    if intent in {"cart_add", "cart_update", "cart_remove", "checkout"}:
        return "selling"
    if intent == "product_detail" or product_ids:
        return "detailing"
    if intent == "product_search" and any(
        (
            filters.category_id,
            filters.category_path,
            filters.category_ids,
            filters.product_type,
            filters.audience,
            filters.brand,
            filters.colors,
            filters.sizes,
            filters.min_price is not None,
            filters.max_price is not None,
        )
    ):
        return "narrowing"
    return "exploring"


def _set_constraint(
    constraints: list[SearchConstraint], constraint: SearchConstraint
) -> list[SearchConstraint]:
    return [item for item in constraints if item.key != constraint.key] + [constraint]


def _apply_constraint_deltas(
    constraints: list[SearchConstraint], deltas: list[ConstraintDelta]
) -> list[SearchConstraint]:
    merged = list(constraints)
    for delta in deltas:
        key = delta.key.casefold()
        if delta.action == "remove":
            merged = [item for item in merged if item.key != key]
        elif delta.value is not None:
            merged = _set_constraint(
                merged,
                SearchConstraint(
                    key=key,
                    operator=delta.operator,
                    value=delta.value,
                    source="explicit",
                    strength=delta.strength,
                ),
            )
    return merged


def _apply_search_context(
    filters: SearchFilters, context: SearchContext
) -> SearchFilters:
    applied = filters.model_copy(deep=True)
    for constraint in context.constraints:
        key = constraint.key
        value = constraint.value
        values = value if isinstance(value, list) else [value]
        text_values = [str(item) for item in values if str(item).strip()]
        first = text_values[0] if text_values else ""
        if key == "product_type" and first:
            applied.product_type = first
        elif key == "category_id" and re.fullmatch(r"[a-fA-F0-9]{24}", first):
            applied.category_id = first
        elif key == "audience" and first in {"nam", "nu", "tre_em", "unisex"}:
            applied.audience = first
        elif key == "brand" and first:
            applied.brand = first
        elif key in {"color", "colors", "variant.color"}:
            applied.colors = text_values[:8]
        elif key in {"size", "sizes", "variant.size"}:
            applied.sizes = text_values[:8]
        elif key in {"price", "max_price"} and constraint.operator in {"lt", "lte"}:
            try:
                applied.max_price = float(value)
            except (TypeError, ValueError):
                pass
        elif key in {"price", "min_price"} and constraint.operator in {"gt", "gte"}:
            try:
                applied.min_price = float(value)
            except (TypeError, ValueError):
                pass
    applied.exclude_product_ids = list(
        dict.fromkeys([*applied.exclude_product_ids, *context.exclude_product_ids])
    )
    return SearchFilters.model_validate(applied.model_dump())


def _sync_context_from_filters(
    context: SearchContext, filters: SearchFilters
) -> SearchContext:
    synced = context.model_copy(deep=True)
    existing = {constraint.key for constraint in synced.constraints}
    candidates: list[SearchConstraint] = []
    scalar_fields = (
        ("product_type", filters.product_type),
        ("category_id", filters.category_id),
        ("audience", filters.audience),
        ("brand", filters.brand),
    )
    for key, value in scalar_fields:
        if value:
            candidates.append(
                SearchConstraint(
                    key=key,
                    value=str(value),
                    source="planner",
                    strength="hard",
                )
            )
    if filters.colors:
        candidates.append(
            SearchConstraint(
                key="variant.color",
                operator="any",
                value=filters.colors,
                source="planner",
                strength="soft",
            )
        )
    if filters.sizes:
        candidates.append(
            SearchConstraint(
                key="variant.size",
                operator="any",
                value=filters.sizes,
                source="planner",
                strength="soft",
            )
        )
    if filters.min_price is not None:
        candidates.append(
            SearchConstraint(
                key="price",
                operator="gte",
                value=filters.min_price,
                source="planner",
                strength="hard",
            )
        )
    if filters.max_price is not None:
        candidates.append(
            SearchConstraint(
                key="price",
                operator="lte",
                value=filters.max_price,
                source="planner",
                strength="hard",
            )
        )
    for constraint in candidates:
        if constraint.key not in existing:
            synced.constraints.append(constraint)
            existing.add(constraint.key)
    synced.exclude_product_ids = list(
        dict.fromkeys([*synced.exclude_product_ids, *filters.exclude_product_ids])
    )
    return SearchContext.model_validate(synced.model_dump())


_FAST_PATH_MAX_TOKENS = 6


def _variant_constraints(colors: list[str], sizes: list[str]) -> list[SemanticConstraint]:
    constraints: list[SemanticConstraint] = []
    if colors:
        constraints.append(
            SemanticConstraint(
                key="variant.color", operator="any", value=list(colors), source="conversation"
            )
        )
    if sizes:
        constraints.append(
            SemanticConstraint(
                key="variant.size", operator="any", value=list(sizes), source="conversation"
            )
        )
    return constraints


def _deterministic_turn(
    message: str,
    history: list[dict],
    active_product_id: str,
    selected: dict,
    *,
    short_only: bool = True,
) -> SemanticTurn | None:
    """Build a SemanticTurn without the model for unambiguous short turns.

    Only acts the deterministic interpreter is near-certain about are taken:
    confirmations of a pending cart offer, variant picks on the active
    product, price extremes and catalog browsing. Everything else returns
    None so the semantic model decides.
    """
    tokens = re.findall(r"[a-z0-9]+", _normalized(message))
    if not tokens or (short_only and len(tokens) > _FAST_PATH_MAX_TOKENS):
        return None
    understood = _fallback_understanding(message, history, active_product_id)
    if understood.confidence < 0.95:
        return None
    active = [SemanticReference(kind="active")] if active_product_id else []
    colors = understood.colors or list(selected.get("colors") or [])
    sizes = understood.sizes or list(selected.get("sizes") or [])
    act = understood.dialogue_act
    focus = "keep"
    if act == "confirmation" and understood.confirmation == "yes":
        if not active or not _last_offer_is_add_to_cart(history):
            return None
        task = SemanticTask(
            intent="cart_add", references=active, constraints=_variant_constraints(colors, sizes)
        )
        action = "continue"
    elif act == "purchase" and active and len(tokens) <= _FAST_PATH_MAX_TOKENS:
        task = SemanticTask(
            intent="cart_add", references=active, constraints=_variant_constraints(colors, sizes)
        )
        action = "continue"
    elif (
        act in {"select_variant", "ask_attribute"}
        and active
        and understood.requested_attribute in {None, "color", "size", "price", "stock"}
    ):
        task = SemanticTask(
            intent="product_detail",
            references=active,
            requested_attributes=(
                [understood.requested_attribute] if understood.requested_attribute else []
            ),
            constraints=_variant_constraints(understood.colors, understood.sizes),
        )
        action = "continue"
    elif act == "new_search" and understood.sort_by != "relevance":
        task = SemanticTask(
            intent="product_search",
            query=message,
            sort_by=understood.sort_by,
            result_limit=understood.result_limit or 1,
        )
        action, focus = "new", "replace"
    elif act == "browse_catalog":
        task = SemanticTask(intent="browse_categories")
        action = "new"
    else:
        return None
    return SemanticTurn(
        tasks=[task],
        conversation_action=action,
        focus_update=focus,
        confidence=understood.confidence,
    )


_RELAX_LABELS = {
    "spec.soft": "thuộc tính phụ",
    "price": "khoảng giá (±15%)",
    "variant.color": "màu",
    "variant.size": "kích thước/size",
    "brand": "thương hiệu",
}


def _next_relaxation(filters: SearchFilters, relaxed: list[str]) -> str | None:
    """Pick the next constraint to loosen, least important first."""
    candidates = (
        ("spec.soft", any(item.strength == "soft" for item in filters.spec_constraints)),
        ("price", filters.max_price is not None or filters.min_price is not None),
        ("variant.color", bool(filters.colors)),
        ("variant.size", bool(filters.sizes)),
        ("brand", bool(filters.brand)),
    )
    return next(
        (key for key, applies in candidates if applies and key not in relaxed), None
    )


def _apply_relaxation(filters: SearchFilters, key: str) -> SearchFilters:
    relaxed = filters.model_copy(deep=True)
    if key == "spec.soft":
        relaxed.spec_constraints = [
            item for item in relaxed.spec_constraints if item.strength == "hard"
        ]
    elif key == "price":
        if relaxed.max_price is not None:
            relaxed.max_price = round(relaxed.max_price * 1.15)
        if relaxed.min_price is not None:
            relaxed.min_price = round(relaxed.min_price * 0.85)
    elif key == "variant.color":
        relaxed.colors = []
    elif key == "variant.size":
        relaxed.sizes = []
    elif key == "brand":
        relaxed.brand = None
    return relaxed


def _soft_context_keys(context: SearchContext) -> set[str]:
    return {
        constraint.key
        for constraint in context.constraints
        if constraint.strength == "soft" and constraint.key not in context.relaxed_keys
    }


def _price_text(value) -> str:
    return f"{float(value or 0):,.0f}".replace(",", ".") + "đ"


def _search_template_answer(products: list[dict]) -> str:
    listed = "; ".join(
        f"{item.get('name', 'Sản phẩm')} ({_price_text(item.get('price'))})"
        for item in products[:3]
    )
    more = f" và {len(products) - 3} mẫu khác" if len(products) > 3 else ""
    return (
        f"Mình tìm thấy {len(products)} sản phẩm phù hợp và còn hàng: {listed}{more}. "
        "Bạn muốn xem chi tiết hoặc so sánh mẫu nào?"
    )


_INTENT_LABELS = {
    "browse_categories": "xem danh mục",
    "product_search": "tìm sản phẩm",
    "product_detail": "hỏi chi tiết sản phẩm",
    "compare_products": "so sánh sản phẩm",
    "cart_view": "xem giỏ hàng",
    "cart_add": "thêm vào giỏ",
    "cart_update": "sửa giỏ hàng",
    "cart_remove": "xóa khỏi giỏ",
    "checkout": "thanh toán",
    "order_status": "tra cứu đơn hàng",
}


class AgenticShoppingGraph:
    def __init__(
        self,
        settings: AgenticSettings,
        models_gateway,
        retriever,
        marketplace,
        policy=None,
        checkpointer=None,
    ):
        self.settings = settings
        self.models = models_gateway
        self.retriever = retriever
        self.marketplace = marketplace
        self.policy = policy
        self.graph = self._compile(checkpointer)

    def _compile(self, checkpointer):
        builder = StateGraph(AgentState)
        builder.add_node("understand", self.understand)
        builder.add_node("resolve_context", self.resolve_context)
        builder.add_node("plan", self.plan)
        builder.add_node("browse_categories", self.browse_categories)
        builder.add_node("retrieve", self.retrieve)
        builder.add_node("relax", self.relax_constraints)
        builder.add_node("product_detail", self.product_detail)
        builder.add_node("cart_view", self.cart_view)
        builder.add_node("prepare_cart", self.prepare_cart)
        builder.add_node("prepare_checkout", self.prepare_checkout)
        builder.add_node("order_status", self.order_status)
        builder.add_node("policy", self.policy_answer)
        builder.add_node("policy_side", self.policy_side)
        builder.add_node("resolve_pending", self.resolve_pending)
        builder.add_node("clarify_guard", self.clarify_guard)
        builder.add_node("general", self.general)
        builder.add_node("collect", self.collect)
        builder.add_node("finalize", self.finalize)
        builder.add_edge(START, "understand")
        builder.add_edge("understand", "resolve_context")
        builder.add_edge("resolve_context", "plan")
        # The main route and the policy side-branch run in the same superstep;
        # finalize waits for both through the collect barrier.
        builder.add_conditional_edges(
            "plan",
            self.route_after_plan,
            {
                "browse_categories": "browse_categories",
                "product_search": "retrieve",
                "product_detail": "product_detail",
                "cart_view": "cart_view",
                "prepare_cart": "prepare_cart",
                "prepare_checkout": "prepare_checkout",
                "order_status": "order_status",
                "policy": "policy",
                "policy_side": "policy_side",
                "resolve_pending": "resolve_pending",
                "clarify_guard": "clarify_guard",
                "general": "general",
            },
        )
        builder.add_conditional_edges(
            "retrieve",
            self.route_after_retrieval,
            {"relax": "relax", "collect": "collect"},
        )
        builder.add_edge("relax", "retrieve")
        for node in (
            "browse_categories",
            "product_detail",
            "cart_view",
            "prepare_cart",
            "prepare_checkout",
            "order_status",
            "policy",
            "resolve_pending",
            "clarify_guard",
            "general",
        ):
            builder.add_edge(node, "collect")
        builder.add_edge(["collect", "policy_side"], "finalize")
        builder.add_edge("finalize", END)
        return builder.compile(checkpointer=checkpointer)

    async def understand(self, state: AgentState) -> dict:
        message = state.get("message", "")
        history = state.get("history", [])
        active_product_id = str(state.get("active_product_id") or "")
        settings = getattr(self, "settings", None)
        semantic_enabled = getattr(settings, "semantic_decision_v2", True)
        if not semantic_enabled or not hasattr(self.models, "decide"):
            # Compatibility for existing deterministic test doubles only. The
            # production Gemini gateway always uses the semantic decision path.
            fallback = _fallback_understanding(message, history, active_product_id)
            try:
                understood = await self.models.understand(
                    message,
                    history,
                    state.get("focused_products", []),
                    active_product_id or None,
                    state.get("selected_options", {}),
                    state.get("shopping_phase", "exploring"),
                )
            except Exception:
                understood = fallback
            if fallback.confidence >= 0.9:
                understood = fallback
            elif fallback.colors or fallback.sizes:
                payload = understood.model_dump()
                payload["colors"] = fallback.colors or payload.get("colors", [])
                payload["sizes"] = fallback.sizes or payload.get("sizes", [])
                understood = TurnUnderstanding.model_validate(payload)
            if understood.confirmation and not _last_offer_is_add_to_cart(history):
                understood.confirmation = None
                if understood.dialogue_act == "confirmation":
                    understood.dialogue_act = "general"
                    understood.confidence = min(understood.confidence, 0.6)
            if not active_product_id:
                understood.refers_to_active_product = False
            return {"understanding": understood.model_dump()}

        warnings = list(state.get("warnings", []))
        selected = state.get("selected_options", {}) or {}
        turn = _deterministic_turn(message, history, active_product_id, selected)
        if turn is not None:
            warnings.append("FAST_PATH")
        else:
            try:
                turn = await self.models.decide(
                    message,
                    history,
                    state.get("focused_products", []),
                    active_product_id or None,
                    selected,
                    state.get("shopping_phase", "exploring"),
                )
            except Exception:
                warnings.append("MODEL_UNAVAILABLE")
                turn = _deterministic_turn(
                    message, history, active_product_id, selected, short_only=False
                ) or SemanticTurn(
                    tasks=[SemanticTask(intent="clarify")],
                    conversation_action="clarify",
                    focus_update="keep",
                    confidence=0,
                    needs_clarification=True,
                    clarification_question="Mình chưa hiểu chắc yêu cầu. Bạn muốn tìm sản phẩm, hỏi chính sách hay thao tác với đơn hàng?",
                )
        primary = turn.tasks[0]
        if turn.confidence < 0.75 and not turn.needs_clarification:
            # A plausible search is cheaper to show than another question:
            # act on the best guess and let the answer state the assumption.
            if (
                turn.confidence >= 0.5
                and primary.intent == "product_search"
                and (primary.query.strip() or message.strip())
            ):
                warnings.append("ASSUMED_INTENT")
            else:
                turn.needs_clarification = True
                turn.conversation_action = "clarify"
                turn.focus_update = "keep"
                turn.clarification_question = (
                    turn.clarification_question
                    or "Bạn có thể nói rõ hơn sản phẩm hoặc nhu cầu cần hỗ trợ không?"
                )
                warnings.append("LOW_CONFIDENCE")

        requested_attribute = (
            primary.requested_attributes[0] if primary.requested_attributes else None
        )
        if requested_attribute not in {
            None, "color", "size", "price", "stock", "fit", "specification", "other"
        }:
            requested_attribute = "specification"
        compatibility = TurnUnderstanding(
            dialogue_act=(
                "new_search"
                if primary.intent == "product_search"
                else "ask_attribute"
                if primary.intent == "product_detail"
                else "compare_products"
                if primary.intent == "compare_products"
                else "browse_catalog"
                if primary.intent == "browse_categories"
                else "purchase"
                if primary.intent in {"cart_add", "cart_update", "cart_remove", "checkout"}
                else "order_status"
                if primary.intent == "order_status"
                else "general"
            ),
            refers_to_active_product=any(
                reference.kind == "active" for reference in primary.references
            ),
            requested_attribute=requested_attribute,
            sort_by=primary.sort_by,
            result_limit=primary.result_limit,
            confidence=turn.confidence,
        )
        return {
            "semantic_turn": turn.model_dump(),
            "understanding": compatibility.model_dump(),
            "warnings": warnings,
        }

    async def resolve_context(self, state: AgentState) -> dict:
        understanding = TurnUnderstanding.model_validate(
            state.get("understanding") or {}
        )
        previous = SearchContext.model_validate(state.get("search_context") or {})
        message = state.get("message", "")

        if understanding.search_mode == "similar":
            focused = state.get("focused_products", [])
            anchor_id = str(state.get("active_product_id") or "")
            if not anchor_id:
                anchor_id = str(previous.anchor_product_id or "")
            if not anchor_id and len(focused) == 1:
                anchor_id = str(focused[0].get("id") or "")
            if not re.fullmatch(r"[a-fA-F0-9]{24}", anchor_id):
                anchor_id = ""
            anchor_name = next(
                (
                    str(item.get("name") or "")
                    for item in focused
                    if str(item.get("id") or "") == anchor_id
                ),
                previous.anchor_product_name,
            )
            catalog_context = (
                await self.retriever.product_context(anchor_id) if anchor_id else {}
            )
            constraints: list[SearchConstraint] = []
            product_type = str(catalog_context.get("productType") or "").strip()
            if product_type:
                constraints.append(
                    SearchConstraint(
                        key="product_type",
                        value=product_type,
                        source="anchor_product",
                        strength="hard",
                    )
                )
            audiences = [
                str(value)
                for value in catalog_context.get("audience", [])
                if str(value) in {"nam", "nu", "tre_em", "unisex"}
            ]
            specific_audiences = [value for value in audiences if value != "unisex"]
            if len(specific_audiences) == 1:
                constraints.append(
                    SearchConstraint(
                        key="audience",
                        value=specific_audiences[0],
                        source="anchor_product",
                        strength="hard",
                    )
                )
            selected = state.get("selected_options", {})
            if selected.get("colors"):
                constraints.append(
                    SearchConstraint(
                        key="variant.color",
                        operator="any",
                        value=list(selected["colors"]),
                        source="conversation",
                        strength="soft",
                    )
                )
            if selected.get("sizes"):
                constraints.append(
                    SearchConstraint(
                        key="variant.size",
                        operator="any",
                        value=list(selected["sizes"]),
                        source="conversation",
                        strength="soft",
                    )
                )
            if understanding.price_relation == "cheaper":
                anchor_price = catalog_context.get("minPrice")
                if isinstance(anchor_price, (int, float)) and anchor_price > 0:
                    constraints.append(
                        SearchConstraint(
                            key="price",
                            operator="lt",
                            value=max(float(anchor_price) - 1, 0),
                            source="explicit",
                            strength="hard",
                        )
                    )
            elif understanding.price_relation == "more_expensive":
                anchor_price = catalog_context.get("maxPrice")
                if isinstance(anchor_price, (int, float)):
                    constraints.append(
                        SearchConstraint(
                            key="price",
                            operator="gt",
                            value=float(anchor_price) + 1,
                            source="explicit",
                            strength="hard",
                        )
                    )
            constraints = _apply_constraint_deltas(
                constraints, understanding.constraint_deltas
            )
            indexed_text = str(catalog_context.get("text") or "")[:700]
            semantic_query = " ".join(
                part for part in (message, anchor_name, indexed_text) if part
            )[:1000]
            context = SearchContext(
                mode="similar",
                anchor_product_id=anchor_id or None,
                anchor_product_name=anchor_name,
                semantic_query=semantic_query,
                constraints=constraints,
                exclude_product_ids=[anchor_id] if anchor_id else [],
            )
            return {"search_context": context.model_dump()}

        if understanding.search_mode == "refine":
            previous.mode = "refine"
            previous.semantic_query = message or previous.semantic_query
            previous.constraints = _apply_constraint_deltas(
                previous.constraints, understanding.constraint_deltas
            )
            return {"search_context": previous.model_dump()}

        if understanding.dialogue_act == "new_search":
            context = SearchContext(
                mode="standard",
                semantic_query=message,
                constraints=_apply_constraint_deltas(
                    [], understanding.constraint_deltas
                ),
            )
            return {"search_context": context.model_dump()}
        return {"search_context": previous.model_dump()}

    @staticmethod
    def _fallback_plan(message: str) -> AgentPlan:
        text = _normalized(message)
        intent = "product_search"
        if any(term in text for term in ("shop ban gi", "danh muc", "nganh hang")):
            intent = "browse_categories"
        elif any(term in text for term in ("gio hang cua toi", "xem gio", "trong gio")):
            intent = "cart_view"
        elif any(term in text for term in ("thanh toan", "checkout", "dat hang")):
            intent = "checkout"
        elif any(term in text for term in ("xoa khoi gio", "bo khoi gio")):
            intent = "cart_remove"
        elif any(term in text for term in ("cap nhat gio", "doi so luong", "sua so luong")):
            intent = "cart_update"
        elif any(term in text for term in ("them vao gio", "them gio")):
            intent = "cart_add"
        elif any(term in text for term in ("don hang", "van chuyen", "giao hang")):
            intent = "order_status"
        product_match = re.search(r"(?<![a-f0-9])([a-f0-9]{24})(?![a-f0-9])", text)
        order_match = re.search(r"(?:don|order)\s*#?\s*(\d+)", text)
        quantity_match = re.search(r"(?:so luong|them|mua)\s+(\d{1,3})\b", text)
        filters = SearchFilters()
        price_match = re.search(
            r"(?:duoi|khong qua|toi da)\s+([\d.,]+)\s*(trieu|nghin|ngan|k)?", text
        )
        if price_match:
            raw, unit = price_match.groups()
            value = float(raw.replace(",", "."))
            if unit == "trieu":
                value *= 1_000_000
            elif unit in {"nghin", "ngan", "k"}:
                value *= 1_000
            filters.max_price = value
        colors = [
            color
            for color in ("den", "trang", "do", "vang", "hong", "tim", "cam", "nau", "xam", "xanh")
            if re.search(rf"(?<!\w){color}(?!\w)", text)
        ]
        filters.colors = colors[:2]
        filters.sizes = _size_tokens(text)[:2]
        return AgentPlan(
            intent=intent,
            query=message,
            filters=filters,
            product_id=product_match.group(1) if product_match else None,
            order_id=int(order_match.group(1)) if order_match else None,
            quantity=int(quantity_match.group(1)) if quantity_match else 1,
        )

    @staticmethod
    def _semantic_references(task: SemanticTask, state: AgentState) -> list[str]:
        focused = state.get("focused_products", [])
        active = str(state.get("active_product_id") or "")
        resolved: list[str] = []
        for reference in task.references:
            product_id = ""
            if reference.kind == "active":
                product_id = active
            elif reference.kind == "focused_index" and reference.index is not None:
                index = reference.index - 1
                if 0 <= index < len(focused):
                    product_id = str(focused[index].get("id") or "")
            elif reference.kind == "name":
                name = _normalized(reference.name)
                matches = [
                    str(item.get("id") or "")
                    for item in focused
                    if name
                    and (
                        name == _normalized(str(item.get("name") or ""))
                        or name in _normalized(str(item.get("name") or ""))
                    )
                ]
                if len(matches) == 1:
                    product_id = matches[0]
            if re.fullmatch(r"[a-fA-F0-9]{24}", product_id) and product_id not in resolved:
                resolved.append(product_id)
        return resolved

    @staticmethod
    def _semantic_filters(task: SemanticTask) -> SearchFilters:
        filters = SearchFilters()
        for constraint in task.constraints:
            key = constraint.key.casefold()
            value = constraint.value
            if key == "product_type" and isinstance(value, str):
                filters.product_type = value
            elif key == "category_path" and isinstance(value, str):
                filters.category_path = value
            elif key == "audience" and value in {"nam", "nu", "tre_em", "unisex"}:
                filters.audience = value
            elif key == "brand" and isinstance(value, str):
                filters.brand = value
            elif key in {"color", "colors", "variant.color"}:
                filters.colors = list(value) if isinstance(value, list) else [str(value)]
            elif key in {"size", "sizes", "variant.size"}:
                filters.sizes = list(value) if isinstance(value, list) else [str(value)]
            elif key in {"max_price", "price"} and constraint.operator in {"lt", "lte"}:
                filters.max_price = float(value)
            elif key in {"min_price", "price"} and constraint.operator in {"gt", "gte"}:
                filters.min_price = float(value)
            elif key == "price" and constraint.operator == "eq":
                filters.min_price = filters.max_price = float(value)
            else:
                filters.spec_constraints.append(constraint)
        return SearchFilters.model_validate(filters.model_dump())

    async def _plan_semantic(self, state: AgentState, turn: SemanticTurn) -> dict:
        request = state.get("request", {})
        focused = state.get("focused_products", [])
        skipped_tasks: list[str] = []
        if turn.needs_clarification:
            task = SemanticTask(intent="clarify")
        else:
            task = next((item for item in turn.tasks if item.intent != "policy"), turn.tasks[0])
            # Policy runs on its own branch; any other extra task is announced
            # in the answer instead of being dropped silently.
            skipped_tasks = [
                _INTENT_LABELS[item.intent]
                for item in turn.tasks
                if item is not task
                and item.intent != "policy"
                and item.intent in _INTENT_LABELS
            ]
        references = self._semantic_references(task, state)
        trusted_product = str(request.get("referenceProductId") or "")
        if re.fullmatch(r"[a-fA-F0-9]{24}", trusted_product):
            references = [trusted_product]
        active = str(state.get("active_product_id") or "")
        if (
            not references
            and task.intent in {"product_detail", "compare_products", "cart_add", "cart_update", "cart_remove"}
            and turn.conversation_action in {"continue", "resume"}
            and re.fullmatch(r"[a-fA-F0-9]{24}", active)
        ):
            references = [active]

        filters = self._semantic_filters(task)
        intent = task.intent
        clarification = ""
        if turn.needs_clarification or intent == "clarify":
            intent = "general"
            clarification = turn.clarification_question or "Bạn có thể nói rõ hơn nhu cầu cần hỗ trợ không?"
        elif task.intent == "out_of_scope":
            intent = "general"
            clarification = "Mình chỉ hỗ trợ mua sắm, chính sách, giỏ hàng và đơn hàng; mình không thể thực hiện yêu cầu đó."
        elif task.intent == "compare_products":
            if len(references) < 2:
                intent = "general"
                clarification = "Bạn muốn so sánh những sản phẩm nào trong danh sách?"
            else:
                intent = "product_search"
        elif task.intent == "product_detail" and len(references) != 1:
            intent = "general"
            clarification = "Bạn muốn hỏi chi tiết sản phẩm nào?"
        elif task.intent in {"cart_add", "cart_update", "cart_remove"} and len(references) != 1:
            intent = "general"
            clarification = "Bạn muốn thao tác với sản phẩm nào?"

        query = task.query or state.get("message", "")
        plan = AgentPlan(
            intent=intent,
            query=query,
            filters=filters,
            product_id=references[0] if len(references) == 1 else None,
            product_ids=references,
            variant_id=request.get("variantId"),
            quantity=request.get("quantity") or task.quantity,
            clarification=clarification,
            sort_by=task.sort_by,
            result_limit=task.result_limit,
        )
        if intent == "product_search" and not references and (filters.category_path or filters.product_type):
            try:
                category_tree = build_catalog_tree(await self.marketplace.categories())
                filters.category_ids = resolve_category_ids(
                    category_tree, filters.category_path or filters.product_type or ""
                )
                plan.filters = filters
            except Exception:
                pass
        next_active = state.get("active_product_id")
        if turn.focus_update == "clear":
            next_active = None
        elif references and len(references) == 1:
            next_active = references[0]
        elif turn.focus_update == "replace" and intent == "product_search":
            next_active = None
        selected_options = dict(state.get("selected_options", {}))
        if filters.colors:
            selected_options["colors"] = filters.colors
        if filters.sizes:
            selected_options["sizes"] = filters.sizes
        return {
            "plan": plan.model_dump(),
            "query": query,
            "retrieval_rounds": 0,
            "products": [],
            "render_product_cards": intent == "product_search" and not references,
            "active_product_id": next_active,
            "selected_options": selected_options,
            "shopping_phase": _shopping_phase(intent, filters, references),
            "tool_result": {},
            "warnings": list(state.get("warnings", [])),
            "route": task.intent if task.intent in {"clarify", "out_of_scope"} else intent,
            "skipped_tasks": skipped_tasks,
            "committed": False,
        }

    async def plan(self, state: AgentState) -> dict:
        request = state.get("request", {})
        if request.get("confirmActionId") or request.get("cancelActionId"):
            return {"route": "resolve_pending", "committed": False}
        if state.get("semantic_turn"):
            return await self._plan_semantic(
                state, SemanticTurn.model_validate(state["semantic_turn"])
            )
        understanding = TurnUnderstanding.model_validate(
            state.get("understanding") or {}
        )
        search_context = SearchContext.model_validate(
            state.get("search_context") or {}
        )
        hints = {
            key: request.get(key)
            for key in (
                "referenceProductId",
                "variantId",
                "quantity",
                "addressId",
                "paymentMethod",
                "voucherCode",
            )
            if request.get(key) is not None
        }
        active_product_id = str(state.get("active_product_id") or "")
        if re.fullmatch(r"[a-fA-F0-9]{24}", active_product_id):
            hints["activeProductId"] = active_product_id
        else:
            active_product_id = ""
        hints["shoppingPhase"] = state.get("shopping_phase", "exploring")
        hints["selectedOptions"] = state.get("selected_options", {})
        hints["turnUnderstanding"] = understanding.model_dump()
        focused = state.get("focused_products", [])
        references = _focused_references(state.get("message", ""), focused)
        reference_ids = [str(item["id"]) for item in references]
        focused_ids = {str(item.get("id")) for item in focused if item.get("id")}
        context_dialogue_acts = {
            "ask_attribute",
            "select_variant",
            "size_advice",
        }
        understanding_is_authoritative = (
            understanding.confidence >= 0.85
            and understanding.dialogue_act != "unknown"
        )
        if understanding_is_authoritative:
            continues_focus = (
                understanding.refers_to_active_product
                and understanding.dialogue_act in context_dialogue_acts
            )
        else:
            continues_focus = _continues_active_product(
                state.get("message", "")
            ) or (
                understanding.refers_to_active_product
                and understanding.dialogue_act in context_dialogue_acts
            )
        requests_purchase = (
            _requests_purchase(state.get("message", ""))
            or understanding.dialogue_act == "purchase"
            or (
                understanding.dialogue_act == "confirmation"
                and understanding.confirmation == "yes"
                and _last_offer_is_add_to_cart(state.get("history", []))
            )
        )
        inherited_product = active_product_id or (
            next(iter(focused_ids)) if len(focused_ids) == 1 else ""
        )
        use_context_plan = (
            len(reference_ids) > 1
            or (len(reference_ids) == 1 and (continues_focus or requests_purchase))
            or (
                not reference_ids
                and bool(inherited_product)
                and (continues_focus or requests_purchase)
            )
        )
        if use_context_plan:
            plan = self._fallback_plan(state.get("message", ""))
            chosen_ids = reference_ids or [inherited_product]
            plan.product_ids = chosen_ids
            plan.product_id = chosen_ids[0] if len(chosen_ids) == 1 else None
            if requests_purchase and len(chosen_ids) == 1:
                plan.intent = "cart_add"
            elif continues_focus and len(chosen_ids) == 1:
                plan.intent = "product_detail"
            else:
                plan.intent = "product_search"
        else:
            try:
                plan = await self.models.plan(
                    state.get("message", ""),
                    state.get("history", []),
                    focused,
                    hints,
                )
            except Exception:
                plan = self._fallback_plan(state.get("message", ""))
        trusted_product = request.get("referenceProductId")
        updates = plan.model_dump()
        context_followup = False
        next_active_product = active_product_id or None
        if trusted_product:
            updates["product_id"] = trusted_product
            updates["product_ids"] = [trusted_product]
            next_active_product = trusted_product
        elif reference_ids:
            updates["product_ids"] = reference_ids
            updates["product_id"] = reference_ids[0] if len(reference_ids) == 1 else None
            next_active_product = reference_ids[0] if len(reference_ids) == 1 else None
            context_followup = True
            if len(reference_ids) == 1 and requests_purchase:
                updates["intent"] = "cart_add"
        else:
            updates["product_ids"] = [
                product_id
                for product_id in updates.get("product_ids", [])
                if product_id in focused_ids
            ]
            planned_product = str(updates.get("product_id") or "")
            if planned_product and planned_product in focused_ids:
                next_active_product = planned_product
                if requests_purchase:
                    updates["intent"] = "cart_add"
                    updates["product_ids"] = [planned_product]
                    context_followup = True
                elif (
                    updates.get("intent") == "product_detail"
                    or continues_focus
                ):
                    updates["intent"] = "product_detail"
                    updates["product_ids"] = [planned_product]
                    context_followup = True
            elif (
                continues_focus
                and (active_product_id or len(focused_ids) == 1)
            ):
                inherited_product = active_product_id or next(iter(focused_ids))
                updates["intent"] = "product_detail"
                updates["product_id"] = inherited_product
                updates["product_ids"] = [inherited_product]
                next_active_product = inherited_product
                context_followup = True
            elif (
                requests_purchase
                and (active_product_id or len(focused_ids) == 1)
            ):
                inherited_product = active_product_id or next(iter(focused_ids))
                updates["intent"] = "cart_add"
                updates["product_id"] = inherited_product
                updates["product_ids"] = [inherited_product]
                next_active_product = inherited_product
                context_followup = True
            if (
                updates.get("intent")
                in {"product_detail", "cart_add", "cart_update", "cart_remove"}
                and not updates.get("product_id")
                and len(focused_ids) == 1
            ):
                updates["product_id"] = next(iter(focused_ids))
                next_active_product = updates["product_id"]
            elif updates.get("intent") == "product_search" and not context_followup:
                next_active_product = None
        if request.get("variantId"):
            updates["variant_id"] = request["variantId"]
        if request.get("quantity"):
            updates["quantity"] = request["quantity"]
        updates["query"] = updates.get("query") or state.get("message", "")
        if understanding.sort_by != "relevance":
            updates["sort_by"] = understanding.sort_by
            updates["result_limit"] = understanding.result_limit or 1
            updates["intent"] = "product_search"
            updates["query"] = state.get("message", "")
            updates["product_id"] = None
            updates["product_ids"] = []
            next_active_product = None
            context_followup = False
            generic_words = {
                "loai", "san", "pham", "hang", "mac", "mat", "dat", "re",
                "gia", "cao", "thap", "nhat", "ma", "ban", "co", "cua",
                "toi", "minh", "hien", "tai", "la", "bao", "nhieu", "tien",
            }
            scope_words = {
                word
                for word in re.findall(r"[a-z0-9]+", _normalized(state.get("message", "")))
                if word not in generic_words
            }
            if not scope_words:
                active_name = next(
                    (
                        str(item.get("name") or "")
                        for item in focused
                        if str(item.get("id") or "") == active_product_id
                    ),
                    "",
                )
                if not active_name and len(focused) == 1:
                    active_name = str(focused[0].get("name") or "")
                if active_name:
                    updates["query"] = f"{state.get('message', '')} {active_name}".strip()
        filters = SearchFilters.model_validate(updates.get("filters") or {})
        # Internal exclusions can only come from the resolved catalog context,
        # never from IDs proposed by the language model.
        filters.exclude_product_ids = []
        if understanding.colors:
            filters.colors = understanding.colors
        if understanding.sizes:
            filters.sizes = understanding.sizes
        if search_context.mode == "similar":
            if not search_context.anchor_product_id:
                updates["intent"] = "general"
                updates["clarification"] = (
                    "Bạn muốn tìm sản phẩm tương tự với mẫu nào? Hãy chọn hoặc ghi rõ tên một sản phẩm."
                )
                updates["product_id"] = None
                updates["product_ids"] = []
            else:
                updates["intent"] = "product_search"
                updates["product_id"] = None
                updates["product_ids"] = []
                updates["sort_by"] = "relevance"
                updates["result_limit"] = self.settings.result_limit
                updates["query"] = search_context.semantic_query or state.get("message", "")
                next_active_product = None
                context_followup = False
                filters = _apply_search_context(filters, search_context)
        elif search_context.mode == "refine":
            filters = _apply_search_context(filters, search_context)
            updates["query"] = search_context.semantic_query or updates["query"]
        # category_ids is an internal deterministic filter. Never trust IDs
        # proposed by the model; resolve them from the live catalog tree.
        filters.category_ids = []
        if (
            updates["intent"] == "product_search"
            and not updates.get("product_ids")
            and not filters.category_id
            and (filters.category_path or filters.product_type)
        ):
            try:
                category_tree = build_catalog_tree(await self.marketplace.categories())
                filters.category_ids = resolve_category_ids(
                    category_tree, filters.category_path or filters.product_type or ""
                )
            except Exception:
                # Taxonomy resolution narrows a search, but is not required for
                # semantic retrieval to degrade gracefully.
                filters.category_ids = []
        selected_options = _merge_selected_options(
            state.get("message", ""),
            state.get("selected_options", {}),
            filters,
            context_followup,
        )
        search_context = _sync_context_from_filters(search_context, filters)
        search_context.semantic_query = updates["query"]
        if updates["intent"] == "product_detail" and next_active_product:
            search_context.anchor_product_id = next_active_product
            search_context.anchor_product_name = next(
                (
                    str(item.get("name") or "")
                    for item in focused
                    if str(item.get("id") or "") == next_active_product
                ),
                search_context.anchor_product_name,
            )
        updates["filters"] = filters.model_dump()
        shopping_phase = _shopping_phase(
            updates["intent"], filters, updates.get("product_ids", [])
        )
        return {
            "plan": updates,
            "query": updates["query"],
            "retrieval_rounds": 0,
            "products": [],
            "render_product_cards": not context_followup,
            "active_product_id": next_active_product,
            "selected_options": selected_options,
            "search_context": search_context.model_dump(),
            "shopping_phase": shopping_phase,
            "tool_result": {},
            "warnings": [],
            "route": updates["intent"],
            "committed": False,
        }

    @staticmethod
    def _main_route(state: AgentState) -> str:
        if state.get("route") == "resolve_pending":
            return "resolve_pending"
        plan = state.get("plan", {})
        intent = plan.get("intent", "general")
        if intent in {"cart_add", "cart_update", "cart_remove"}:
            return "prepare_cart"
        if intent == "checkout":
            return "prepare_checkout"
        if intent in {
            "browse_categories",
            "product_search",
            "product_detail",
            "cart_view",
            "order_status",
            "policy",
        }:
            return intent
        return "clarify_guard" if plan.get("clarification") else "general"

    @classmethod
    def route_after_plan(cls, state: AgentState) -> list[str]:
        return [cls._main_route(state), "policy_side"]

    async def browse_categories(self, state: AgentState) -> dict:
        categories = await self.marketplace.categories()
        tree = build_catalog_tree(categories)
        return {
            "route": "browse_categories",
            "shopping_phase": "exploring",
            "tool_result": {
                "catalogTree": compact_catalog_tree(tree),
                "sourceCategoryCount": len(categories),
                "rootCategoryCount": len(tree),
            },
        }

    async def retrieve(self, state: AgentState) -> dict:
        plan = AgentPlan.model_validate(state["plan"])
        if plan.product_ids:
            hits = [
                {"productId": product_id, "vectorScore": None, "sources": ["conversation"]}
                for product_id in plan.product_ids
            ]
        else:
            hits = await self.retriever.search(
                state["query"],
                plan.filters,
                limit=max(
                    self.settings.retrieval_limit,
                    plan.result_limit or self.settings.result_limit,
                ),
                sort_by=plan.sort_by,
            )
        requested_limit = plan.result_limit or self.settings.result_limit
        hydration_limit = (
            requested_limit
            if plan.product_ids
            or plan.sort_by != "relevance"
            else max(
                requested_limit,
                min(len(hits), self.settings.retrieval_limit),
            )
        )
        products = await self.marketplace.hydrate_products(
            hits, plan.filters, hydration_limit
        )
        verification: list[dict] = []
        warnings = list(state.get("warnings", []))
        needs_semantic_verifier = False
        if plan.filters.spec_constraints:
            needs_semantic_verifier = requires_semantic_verifier(
                plan.filters.spec_constraints
            )
            grounded_products: list[dict] = []
            for product in products:
                verdict = verify_spec_constraints(
                    product, plan.filters.spec_constraints
                )
                verification.append(
                    {
                        "productId": product.get("id"),
                        "verdict": verdict.verdict,
                        "evidence": list(verdict.evidence),
                        "reason": verdict.reason,
                    }
                )
                if verdict.verdict == "match":
                    grounded_products.append(product)
                elif verdict.verdict == "unknown" and needs_semantic_verifier:
                    grounded_products.append(product)
                elif verdict.verdict == "unknown" and not any(
                    item.strength == "hard"
                    for item in plan.filters.spec_constraints
                ):
                    grounded_products.append(product)
            products = grounded_products
        semantic_scope_constraint: dict | None = None
        raw_turn = state.get("semantic_turn")
        if raw_turn and not plan.product_ids:
            turn = SemanticTurn.model_validate(raw_turn)
            product_task = next(
                (task for task in turn.tasks if task.intent == "product_search"), None
            )
            has_structured_scope = bool(
                plan.filters.product_type
                or plan.filters.category_id
                or plan.filters.category_ids
                or plan.filters.category_path
            )
            if product_task and not has_structured_scope:
                semantic_scope_constraint = {
                    "key": "semantic_product_scope",
                    "operator": "contains",
                    "value": product_task.query or state["query"],
                    "unit": "",
                    "strength": "hard",
                    "source": "semantic_query",
                }
                needs_semantic_verifier = True
        if products and needs_semantic_verifier:
            verifier_constraints = [
                item.model_dump() for item in plan.filters.spec_constraints
            ]
            if semantic_scope_constraint:
                verifier_constraints.append(semantic_scope_constraint)
            try:
                checked = await self.models.verify_candidates(
                    state["query"], verifier_constraints, products
                )
                by_id = {item.productId: item for item in checked.results}
                products = [
                    product
                    for product in products
                    if by_id.get(str(product.get("id")))
                    and by_id[str(product.get("id"))].verdict == "match"
                ]
                verification = [item.model_dump() for item in checked.results]
            except Exception:
                # Model unavailable or out of budget: fall back to evidence we
                # can check deterministically instead of returning nothing.
                # Unknown hard specs and products whose name shares no term
                # with the query still never leak into the response.
                warnings.append("UNVERIFIED")
                deterministic = {
                    str(item.get("productId")): item.get("verdict")
                    for item in verification
                }
                has_hard_specs = any(
                    item.strength == "hard" for item in plan.filters.spec_constraints
                )
                query_terms = set(_search_terms(state["query"]))
                products = [
                    product
                    for product in products
                    if (
                        not has_hard_specs
                        or deterministic.get(str(product.get("id"))) == "match"
                    )
                    and (
                        not semantic_scope_constraint
                        or query_terms & set(_search_terms(str(product.get("name") or "")))
                    )
                ]
        referenced_ids = list(plan.product_ids)
        if not referenced_ids:
            named_products = _focused_references(
                state.get("message", ""), products
            )
            if named_products:
                referenced_ids = [str(item["id"]) for item in named_products]
                products_by_id = {str(item.get("id")): item for item in products}
                products = [
                    products_by_id[product_id]
                    for product_id in referenced_ids
                    if product_id in products_by_id
                ]
            else:
                products = products[:requested_limit]
        ranking_price = None
        if products and plan.sort_by != "relevance":
            def price_getter(product: dict) -> float:
                prices = [
                    float(variant.get("price") or 0)
                    for variant in product.get("variants", [])
                ]
                if not prices:
                    return float(product.get("price") or 0)
                return (
                    max(prices)
                    if plan.sort_by == "price_desc"
                    else min(prices)
                )

            products.sort(
                key=price_getter,
                reverse=plan.sort_by == "price_desc",
            )
            products = products[:requested_limit]
            ranking_price = price_getter(products[0]) if products else None
        rounds = (
            self.settings.max_retrieval_rounds
            if plan.product_ids
            else int(state.get("retrieval_rounds", 0)) + 1
        )
        search_context = SearchContext.model_validate(
            state.get("search_context") or {}
        )
        if len(products) == 1:
            search_context.anchor_product_id = str(products[0].get("id") or "") or None
            search_context.anchor_product_name = str(products[0].get("name") or "")
        resolved_active_product = (
            referenced_ids[0]
            if len(referenced_ids) == 1
            else str(products[0].get("id") or "")
            if len(products) == 1
            else None
        )
        return {
            "route": "product_search",
            "retrieval_hits": hits,
            "retrieval_rounds": rounds,
            "products": products,
            "warnings": list(dict.fromkeys(warnings)),
            "active_product_id": resolved_active_product,
            "search_context": search_context.model_dump(),
            "tool_result": {
                "query": state["query"],
                "filters": plan.filters.model_dump(),
                "found": len(products),
                "referencedProductIds": referenced_ids,
                "sortBy": plan.sort_by,
                "rankingPrice": ranking_price,
                "relaxedConstraints": search_context.relaxed_keys,
                "verification": verification,
            },
        }

    def route_after_retrieval(self, state: AgentState) -> str:
        if state.get("products"):
            return "collect"
        if int(state.get("retrieval_rounds", 0)) >= self.settings.max_retrieval_rounds:
            return "collect"
        plan = AgentPlan.model_validate(state["plan"])
        context = SearchContext.model_validate(state.get("search_context") or {})
        if (context.mode == "similar" and _soft_context_keys(context)) or _next_relaxation(
            plan.filters, context.relaxed_keys
        ):
            return "relax"
        # Retrying the same query with the same filters cannot change the result.
        return "collect"

    async def relax_constraints(self, state: AgentState) -> dict:
        """Loosen one constraint per round instead of asking a model to rewrite.

        Every relaxed key is recorded so the answer can say what changed.
        """
        plan = AgentPlan.model_validate(state["plan"])
        context = SearchContext.model_validate(state.get("search_context") or {})
        warnings = list(state.get("warnings", []))
        relaxable = _soft_context_keys(context) if context.mode == "similar" else set()
        if relaxable:
            context.constraints = [
                constraint
                for constraint in context.constraints
                if constraint.key not in relaxable
            ]
            context.relaxed_keys.extend(sorted(relaxable))
            filters = plan.filters.model_copy(deep=True)
            if relaxable & {"color", "colors", "variant.color"}:
                filters.colors = []
            if relaxable & {"size", "sizes", "variant.size"}:
                filters.sizes = []
            plan.filters = filters
            relaxed_text = ", ".join(
                _RELAX_LABELS.get(key, key) for key in sorted(relaxable)
            )
            warnings.append(
                f"Không có kết quả khớp hoàn toàn; đã nới: {relaxed_text}."
            )
        else:
            key = _next_relaxation(plan.filters, context.relaxed_keys)
            if key:
                plan.filters = _apply_relaxation(plan.filters, key)
                context.relaxed_keys.append(key)
                warnings.append(
                    f"Không có kết quả khớp hoàn toàn; đã nới: {_RELAX_LABELS[key]}."
                )
        return {
            "plan": plan.model_dump(),
            "search_context": context.model_dump(),
            "warnings": warnings,
        }

    async def product_detail(self, state: AgentState) -> dict:
        product_id = state.get("plan", {}).get("product_id")
        if not product_id:
            return {"tool_result": {"clarification": "Bạn muốn hỏi sản phẩm nào?"}}
        # Detail questions need the complete in-stock sibling variants so the
        # agent can answer negative availability (for example "Be có size S?").
        card = await self.marketplace.product_card(product_id, SearchFilters())
        selected_options = {
            "colors": list(state.get("selected_options", {}).get("colors") or []),
            "sizes": list(state.get("selected_options", {}).get("sizes") or []),
        }
        if card:
            inferred = _variant_selection(
                state.get("message", ""),
                card.get("variants", []),
                card.get("name", ""),
            )
            for field in ("colors", "sizes"):
                if inferred[field]:
                    selected_options[field] = inferred[field]
        return {
            "route": "product_detail",
            "products": [card] if card else [],
            "active_product_id": product_id if card else None,
            "selected_options": selected_options,
            "tool_result": {
                "found": bool(card),
                "productId": product_id,
                "selectedOptions": selected_options,
            },
        }

    @staticmethod
    def _auth_error(state: AgentState) -> dict | None:
        if not state.get("user_id") or state.get("role") not in {"buyer", "admin"}:
            return {
                "tool_result": {
                    "error": "Bạn cần đăng nhập bằng tài khoản người mua để thực hiện thao tác này."
                }
            }
        return None

    async def cart_view(self, state: AgentState) -> dict:
        denied = self._auth_error(state)
        if denied:
            return denied
        cart = await self.marketplace.cart(state["user_id"])
        return {"route": "cart_view", "tool_result": {"cart": cart}}

    async def prepare_cart(self, state: AgentState) -> dict:
        denied = self._auth_error(state)
        if denied:
            return denied
        plan = AgentPlan.model_validate(state["plan"])
        if not plan.product_id:
            return {
                "tool_result": {
                    "clarification": "Bạn hãy chọn rõ sản phẩm cần thay đổi trong giỏ hàng."
                }
            }
        variant_id = plan.variant_id
        product_name = plan.product_id
        if plan.intent == "cart_add":
            card = await self.marketplace.product_card(plan.product_id, plan.filters)
            if not card:
                return {"tool_result": {"error": "Sản phẩm không còn bán hoặc đã hết hàng."}}
            product_name = card["name"]
            variants = card.get("variants", [])
            if not variant_id and len(variants) > 1:
                return {
                    "products": [card],
                    "suggestions": [
                        f"Thêm {variant['name']} vào giỏ"
                        for variant in variants[:8]
                        if variant.get("name")
                    ],
                    "tool_result": {
                        "clarification": "Sản phẩm có nhiều biến thể. Hãy chọn màu/size trước khi thêm vào giỏ.",
                        "variants": variants[:12],
                    },
                }
            if not variant_id and len(variants) == 1:
                variant_id = variants[0].get("id")
        labels = {
            "cart_add": "Thêm",
            "cart_update": "Đặt số lượng",
            "cart_remove": "Xóa",
        }
        summary = (
            f"{labels[plan.intent]} {product_name}"
            + (f" — số lượng {plan.quantity}" if plan.intent != "cart_remove" else "")
        )
        action = PendingAction(
            id=f"act_{secrets.token_urlsafe(18)}",
            kind=plan.intent,
            summary=summary,
            payload={
                "productId": plan.product_id,
                "variantId": variant_id,
                "quantity": plan.quantity,
            },
            expires_at=time.time() + self.settings.action_ttl,
        )
        return {
            "route": plan.intent,
            "pending_action": action.model_dump(),
            "tool_result": {
                "confirmationRequired": True,
                "summary": summary,
                "actionId": action.id,
            },
        }

    async def prepare_checkout(self, state: AgentState) -> dict:
        denied = self._auth_error(state)
        if denied:
            return denied
        request = state.get("request", {})
        address_id = request.get("addressId")
        payment_method = request.get("paymentMethod")
        if not address_id:
            addresses = await self.marketplace.addresses(state["user_id"])
            return {
                "tool_result": {
                    "clarification": "Bạn hãy chọn địa chỉ giao hàng trước khi tạo báo giá.",
                    "addresses": addresses,
                }
            }
        if payment_method not in {"cod", "bank_transfer"}:
            return {
                "tool_result": {
                    "clarification": "Bạn chọn thanh toán COD hay chuyển khoản ngân hàng?"
                }
            }
        cart = await self.marketplace.cart(state["user_id"])
        items = cart.get("products", []) if isinstance(cart, dict) else []
        if not items:
            return {"tool_result": {"error": "Giỏ hàng đang trống."}}
        products = [
            {
                "productId": str(item.get("productId")),
                "variantId": item.get("variantId"),
                "quantity": int(item.get("quantity", 1)),
            }
            for item in items
            if item.get("productId") and int(item.get("quantity", 0)) > 0
        ]
        quote = await self.marketplace.checkout_quote(
            state["user_id"],
            state["session_id"],
            products,
            address_id,
            payment_method,
            request.get("voucherCode"),
        )
        confirmation_token = str(quote.pop("confirmationToken", ""))
        if not quote.get("quoteId") or not confirmation_token:
            return {"tool_result": {"error": "Không tạo được báo giá thanh toán."}}
        summary = (
            f"Thanh toán {len(products)} dòng hàng, tổng {float(quote.get('totalPrice', 0)):,.0f}đ "
            f"bằng {'COD' if payment_method == 'cod' else 'chuyển khoản'}"
        )
        action = PendingAction(
            id=f"act_{secrets.token_urlsafe(18)}",
            kind="checkout_confirm",
            summary=summary,
            payload={"quoteId": str(quote["quoteId"])},
            secret=confirmation_token,
            expires_at=time.time() + self.settings.action_ttl,
        )
        return {
            "route": "checkout",
            "pending_action": action.model_dump(),
            "tool_result": {
                "quote": quote,
                "confirmationRequired": True,
                "summary": summary,
                "actionId": action.id,
            },
        }

    async def order_status(self, state: AgentState) -> dict:
        denied = self._auth_error(state)
        if denied:
            return denied
        plan = AgentPlan.model_validate(state["plan"])
        orders = await self.marketplace.orders(state["user_id"])
        if plan.order_id:
            order = next(
                (item for item in orders if int(item.get("id", 0)) == plan.order_id), None
            )
            shipment = (
                await self.marketplace.shipment(state["user_id"], plan.order_id)
                if order
                else None
            )
            return {
                "route": "order_status",
                "tool_result": {"order": order, "shipment": shipment},
            }
        return {"route": "order_status", "tool_result": {"orders": orders[:10]}}

    async def resolve_pending(self, state: AgentState) -> dict:
        denied = self._auth_error(state)
        if denied:
            return denied
        request = state.get("request", {})
        raw = state.get("pending_action")
        if not raw:
            return {"tool_result": {"error": "Không có thao tác nào đang chờ xác nhận."}}
        action = PendingAction.model_validate(raw)
        cancel_id = request.get("cancelActionId")
        confirm_id = request.get("confirmActionId")
        if cancel_id:
            if cancel_id != action.id:
                return {"tool_result": {"error": "Mã hành động không khớp."}}
            return {
                "pending_action": None,
                "route": action.kind,
                "tool_result": {"cancelled": True, "summary": action.summary},
            }
        if confirm_id != action.id:
            return {"tool_result": {"error": "Mã xác nhận không khớp."}}
        if action.expires_at <= time.time():
            return {
                "pending_action": None,
                "tool_result": {"error": "Xác nhận đã hết hạn. Hãy tạo lại thao tác."},
            }
        payload = action.payload
        if action.kind == "cart_add":
            result = await self.marketplace.add_to_cart(
                state["user_id"],
                payload["productId"],
                payload.get("variantId"),
                int(payload["quantity"]),
                action.id,
            )
        elif action.kind in {"cart_update", "cart_remove"}:
            result = await self.marketplace.set_cart_line(
                state["user_id"],
                payload["productId"],
                payload.get("variantId"),
                0 if action.kind == "cart_remove" else int(payload["quantity"]),
            )
        else:
            result = await self.marketplace.confirm_checkout(
                state["user_id"],
                state["session_id"],
                payload["quoteId"],
                action.secret,
            )
        return {
            "pending_action": None,
            "route": action.kind,
            "tool_result": {
                "success": True,
                "summary": action.summary,
                "result": result,
            },
        }

    async def _policy_result(self, question: str) -> tuple[str, list[dict]]:
        if not self.policy:
            return "Mình chưa có kho tài liệu chính sách để kiểm tra thông tin này.", []
        try:
            context, sources = await self.policy.retrieve(question)
        except Exception:
            # A policy lookup failure must not take the rest of the turn down.
            return "Mình chưa tra cứu được chính sách lúc này, bạn thử lại sau nhé.", []
        if not context:
            return "Mình chưa tìm thấy chính sách phù hợp trong kho tài liệu hiện tại.", []
        try:
            answer = await self.models.answer_policy(question, context)
            cited_numbers = {
                int(number)
                for number in re.findall(r"\[Nguồn\s+(\d+)\]", answer)
            }
            cited_sources = [
                source for source in sources if source["number"] in cited_numbers
            ]
            return answer, cited_sources
        except Exception:
            excerpt = str(context[0].get("text") or "")[:900]
            return f"Theo tài liệu đã truy xuất: {excerpt} [Nguồn {context[0]['number']}]", sources

    async def policy_answer(self, state: AgentState) -> dict:
        answer, sources = await self._policy_result(
            state.get("query") or state.get("message", "")
        )
        return {
            "route": "policy",
            "render_product_cards": False,
            "tool_result": {"policyAnswer": answer},
            "sources": sources,
        }

    async def policy_side(self, state: AgentState) -> dict:
        """Answer a secondary policy task in parallel with the main route."""
        raw = state.get("semantic_turn")
        if not raw or state.get("route") in {"policy", "resolve_pending"}:
            return {}
        turn = SemanticTurn.model_validate(raw)
        task = next((item for item in turn.tasks if item.intent == "policy"), None)
        if not task:
            return {}
        answer, sources = await self._policy_result(
            task.query or state.get("message", "")
        )
        return {"policy_appendix": answer, "policy_sources": sources}

    async def collect(self, _state: AgentState) -> dict:
        """Join point of the main route before the policy barrier."""
        return {}

    async def _category_suggestions(self, limit: int = 5) -> list[str]:
        try:
            tree = build_catalog_tree(await self.marketplace.categories())
        except Exception:
            return []
        return [str(node.get("name")) for node in tree if node.get("name")][:limit]

    async def clarify_guard(self, state: AgentState) -> dict:
        """Escalate repeated clarifications instead of asking the same thing again.

        1st: one question with quick replies. 2nd (or the same message again):
        offer structured choices. 3rd and later: offer a human handoff.
        """
        plan = state.get("plan", {})
        clarification = str(plan.get("clarification") or "")
        message_key = _normalized(state.get("message", "")).strip()[:200]
        count = int(state.get("clarify_count") or 0) + 1
        if message_key and message_key == state.get("last_clarify_key"):
            count = max(count, 2)
        route = state.get("route") if state.get("route") in {"clarify", "out_of_scope"} else "clarify"
        focused_names = [
            str(item.get("name"))
            for item in state.get("focused_products", [])
            if item.get("name")
        ]
        asks_product = bool(
            re.search(r"\b(?:san pham nao|mau nao|nhung san pham)\b", _normalized(clarification))
        )
        product_choices = focused_names[:4] if asks_product and focused_names else []
        handoff = False
        if count >= 3:
            text = (
                "Mình vẫn chưa hiểu đúng nhu cầu của bạn. "
                "Bạn có muốn chat trực tiếp với nhân viên shop để được hỗ trợ nhanh hơn không?"
            )
            suggestions = product_choices or await self._category_suggestions(3)
            handoff = True
        elif count == 2:
            text = (
                "Để mình gợi ý nhanh nhé: bạn chọn một mục bên dưới, hoặc mô tả theo mẫu "
                "“loại sản phẩm + ngân sách + người dùng” (ví dụ: “tai nghe dưới 1 triệu cho học sinh”)."
            )
            suggestions = product_choices or await self._category_suggestions(5)
        else:
            text = clarification
            suggestions = product_choices or await self._category_suggestions(4)
        return {
            "route": route,
            "render_product_cards": False,
            "tool_result": {"clarification": text},
            "suggestions": suggestions,
            "handoff": handoff,
            "clarify_count": count,
            "last_clarify_key": message_key,
        }

    async def general(self, state: AgentState) -> dict:
        clarification = str(state.get("plan", {}).get("clarification") or "")
        if clarification:
            return {
                "route": state.get("route", "general"),
                "render_product_cards": False,
                "tool_result": {"clarification": clarification},
            }
        return {
            "route": "general",
            "tool_result": {
                "capabilities": [
                    "tìm và so sánh sản phẩm",
                    "xem hoặc cập nhật giỏ hàng có xác nhận",
                    "xem đơn hàng",
                    "tạo báo giá và xác nhận checkout",
                ]
            },
        }

    @staticmethod
    def _product_attribute_answer(state: AgentState) -> str | None:
        products = state.get("products", [])
        if state.get("semantic_turn"):
            turn = SemanticTurn.model_validate(state["semantic_turn"])
            task = next(
                (
                    item
                    for item in turn.tasks
                    if item.intent in {"product_detail", "compare_products"}
                ),
                None,
            )
            if task and task.intent == "compare_products":
                return None
            requested = task.requested_attributes if task else []
            # Variant-oriented questions (color/size/fit or a bare variant pick)
            # fall through to the deterministic variant logic below.
            spec_question = (
                task is not None
                and len(products) == 1
                and bool(requested)
                and not set(requested) <= {"color", "size", "fit"}
            )
        if state.get("semantic_turn") and spec_question:
            product = products[0]
            facts = normalize_specifications(product.get("specifications") or [])
            answers: list[str] = []
            for attribute in requested:
                if attribute == "price":
                    answers.append(
                        "Giá: "
                        + f"{float(product.get('price') or 0):,.0f}".replace(",", ".")
                        + "đ"
                    )
                    continue
                if attribute == "stock":
                    available = sum(
                        float(item.get("availableStock") or 0)
                        for item in product.get("variants", [])
                    )
                    answers.append(f"Tồn kho khả dụng: {available:g}")
                    continue
                if attribute in {"color", "size"}:
                    values = []
                    for variant in product.get("variants", []):
                        name = str(variant.get("name") or "")
                        if name and name not in values:
                            values.append(name)
                    if values:
                        answers.append("Biến thể: " + ", ".join(values[:12]))
                    continue
                key = canonical_spec_key(attribute)
                matching = [fact for fact in facts if fact.get("key") == key]
                if matching:
                    answers.extend(
                        f"{fact['rawName']}: {fact['rawValue']}" for fact in matching[:3]
                    )
                else:
                    answers.append(f"Chưa có dữ liệu xác minh cho {attribute}")
            return f"{product.get('name', 'Sản phẩm')}: " + "; ".join(answers) + "."
        if len(products) != 1:
            return None
        product = products[0]
        variants = [item for item in product.get("variants", []) if item.get("name")]
        if not variants:
            return None
        message = _normalized(state.get("message", ""))
        plan = state.get("plan", {})
        sort_by = plan.get("sort_by", "relevance") if isinstance(plan, dict) else "relevance"
        if sort_by in {"price_asc", "price_desc"}:
            ranking_price = (state.get("tool_result") or {}).get("rankingPrice")
            if ranking_price is None:
                ranking_price = product.get("price", 0)
            price_text = f"{float(ranking_price):,.0f}".replace(",", ".") + "đ"
            label = "cao nhất" if sort_by == "price_desc" else "thấp nhất"
            return (
                f"{product.get('name', 'Sản phẩm')} là kết quả có giá {label} "
                f"trong nhóm hàng đang tìm và còn hàng, với giá {price_text}."
            )
        if state.get("route") == "product_search":
            return None
        dimensions = _variant_dimensions(variants, product.get("name", ""))
        raw_filters = plan.get("filters", {}) if isinstance(plan, dict) else {}
        selected = state.get("selected_options", {})
        mentioned = _variant_selection(
            state.get("message", ""), variants, product.get("name", "")
        )
        color_source = (
            mentioned.get("colors")
            or selected.get("colors")
            or raw_filters.get("colors")
            or []
        )
        size_source = (
            mentioned.get("sizes")
            or selected.get("sizes")
            or raw_filters.get("sizes")
            or []
        )
        requested_colors = list(
            dict.fromkeys(_normalized(str(value)) for value in color_source if value)
        )
        requested_sizes = list(
            dict.fromkeys(_normalized(str(value)) for value in size_source if value)
        )

        def matching_records(*, use_size: bool = True) -> list[dict]:
            return [
                record
                for record in dimensions["records"]
                if (
                    not requested_colors
                    or record["color"] in requested_colors
                )
                and (
                    not use_size
                    or not requested_sizes
                    or bool(record["sizes"] & set(requested_sizes))
                )
            ]

        color_records = matching_records(use_size=False)
        size_order = {
            value: index
            for index, value in enumerate(
                ("xs", "s", "m", "l", "xl", "xxl", "2xl", "3xl", "4xl")
            )
        }
        available_size_keys = sorted(
            {size for record in color_records for size in record["sizes"]},
            key=lambda value: (size_order.get(value, 999), value),
        )
        available_sizes = [
            dimensions["sizes"].get(key, key.upper()) for key in available_size_keys
        ]
        color_display = [
            dimensions["colors"].get(value, value) for value in requested_colors
        ]
        color_suffix = f" màu {', '.join(color_display)}" if color_display else ""

        asks_fit = bool(
            re.search(r"\b(?:lam sao|tu van|phu hop|vua)\b.{0,40}\bsize\b", message)
            or re.search(r"\bsize\b.{0,30}\b(?:phu hop|vua)\b", message)
            or re.search(r"\b(?:cao|nang|can nang)\b", message)
            or re.search(r"\b\d+m\d{1,2}\b", message)
            or re.search(r"\b\d+(?:[.,]\d+)?\s*(?:kg|cm)\b", message)
        )
        if asks_fit:
            if _has_size_chart(product):
                return None
            size_text = ", ".join(available_sizes) if available_sizes else "chưa xác định"
            return (
                f"{product.get('name', 'Sản phẩm')} chưa có bảng size và cũng không có khoảng số đo đủ rõ để "
                "suy ra size từ chiều cao/cân nặng. "
                f"Các size đang còn hàng{color_suffix}: {size_text}. "
                "Bạn nên đối chiếu bảng size riêng của sản phẩm hoặc hỏi shop trước khi chọn."
            )

        asks_size = bool(
            re.search(r"\b(?:size|kich thuoc)\b", message)
            or mentioned.get("sizes")
        )
        if asks_size:
            if requested_sizes:
                relevant = matching_records()
                requested_display = [
                    dimensions["sizes"].get(value, value.upper())
                    for value in requested_sizes
                ]
                size_text = ", ".join(requested_display)
                if relevant:
                    prices = sorted(
                        {
                            float(
                                record["variant"].get(
                                    "price", product.get("price", 0)
                                )
                                or 0
                            )
                            for record in relevant
                        }
                    )
                    price_text = " – ".join(
                        f"{price:,.0f}".replace(",", ".") + "đ"
                        for price in prices
                    )
                    return (
                        f"{product.get('name', 'Sản phẩm')}{color_suffix}, size {size_text} "
                        f"đang còn hàng với giá {price_text}. Bạn có muốn thêm lựa chọn này vào giỏ không?"
                    )
                alternatives = ", ".join(available_sizes) or "không còn size nào"
                return (
                    f"{product.get('name', 'Sản phẩm')}{color_suffix} không có size {size_text} "
                    f"đang còn hàng. Các size hiện có: {alternatives}."
                )
            return (
                f"{product.get('name', 'Sản phẩm')}{color_suffix} có các size đang còn hàng: "
                + (", ".join(available_sizes) if available_sizes else "chưa có thông tin")
                + "."
            )

        asks_colors = bool(
            re.search(r"\bmau\b", message)
            and re.search(r"\b(?:gi|nao|nhung|cac|co)\b", message)
        )
        if asks_colors:
            if dimensions["colors"]:
                colors = list(dimensions["colors"].values())
                return (
                    f"{product.get('name', 'Sản phẩm')} có các màu: "
                    + ", ".join(colors)
                    + "."
                )
            return (
                f"Catalog hiện chưa có thông tin màu hoặc biến thể màu cho "
                f"{product.get('name', 'sản phẩm này')}."
            )

        asks_price = bool(re.search(r"\b(?:gia|bao nhieu)\b", message))
        relevant = matching_records()
        if not relevant:
            return (
                f"{product.get('name', 'Sản phẩm')} không có biến thể "
                + " ".join([*requested_colors, *requested_sizes])
                + " đang còn hàng."
            )
        if not asks_price:
            if mentioned.get("colors") and available_sizes:
                return (
                    f"{product.get('name', 'Sản phẩm')}{color_suffix} có các size đang còn hàng: "
                    + ", ".join(available_sizes)
                    + ". Bạn muốn chọn size nào?"
                )
            return None
        prices = sorted(
            {
                float(
                    record["variant"].get("price", product.get("price", 0)) or 0
                )
                for record in relevant
            }
        )
        price_text = " – ".join(
            f"{price:,.0f}".replace(",", ".") + "đ" for price in prices
        )
        option_text = ", ".join(
            [
                *color_display,
                *[
                    dimensions["sizes"].get(value, value.upper())
                    for value in requested_sizes
                ],
            ]
        )
        return (
            f"{product.get('name', 'Sản phẩm')}"
            + (f" màu/biến thể {option_text}" if option_text else "")
            + f" có giá {price_text}."
        )

    @staticmethod
    def _fallback_answer(state: AgentState) -> str:
        result = state.get("tool_result") or {}
        if isinstance(result, dict):
            if result.get("policyAnswer"):
                return str(result["policyAnswer"])
            if result.get("error"):
                return str(result["error"])
            if result.get("clarification"):
                return str(result["clarification"])
            if result.get("confirmationRequired"):
                return f"Vui lòng kiểm tra và xác nhận: {result.get('summary', '')}."
            if result.get("cancelled"):
                return f"Đã hủy: {result.get('summary', 'thao tác đang chờ')}."
            if result.get("success"):
                return f"Đã thực hiện thành công: {result.get('summary', '')}."
            if "catalogTree" in result:
                names = [item.get("name", "") for item in result["catalogTree"][:12]]
                return "Các danh mục hiện có: " + ", ".join(name for name in names if name) + "."
            if "cart" in result:
                count = len(result.get("cart", {}).get("products", []))
                return f"Giỏ hàng hiện có {count} dòng sản phẩm."
            if result.get("found") == 0:
                return "Mình chưa tìm thấy sản phẩm còn hàng phù hợp. Bạn muốn nới điều kiện nào?"
        products = state.get("products", [])
        if products:
            return f"Mình tìm thấy {len(products)} sản phẩm phù hợp và còn hàng."
        return "Mình có thể giúp tìm sản phẩm, quản lý giỏ hàng, xem đơn và checkout có xác nhận."

    async def finalize(self, state: AgentState) -> dict:
        sources = list(state.get("sources", []))
        multi_route = False
        policy_appendix = str(state.get("policy_appendix") or "")
        if policy_appendix:
            sources = list(state.get("policy_sources", []))
            turn = SemanticTurn.model_validate(state["semantic_turn"])
            multi_route = len(turn.tasks) > 1
        direct = self._fallback_answer(state)
        attribute_answer = self._product_attribute_answer(state)
        result = state.get("tool_result") or {}
        products = state.get("products", [])
        plan = state.get("plan", {}) if isinstance(state.get("plan"), dict) else {}
        relaxed = (
            list(result.get("relaxedConstraints") or []) if isinstance(result, dict) else []
        )
        # Product cards already carry the facts of a plain search, so a
        # template answer saves a model call; comparisons and relaxed or
        # assumed searches still need the model to explain themselves.
        template_answer = (
            _search_template_answer(products)
            if state.get("route") == "product_search"
            and products
            and len(plan.get("product_ids") or []) < 2
            and not relaxed
            else ""
        )
        model_result = (
            {**result, "shoppingPhase": state.get("shopping_phase", "exploring")}
            if isinstance(result, dict)
            else result
        )
        should_be_deterministic = isinstance(result, dict) and any(
            key in result
            for key in (
                "error", "clarification", "confirmationRequired", "cancelled", "success", "policyAnswer"
            )
        )
        if attribute_answer:
            answer = attribute_answer
        elif should_be_deterministic:
            answer = direct
        elif template_answer:
            answer = template_answer
        else:
            try:
                answer = await self.models.answer(
                    state.get("message", ""),
                    state.get("plan", {}),
                    model_result,
                    products,
                    state.get("history", []),
                )
            except Exception:
                answer = direct
                if products and relaxed:
                    answer = (
                        _search_template_answer(products)
                        + " Lưu ý: không có mẫu khớp hoàn toàn nên mình đã nới "
                        + ", ".join(_RELAX_LABELS.get(key, key) for key in relaxed)
                        + "."
                    )
        suggestions = list(state.get("suggestions") or [])
        if "ASSUMED_INTENT" in state.get("warnings", []) and state.get("route") == "product_search":
            query = str(plan.get("query") or state.get("message", "")).strip()
            answer = f"Mình hiểu bạn đang tìm “{query}”. {answer}"
            suggestions = suggestions or await self._category_suggestions(4)
        skipped = list(state.get("skipped_tasks") or [])
        if skipped:
            answer += (
                "\n\nMình đã xử lý yêu cầu chính trước; phần "
                + ", ".join(skipped)
                + " bạn nhắn tiếp giúp mình nhé."
            )
        if policy_appendix:
            answer = f"{answer}\n\n{policy_appendix}" if answer else policy_appendix
        clarifying = state.get("route") in {"clarify", "out_of_scope"}
        new_focused = [
            {"id": item.get("id"), "name": item.get("name", "")}
            for item in state.get("products", [])
            if item.get("id")
        ][:6]
        focused = state.get("focused_products", [])
        if state.get("semantic_turn"):
            turn = SemanticTurn.model_validate(state["semantic_turn"])
            if turn.focus_update == "clear":
                focused = []
            elif turn.focus_update == "replace":
                focused = new_focused
            elif new_focused and state.get("route") == "product_search":
                focused = new_focused
        elif new_focused:
            focused = new_focused
        return {
            "answer": answer,
            "focused_products": focused,
            "sources": sources,
            "suggestions": suggestions[:8],
            "handoff": bool(state.get("handoff")) and clarifying,
            "clarify_count": int(state.get("clarify_count") or 0) if clarifying else 0,
            "last_clarify_key": state.get("last_clarify_key", "") if clarifying else "",
            "route": "multi" if multi_route else state.get("route", "general"),
            "committed": True,
        }

