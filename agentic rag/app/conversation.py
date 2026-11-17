"""Conversation helpers shared by the supervisor and both agents.

Pure functions over the dialogue state: product references, variant
dimensions, search-context bookkeeping, constraint relaxation and the
deterministic interpreter that backs the semantic model when it fails.
"""

from __future__ import annotations

import re
import unicodedata

from .indexer.documents import PRODUCT_TYPES
from .search_parser import mentions_other_product, parse_search_turn
from .schemas import (
    ConstraintDelta,
    SearchConstraint,
    SearchContext,
    SearchFilters,
    SemanticConstraint,
    SemanticReference,
    SemanticTask,
    SemanticTurn,
    TurnUnderstanding,
)

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
    if mentions_other_product(message):
        # "áo khoác không phải màu đen" names a product kind (and negates the
        # colour): it is a new search, not a variant pick on the active item.
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
    # No rule for "cái nào rẻ nhất": a message that names a product kind
    # never reaches here (mentions_other_product), so such a rule could only
    # sort the whole catalog. The model, or parse_followup_turn with the
    # last search, ties it to the products being discussed.
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


_PRODUCT_HEADS = sorted(
    {term.strip() for _kind, terms in PRODUCT_TYPES for term in terms},
    key=len,
    reverse=True,
)


def _product_head(phrase: str) -> str:
    """The known product kind a phrase starts with ("noi chien" for "nồi
    chiên không dầu"), or "" when the phrase does not start with one."""
    folded = " ".join(re.findall(r"[a-z0-9]+", _normalized(phrase)))
    return next(
        (term for term in _PRODUCT_HEADS if re.match(rf"{re.escape(term)}(?!\w)", folded)),
        "",
    )


_IMAGE_CAPTION_KEYS = {"price", "min_price", "max_price", "color", "size", "brand"}


def _image_search_turn(message: str) -> SemanticTurn:
    parsed = parse_search_turn(message, strict=False) if message.strip() else None
    constraints = [
        item for item in (parsed.tasks[0].constraints if parsed else [])
        if item.key in _IMAGE_CAPTION_KEYS
    ]
    return SemanticTurn(
        tasks=[SemanticTask(
            intent="product_search",
            query=message.strip() or "sản phẩm giống ảnh",
            constraints=constraints,
        )],
        conversation_action="new",
        focus_update="replace",
        confidence=0.95,
    )


_RELAX_LABELS = {
    "spec.soft": "thuộc tính phụ",
    "category": "danh mục",
    "price": "khoảng giá (±15%)",
    "variant.color": "màu",
    "variant.size": "kích thước/size",
    "brand": "thương hiệu",
    "spec.hard": "thông số (chưa xác nhận được)",
}


def _category_matches_kind(filters: SearchFilters) -> bool:
    """True when the category branch is the kind of product the customer
    named, so loosening it would show another kind (a soundbar for "loa
    bluetooth", a laptop bag for "laptop").

    Vietnamese product phrases start with their head noun ("balo laptop" is a
    bag), so the branch fits when its leaf starts with the same head word. A
    branch resolved from the kind itself, without a path, fits by definition.
    """
    kind = _normalized(filters.product_type or "").split()
    if not kind:
        return False
    if not filters.category_path:
        return True
    leaf = _normalized(re.split(r"\s*[›>/]\s*", filters.category_path)[-1]).split()
    return bool(leaf) and leaf[0] == kind[0]


def _next_relaxation(filters: SearchFilters, relaxed: list[str]) -> str | None:
    """Pick the next constraint to loosen, least important first."""
    has_category = bool(filters.category_ids or filters.category_id)
    trusted_category = has_category and _category_matches_kind(filters)
    candidates = (
        ("spec.soft", any(item.strength == "soft" for item in filters.spec_constraints)),
        # A branch resolved from the phrase can be the wrong one ("balo
        # laptop" -> Laptop); semantic search still finds the right kind.
        ("category", has_category and not trusted_category),
        ("price", filters.max_price is not None or filters.min_price is not None),
        ("variant.color", bool(filters.colors)),
        ("variant.size", bool(filters.sizes)),
        ("brand", bool(filters.brand)),
        # The branch the customer named is loosened only after everything
        # else: another kind of product is rarely what they meant.
        ("category", trusted_category),
        # Last resort: most listings carry no evidence for features such as
        # "chống nước"; show the closest products and say it is unconfirmed.
        ("spec.hard", any(item.strength == "hard" for item in filters.spec_constraints)),
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
    elif key == "category":
        relaxed.category_ids = []
        relaxed.category_id = None
        relaxed.category_path = None
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
    elif key == "spec.hard":
        relaxed.spec_constraints = []
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
