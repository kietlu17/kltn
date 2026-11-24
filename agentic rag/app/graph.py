"""Supervisor graph of the shopping assistant.

One semantic decision per turn (``understand``) feeds a planner that routes
the turn to a specialist:

* ProductAgent: customer Q&A - catalog search, product details,
  comparisons, policies and web research for the hard cases;
* OrderAgent: cart, checkout, order tracking and confirmations.

Policy and web research for a secondary task run as side branches next to
the main route; ``finalize`` joins everything and writes the answer.
"""

from __future__ import annotations

import asyncio
import logging
import re

from langgraph.graph import END, START, StateGraph

from .agents import OrderAgent, ProductAgent
from .agents.advisor import ShoppingAdvisor
from .agents.order import ORDER_NODES
from .config import AgenticSettings
from .memory import apply_profile_updates, memory_context, memory_note, resolved_message
from .mentions import MAX_NAMED_CARDS, named_products
from .conversation import (  # noqa: F401 - re-exported for callers and tests
    _last_assistant_message,
    _INTENT_LABELS,
    _RELAX_LABELS,
    _apply_constraint_deltas,
    _apply_relaxation,
    _apply_search_context,
    _continues_active_product,
    _deterministic_turn,
    _fallback_understanding,
    _focused_references,
    _image_search_turn,
    _last_offer_is_add_to_cart,
    _merge_selected_options,
    _next_relaxation,
    _normalized,
    _price_text,
    _requests_purchase,
    _search_template_answer,
    _shopping_phase,
    _size_tokens,
    _sync_context_from_filters,
)
from .search_parser import _money as _parse_money
from .search_parser import (
    mentions_other_product,
    parse_checkout_turn,
    parse_followup_turn,
    parse_policy_turn,
    parse_search_turn,
    parse_smalltalk_turn,
    reconcile_turn,
)
from .schemas import (
    AgentPlan,
    AgentState,
    SearchConstraint,
    SearchContext,
    SearchFilters,
    SemanticConstraint,
    SemanticTask,
    SemanticTurn,
    TurnUnderstanding,
)
from .taxonomy import (
    build_catalog_tree,
    category_path_list,
    resolve_category_ids,
    resolve_category_path,
)

log = logging.getLogger(__name__)

_CONFIRM_REPLY = re.compile(
    r"(?:xac nhan|dong y|ok|oke|okay|okie|co|chot|chot don|duoc|dc|u|uh|vang|yes|confirm|"
    r"dat luon|them di|them luon|lam di|xac nhan nhe|ok luon|dong y nhe|co nhe|co a|"
    r"thanh toan di|dat hang di)"
)
_CANCEL_REPLY = re.compile(
    r"(?:huy|huy di|huy nhe|khong|ko|thoi|thoi khoi|thoi khong|thoi khong can|thoi bo|bo qua|bo di|"
    r"cancel|khong them|khong can|khong can dau|khong can nua|khong lay|khong mua|khong dat|de sau|"
    r"chua|chua can|chua can dau|chua can nua|de khi khac)"
)


_VAGUE_BRAND = re.compile(
    r"\b(?:cung hang|cung thuong hieu|thuong hieu|hang nao|khong can|bat ky|uy tin|noi tieng|chinh hang)\b"
)
_NEUTRAL = re.compile(r"\b(?:trung tinh|neutral|basic|don gian)\b")
_NEUTRAL_COLORS = ["be", "đen", "trắng", "xám", "nâu", "kem"]
_SIZE_VALUE = re.compile(r"(?:xxs|xs|s|m|l|xl|xxl|xxxl|[2-5]xl|free ?size|[1-5]?\d(?:[.,]5)?)")
_UNVERIFIABLE_KEY = re.compile(
    r"(?:deliver|shipping|ship|giao|gift|wrap|goi qua|personali|ca nhan|warranty|bao hanh|"
    r"total|tong|location|origin|seller|authentic|chinh hang|return|doi tra|voucher|discount)"
)
# Spec keys whose numbers the catalog carries: only these can stay hard.
_MEASURABLE_KEY = re.compile(
    r"(?:storage|rom|ram|memory|screen|display|battery|capacity|dung tich|weight|power|"
    r"wattage|refresh|camera|resolution|size_inch|inch|volume|area|dien tich)"
)


def _soften(constraint: SemanticConstraint) -> SemanticConstraint:
    """Keep a spec hard only when it is a number the listings state
    (256GB, 16GB RAM, 5 lít); wishes ("không quá nặng", "chống nước",
    "dễ vệ sinh") rank the results instead of emptying them."""
    if constraint.strength != "hard":
        return constraint
    value = constraint.value
    numeric = isinstance(value, (int, float)) or bool(
        re.fullmatch(r"\s*\d+(?:[.,]\d+)?\s*[a-zA-Z%²]*\s*", str(value))
    )
    if numeric and _MEASURABLE_KEY.search(constraint.key.casefold()):
        return constraint
    return constraint.model_copy(update={"strength": "soft"})


# A message with several product searches: results kept for the main one
# and shown for each other one.
_MAIN_RESULTS_WITH_EXTRAS = 4
_EXTRA_SEARCH_RESULTS = 3
# Products shown in a session that a later reply may still name.
_MAX_RECENT_PRODUCTS = 40
# Order-agent intents answered from the customer's real cart or orders.
_CART_READING_INTENTS = {"checkout", "cart_view", "cart_update", "cart_remove", "order_status"}
# Matched on _normalized text: a bare "yes" to the assistant's question.
_AFFIRMATION = re.compile(
    r"^(?:dung|dung roi|dung vay|dung the|phai|phai roi|u|uh|um|uhm|vang|da|da dung|co|ok|oke|okay|yes|chuan|chinh xac)"
    r"(?:\s+(?:roi|a|nhe|nha|ban|em|shop|vay))*[\s.!]*$"
)
# A clarification that only re-states the request and asks for a yes/no.
_CONFIRMING_QUESTION = re.compile(r"\b(?:dung khong|phai khong|co phai|dung chua|phai chu)\b")


def _clarified_search(turn: SemanticTurn, state: AgentState, message: str) -> SemanticTurn | None:
    """A product search to run instead of another clarifying question.

    The assistant asks at most once in a row: right after a clarification
    the customer's answer ("áo thun", "đúng") is joined with the request it
    answers. A question that only asks "…đúng không?" about a search the
    model already understood is skipped too. None keeps the clarification.
    """
    search = next(
        (
            task for task in turn.tasks
            if task.intent == "product_search" and re.search(r"\w{2,}", task.query)
        ),
        None,
    )
    question = _normalized(turn.clarification_question or "")
    confirming = bool(_CONFIRMING_QUESTION.search(question))
    if search and confirming:
        return turn.model_copy(update={"tasks": [search], "needs_clarification": False,
                                       "clarification_question": "", "conversation_action": "continue"})
    if int(state.get("clarify_count") or 0) < 1:
        return None
    # Only when the need is already understood: the model now only asks
    # "…đúng không?", the customer said yes to such a question, or the model
    # proposes a search it is fairly sure of. A vague "cái đó đó" keeps being
    # asked (and is escalated by clarify_guard).
    last_question = _normalized(_last_assistant_message(state.get("history") or []))
    said_yes = bool(
        _CONFIRMING_QUESTION.search(last_question) and _AFFIRMATION.match(_normalized(message).strip())
    )
    if not (confirming or said_yes or (search and turn.confidence >= 0.5)):
        return None
    if search:
        query = search.query.strip()
    else:
        # The model gave no search: rebuild it from what the customer said
        # since the first question (its request included), dropping bare
        # yes-words.
        asked = int(state.get("clarify_count") or 0)
        said = [
            str(item.get("content") or "")
            for item in (state.get("history") or [])
            if item.get("role") == "user"
        ][-asked:] + [message]
        parts = [
            text.strip() for text in said
            if text.strip() and not _AFFIRMATION.match(_normalized(text).strip())
            and text.strip() != "[Hành động UI]"
        ]
        query = " ".join(dict.fromkeys(parts))[:300]
        if not query:
            return None
        search = SemanticTask(intent="product_search", query=query)
    return turn.model_copy(update={
        "tasks": [search.model_copy(update={"query": query})],
        "needs_clarification": False,
        "clarification_question": "",
        "conversation_action": "continue",
        "focus_update": "replace",
        "confidence": max(turn.confidence, 0.6),
    })


def _ui_selection_intent(request: dict) -> str | None:
    """The intent of a turn sent from a checkbox picker of the widget."""
    if request.get("confirmActionId") or request.get("cancelActionId"):
        return None
    if request.get("variantIds") and request.get("referenceProductId"):
        return "cart_add"
    if request.get("checkoutLineIds"):
        return "checkout"
    return None


_GENERIC_CLARIFICATIONS = {
    "ban co the noi ro hon san pham hoac nhu cau can ho tro khong",
    "minh chua hieu chac yeu cau ban muon tim san pham hoi chinh sach hay thao tac voi don hang",
}


def _is_generic_clarification(question: str) -> bool:
    key = " ".join(re.findall(r"[a-z0-9]+", _normalized(question or "")))
    return not key or key in _GENERIC_CLARIFICATIONS


def _contextual_clarification(profile: dict, last_search: dict) -> str | None:
    """A clarifying question built from what the customer already said."""
    recipient = str((profile or {}).get("recipient") or "").strip()
    use_case = str((profile or {}).get("use_case") or "").strip()
    if recipient:
        hint = f" để {use_case}" if use_case else ""
        return (
            f"Bạn muốn tìm món gì cho {recipient}{hint}: đồ công nghệ (điện thoại, tai nghe, đồng hồ), "
            "đồ chăm sóc sức khỏe hay quần áo, phụ kiện? Ngân sách khoảng bao nhiêu để mình gợi ý sát hơn?"
        )
    kind = str((last_search or {}).get("product_type") or "").strip()
    if kind:
        return (
            f"Bạn đang hỏi thêm về {kind} vừa xem hay muốn tìm món khác? "
            "Nói mình tiêu chí bạn quan tâm (giá, hãng, tính năng) nhé."
        )
    return None


def _price_value(value) -> float | None:
    """A price constraint's value in VND: a number, a numeric string or a
    phrase with an amount ("8 triệu"); None when it states no amount."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else None
    if isinstance(value, str):
        match = re.search(
            r"(\d+(?:[.,]\d+)*)\s*(trieu|nghin|ngan|dong|vnd|tr|cu|k|d)?(?![a-z])",
            _normalized(value),
        )
        if not match:
            return None
        amount = _parse_money(match.group(1), match.group(2))
        if amount is None and not match.group(2):
            # A bare small number is not a price for the text parser, but a
            # price slot holding "8000000" or "500" is one.
            try:
                amount = float(match.group(1).replace(",", "."))
            except ValueError:
                return None
        return amount
    return None


def _pending_reply(message: str) -> str | None:
    """'confirm' / 'cancel' when the whole message only answers the action
    waiting for confirmation; anything longer goes to the model."""
    text = re.sub(r"[^\w\s]", " ", _normalized(message)).split()
    phrase = " ".join(
        word for word in text if word not in {"nhe", "nha", "a", "ban", "minh", "giup", "oi", "shop"}
    )
    if not phrase or len(text) > 5:
        return None
    if _CONFIRM_REPLY.fullmatch(phrase):
        return "confirm"
    if _CANCEL_REPLY.fullmatch(phrase):
        return "cancel"
    return None


_EXPLICIT_CONFIRM = re.compile(
    r"^\W*(?:xac nhan|dong y|ok|oke|okay|chot|dat luon|dat hang|thanh toan|them (?:di|luon|vao gio)|"
    r"co,? them|lay (?:di|luon)|duoc,? them)\b"
)
_EXPLICIT_CANCEL = re.compile(r"^\W*(?:huy|khong them|thoi khong|bo qua|khong dat|dung lai|cancel)\b")


_ATTRIBUTE_HINTS = {
    "weight": r"\b(?:khoi luong|trong luong|nang|weight)\b",
    "battery": r"\b(?:pin|battery)\b",
    "camera": r"\b(?:camera|chup|quay)\b",
    "screen": r"\b(?:man hinh|screen|display|tan so quet|do phan giai man)\b",
    "ram": r"\b(?:ram)\b",
    "storage": r"\b(?:rom|bo nho trong|dung luong luu tru|o cung|ssd|storage)\b",
    "charging": r"\b(?:sac|charging)\b",
    "chip": r"\b(?:chip|cpu|vi xu ly|processor)\b",
}
_ATTRIBUTE_FROM_REQUEST = {
    "weight": "weight", "battery_capacity": "battery", "battery_life": "battery", "battery": "battery",
    "camera": "camera", "screen_size": "screen", "display": "screen", "ram": "ram", "storage": "storage",
    "charging": "charging", "chip": "chip", "cpu": "chip",
}


def _compared_attributes(message: str, requested: list[str]) -> list[str]:
    attributes = [_ATTRIBUTE_FROM_REQUEST[item] for item in requested if item in _ATTRIBUTE_FROM_REQUEST]
    text = _normalized(message)
    for attribute, pattern in _ATTRIBUTE_HINTS.items():
        if re.search(pattern, text) or (attribute == "weight" and re.search(r"\bnhe\b", text)):
            attributes.append(attribute)
    return list(dict.fromkeys(attributes))[:4]


def _number(value: str, unit_scale: dict[str, float]) -> float | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g|mah|wh)\b", _normalized(value))
    if not match:
        return None
    return float(match.group(1).replace(",", ".")) * unit_scale.get(match.group(2), 1)


def _spec_comparison(state: AgentState) -> dict | None:
    """Exact values of the attributes being compared ("cái nào nhẹ hơn",
    "pin trâu nhất"), read from each listing, so the answer model compares
    numbers instead of guessing."""
    products = [item for item in state.get("products", []) if item.get("specifications")]
    if len(products) < 2:
        return None
    turn = state.get("semantic_turn") or {}
    requested = [
        attribute
        for task in turn.get("tasks", [])
        for attribute in task.get("requested_attributes", [])
    ]
    attributes = _compared_attributes(state.get("message", ""), requested)
    if not attributes:
        return None
    rows = []
    for position, product in enumerate(products[:6], 1):
        values = {}
        for attribute in attributes:
            pattern = _ATTRIBUTE_HINTS[attribute]
            found = [
                f"{spec.get('name')}: {spec.get('value')}"
                for spec in product.get("specifications", [])
                if re.search(pattern, _normalized(str(spec.get("name") or "")))
            ][:3]
            values[attribute] = "; ".join(found) if found else "chưa có trong tin đăng"
        rows.append({"position": position, "name": product.get("name"), "values": values})
    summary = {}
    for attribute, scale, best in (("weight", {"kg": 1000, "g": 1}, min), ("battery", {"mah": 1, "wh": 1}, max)):
        if attribute not in attributes:
            continue
        measured = [
            (number, row["name"])
            for row in rows
            if (number := _number(row["values"][attribute], scale)) is not None
        ]
        if len(measured) >= 2:
            value, name = best(measured)
            label = "nhẹ nhất" if attribute == "weight" else "pin lớn nhất"
            summary[attribute] = f"{label}: {name}"
    return {"attributes": attributes, "rows": rows, "computed": summary}


_ACTION_CLAIM = re.compile(
    r"(?<!\w)(?:mình|tôi|em)\s+(?:đã|vừa)\s+(?:thêm|bỏ|xóa|xoá|cập nhật|đặt|gửi|tạo|hủy|huỷ)\b[^.!?\n]*"
    r"(?:giỏ|đơn|yêu cầu)[^.!?\n]*[.!?]?",
    re.IGNORECASE,
)


def _drop_unbacked_action_claims(answer: str, tool_result: dict) -> str:
    """The model must never report a cart change, order or ticket that no
    tool performed; such sentences are replaced by an offer to do it."""
    if not answer or (isinstance(tool_result, dict) and tool_result.get("success")):
        return answer
    cleaned, count = _ACTION_CLAIM.subn("", answer)
    if not count:
        return answer
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    offer = "Bạn chọn phiên bản và nhắn “thêm vào giỏ”, mình sẽ tạo yêu cầu để bạn xác nhận nhé."
    return f"{cleaned}\n\n{offer}" if cleaned else offer


def _explicit_pending_answer(message: str, decision: str) -> bool:
    text = _normalized(message)
    return bool((_EXPLICIT_CONFIRM if decision == "confirm" else _EXPLICIT_CANCEL).search(text))


class AgenticShoppingGraph:
    def __init__(
        self,
        settings: AgenticSettings,
        models_gateway,
        retriever,
        marketplace,
        policy=None,
        checkpointer=None,
        reranker=None,
        visual=None,
    ):
        self.settings = settings
        self.models = models_gateway
        self.retriever = retriever
        self.marketplace = marketplace
        self.policy = policy
        self.reranker = reranker
        self.visual = visual
        self.product_agent = ProductAgent(
            settings, models_gateway, retriever, marketplace,
            policy=policy, reranker=reranker, visual=visual,
        )
        self.order_agent = OrderAgent(settings, models_gateway, marketplace)
        self.advisor = ShoppingAdvisor(settings, models_gateway, retriever, marketplace)
        self.graph = self._compile(checkpointer)

    # Product answers are composed from catalog facts by the product agent.
    _product_attribute_answer = staticmethod(ProductAgent._product_attribute_answer)

    def _compile(self, checkpointer):
        builder = StateGraph(AgentState)
        builder.add_node("understand", self.understand)
        builder.add_node("resolve_context", self.resolve_context)
        builder.add_node("plan", self.plan)
        builder.add_node("clarify_guard", self.clarify_guard)
        builder.add_node("general", self.general)
        builder.add_node("collect", self.collect)
        builder.add_node("finalize", self.finalize)
        builder.add_node("search_side", self.search_side)
        builder.add_edge(START, "understand")
        builder.add_edge("understand", "resolve_context")
        builder.add_edge("resolve_context", "plan")
        self.product_agent.register(builder, join="collect")
        self.order_agent.register(builder, join="collect")
        # The main route and the side branches (policy, web research) run in
        # the same superstep; finalize waits for all of them.
        builder.add_node("advisor", self.run_advisor)
        # A failed advisor turn continues on the route the graph planned.
        builder.add_conditional_edges(
            "advisor",
            self.route_after_advisor,
            {"collect": "collect", "retrieve": "retrieve", "product_detail": "product_detail"},
        )
        routes = {
            "advisor": "advisor",
            "browse_categories": "browse_categories",
            "product_search": "retrieve",
            "product_detail": "product_detail",
            "policy": "policy",
            "clarify_guard": "clarify_guard",
            "general": "general",
            "policy_side": "policy_side",
            "research_side": "research_side",
            "search_side": "search_side",
            **{node: node for node in ORDER_NODES},
        }
        builder.add_conditional_edges("plan", self.route_after_plan, routes)
        for node in ("clarify_guard", "general"):
            builder.add_edge(node, "collect")
        builder.add_edge(["collect", "policy_side", "research_side", "search_side"], "finalize")
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
        # LLM-first: the semantic model decides every text turn; the rule
        # fast path and the hedged parse only back it up when it fails.
        llm_first = bool(getattr(settings, "llm_first", False))
        turn = None if llm_first else _deterministic_turn(
            message, history, active_product_id, selected
        )
        ui_intent = _ui_selection_intent(state.get("request") or {})
        if ui_intent:
            # Boxes ticked in the widget's picker: the request names exactly
            # what to add or pay, so no model reads the message.
            return {
                "semantic_turn": SemanticTurn(
                    tasks=[SemanticTask(intent=ui_intent, query=message)],
                    conversation_action="continue",
                    confidence=1,
                ).model_dump(),
                "understanding": {},
                "warnings": [*warnings, "UI_SELECTION"],
            }
        pending_reply = _pending_reply(message) if state.get("pending_action") else None
        if pending_reply and not (state.get("request") or {}).get("image"):
            # A bare "xác nhận" / "thôi" answers the waiting action at once:
            # no model call, same effect as the confirm or cancel button.
            return {
                "semantic_turn": SemanticTurn(
                    tasks=[SemanticTask(intent="general", query=message)],
                    conversation_action="continue",
                    confidence=1,
                    pending_decision=pending_reply,
                ).model_dump(),
                "understanding": {},
                "warnings": [*warnings, "TEXT_CONFIRMATION"],
            }
        if (state.get("request") or {}).get("image"):
            # A photo is a visual product search: only price, colour, size
            # and brand from the caption ("giống ảnh này nhưng dưới 500k")
            # narrow it; the model is not needed to decide what to do.
            turn = _image_search_turn(message)
            warnings.append("IMAGE_SEARCH")
        elif turn is not None:
            warnings.append("FAST_PATH")
        else:
            parsed = (
                parse_checkout_turn(message)
                or parse_search_turn(message, active_product_id=active_product_id)
                or parse_policy_turn(message)
            )
            decision = asyncio.ensure_future(
                self.models.decide(
                    message,
                    history,
                    state.get("focused_products", []),
                    active_product_id or None,
                    selected,
                    state.get("shopping_phase", "exploring"),
                    category_paths=await self._category_paths(),
                    conversation_state=self._conversation_state(state),
                )
            )
            try:
                if parsed is None or llm_first:
                    turn = await decision
                else:
                    # A plain search or policy question must not wait on a slow
                    # model: give it a short head start, then act on the parse.
                    hedge = getattr(settings, "decide_hedge", 1.5)
                    done, _pending = await asyncio.wait({decision}, timeout=hedge)
                    if done:
                        turn = decision.result()
                    else:
                        decision.cancel()
                        turn = parsed
                        warnings.append("PARSED_SEARCH")
            except Exception as error:
                log.warning("decide failed: %s: %s", type(error).__name__, str(error)[:300])
                warnings.append("MODEL_UNAVAILABLE")
                turn = (
                    _deterministic_turn(message, history, active_product_id, selected)
                    if llm_first
                    else None
                ) or parsed or (
                    # A product in focus blocks the strict parse (a bare "màu
                    # đen" is a variant pick), but a named product kind is a
                    # new search; with the model down, nothing else reads it.
                    parse_search_turn(message)
                    if active_product_id and mentions_other_product(message)
                    else None
                ) or parse_smalltalk_turn(message) or parse_followup_turn(
                    message, state.get("last_search") or {}
                ) or _deterministic_turn(
                    message, history, active_product_id, selected, short_only=False
                ) or (
                    # The loose parse turns long sentences into nonsense
                    # queries; with the model down, asking again is better.
                    None
                    if llm_first
                    else parse_search_turn(message, active_product_id=active_product_id, strict=False)
                ) or SemanticTurn(
                    tasks=[SemanticTask(intent="clarify")],
                    conversation_action="clarify",
                    focus_update="keep",
                    confidence=0,
                    needs_clarification=True,
                    clarification_question="Mình chưa hiểu chắc yêu cầu. Bạn muốn tìm sản phẩm, hỏi chính sách hay thao tác với đơn hàng?",
                )
        turn = reconcile_turn(turn, message)
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
        clarifies = turn.needs_clarification or turn.tasks[0].intent == "clarify"
        if clarifies and "MODEL_UNAVAILABLE" not in warnings:
            resolved = _clarified_search(turn, state, message)
            if resolved is not None:
                turn = resolved
                primary = turn.tasks[0]
                warnings = [item for item in warnings if item != "LOW_CONFIDENCE"]
                warnings.append("ASSUMED_INTENT")
        clarifies = turn.needs_clarification or turn.tasks[0].intent == "clarify"
        if clarifies and "MODEL_UNAVAILABLE" not in warnings:
            # "thanh toán đơn" with a model question about cart lines it never
            # saw: the order agent reads the real cart and asks from that (or
            # says it is empty), so the model must not answer for it.
            cart_task = next(
                (task for task in turn.tasks if task.intent in _CART_READING_INTENTS), None
            ) or next(iter((parse_checkout_turn(message) or SemanticTurn(
                tasks=[SemanticTask(intent="general")])).tasks), None)
            if cart_task is not None and cart_task.intent in _CART_READING_INTENTS:
                turn = turn.model_copy(update={
                    "tasks": [cart_task],
                    "needs_clarification": False,
                    "clarification_question": "",
                    "conversation_action": "continue",
                    "focus_update": "keep",
                })
                primary = cart_task
                warnings = [item for item in warnings if item != "LOW_CONFIDENCE"]
                warnings.append("CART_DECIDES")

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
        profile = apply_profile_updates(state.get("shopper_profile"), turn.profile_updates)
        if (
            turn.needs_clarification
            and "MODEL_UNAVAILABLE" not in warnings
            and _is_generic_clarification(turn.clarification_question)
        ):
            # The model asked nothing in particular: ask from what the
            # customer already said (who it is for, what they last looked at).
            specific = _contextual_clarification(profile, state.get("last_search") or {})
            if specific:
                turn = turn.model_copy(update={"clarification_question": specific})
        return {
            "semantic_turn": turn.model_dump(),
            "understanding": compatibility.model_dump(),
            "warnings": warnings,
            "shopper_profile": profile,
            "standalone_query": turn.standalone_query,
        }

    @staticmethod
    def _last_recommended(state: AgentState, focused: list[dict]) -> str:
        """The listed product the last reply named first ("A07 có pin trâu
        nhất"), else the first card."""
        reply = _normalized(_last_assistant_message(state.get("history", [])))
        positions = []
        for item in focused:
            name = _normalized(str(item.get("name") or ""))
            short = re.sub(r"^(?:dien thoai|laptop|tai nghe|loa bluetooth|loa|ao|quan)\s+", "", name)
            found = [index for index in (reply.find(name), reply.find(short)) if index >= 0 and len(short) >= 4]
            if found:
                positions.append((min(found), str(item.get("id") or "")))
        if positions:
            return min(positions)[1]
        return str(focused[0].get("id") or "")

    @staticmethod
    def _carry_over(filters: SearchFilters, last: dict) -> SearchFilters:
        """A follow-up for the same kind of product keeps what was said
        before ("tầm 15 triệu", "Android") when the model left it out; a new
        kind of product starts fresh."""
        if not last:
            return filters
        def kind(value) -> str:
            return _normalized(str(value or "")).strip()

        new_kind = kind(filters.product_type)
        old_kind = kind(last.get("product_type"))
        new_path = kind(filters.category_path)
        old_path = kind(last.get("category_path"))
        same_kind = (
            not new_kind
            or not old_kind
            or new_kind in old_kind
            or old_kind in new_kind
        ) and (not new_path or not old_path or new_path.startswith(old_path) or old_path.startswith(new_path))
        if not same_kind or not (old_kind or old_path):
            return filters

        def keep_wishes(merged: SearchFilters) -> SearchFilters:
            # Wishes said earlier ("chống nước", "pin 8 tiếng") stay for the
            # same kind of product; they only rank (soft) so a stale one never
            # empties the result, and a wish restated now wins.
            said_now = {item.key.casefold() for item in merged.spec_constraints}
            for raw in last.get("spec_constraints") or []:
                try:
                    earlier = SemanticConstraint.model_validate(raw)
                except Exception:
                    continue
                if earlier.key.casefold() in said_now:
                    continue
                merged.spec_constraints.append(
                    earlier.model_copy(update={"strength": "soft", "source": "conversation"})
                )
                said_now.add(earlier.key.casefold())
            return merged

        new_brand, old_brand = kind(filters.brand), kind(last.get("brand"))
        if new_brand and old_brand and new_brand != old_brand:
            # "shop có iPhone không" after Samsung at 8 triệu: switching to
            # another brand is a new question, not the old budget. Naming a
            # brand for the first time only narrows the same search.
            merged = filters.model_copy(deep=True)
            if not merged.category_path and last.get("category_path"):
                merged.category_path = last["category_path"]
            if not merged.product_type and last.get("product_type"):
                merged.product_type = last["product_type"]
            return SearchFilters.model_validate(keep_wishes(merged).model_dump())
        merged = filters.model_copy(deep=True)
        if not merged.product_type and last.get("product_type"):
            merged.product_type = last["product_type"]
        if not merged.category_path and last.get("category_path"):
            merged.category_path = last["category_path"]
        if merged.min_price is None and merged.max_price is None:
            merged.min_price = last.get("min_price")
            merged.max_price = last.get("max_price")
        for field in ("brand", "audience"):
            if not getattr(merged, field) and last.get(field):
                setattr(merged, field, last[field])
        for field in ("colors", "sizes"):
            if not getattr(merged, field) and last.get(field):
                setattr(merged, field, list(last[field]))
        return SearchFilters.model_validate(keep_wishes(merged).model_dump())

    @staticmethod
    def _search_criteria(query: str, filters: SearchFilters) -> dict:
        """The criteria a follow-up turn should keep unless the user changes them."""
        criteria = {
            "query": query,
            "product_type": filters.product_type,
            "category_path": filters.category_path,
            "min_price": filters.min_price,
            "max_price": filters.max_price,
            "brand": filters.brand,
            "audience": filters.audience,
            "colors": filters.colors,
            "sizes": filters.sizes,
            "other": [
                f"{item.key} {item.operator} {item.value}{(' ' + item.unit) if item.unit else ''}"
                for item in filters.spec_constraints[:8]
            ],
            # Structured copy for _carry_over; "other" is what the model reads.
            "spec_constraints": [item.model_dump() for item in filters.spec_constraints[:8]],
        }
        return {key: value for key, value in criteria.items() if value not in (None, "", [])}

    @staticmethod
    def _conversation_state(state: AgentState) -> dict:
        """What the model must remember beyond the transcript: the action
        waiting for confirmation, the criteria of the latest search, the
        summary of turns that left the transcript and the shopper profile."""
        context: dict = memory_context(state)
        pending = state.get("pending_action") or {}
        if pending:
            context["pending_confirmation"] = {
                "kind": pending.get("kind"),
                "summary": pending.get("summary"),
            }
        last_search = state.get("last_search") or {}
        if last_search:
            context["last_search_criteria"] = {
                key: value for key, value in last_search.items() if key != "spec_constraints"
            }
        return context

    async def _category_paths(self) -> list[str]:
        """The catalog tree as paths the semantic model may choose from."""
        marketplace = getattr(self, "marketplace", None)
        if marketplace is None or not hasattr(marketplace, "categories"):
            return []
        try:
            return category_path_list(build_catalog_tree(await marketplace.categories()))
        except Exception:
            return []

    @staticmethod
    def _resolve_categories(tree: list[dict], filters: SearchFilters) -> list[str]:
        """Category ids for the branch the model picked (exact path), else the
        branch named by the category phrase or the product kind."""
        if filters.category_path:
            exact = resolve_category_path(tree, filters.category_path)
            if exact:
                # Same-kind siblings from other shops ("Nữ › Áo Thun" of one
                # seller, "Nữ › Áo thun nữ" of another) belong to the branch.
                return sorted({*exact, *resolve_category_ids(tree, filters.category_path)})
        return resolve_category_ids(tree, filters.category_path or filters.product_type or "")

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
    def _detail_task_guard(
        task: SemanticTask, references: list[str], message: str, history: list[dict] | None = None
    ) -> SemanticTask:
        """A question about one product's attributes ("mẫu basic có mấy màu")
        is a detail question, and the previous search's colour/size filters
        the model copied along must not narrow it to the colour searched.

        A bare "có" to "xem thêm thông tin về sản phẩm này?" asks for the
        overview, not the attribute the user asked about just before."""
        if task.intent == "product_search" and len(references) == 1 and task.requested_attributes:
            task = task.model_copy(update={"intent": "product_detail"})
        if task.intent != "product_detail":
            return task
        said = _normalized(message)
        previous_user = next(
            (
                _normalized(str(item.get("content") or ""))
                for item in reversed(history or [])
                if item.get("role") == "user"
            ),
            "",
        )
        asked_before = {
            "color": r"\bmau\b",
            "size": r"\b(?:size|kich thuoc|co nao)\b",
        }
        if (
            re.fullmatch(r"\s*(?:co|ok|oke|okay|u|uh|um|vang|duoc|dong y|yes|xem|xem them|co a|co nhe)\s*[.!]*\s*", said)
            and task.requested_attributes
            and all(
                attribute in asked_before and re.search(asked_before[attribute], previous_user)
                for attribute in task.requested_attributes
            )
        ):
            task = task.model_copy(update={
                "requested_attributes": ["specification"],
                "query": "giới thiệu tổng quan sản phẩm: giá, chất liệu, màu và size có sẵn, điểm nổi bật",
            })
        kept = [
            constraint
            for constraint in task.constraints
            if constraint.key.casefold() not in {"color", "colors", "variant.color", "size", "sizes", "variant.size"}
            or all(
                re.search(rf"(?<!\w){re.escape(_normalized(str(value)))}(?!\w)", said)
                for value in (constraint.value if isinstance(constraint.value, list) else [constraint.value])
            )
        ]
        if len(kept) == len(task.constraints):
            return task
        return task.model_copy(update={"constraints": kept})

    async def _catalog_references(
        self, task: SemanticTask, state: AgentState, resolved: list[str]
    ) -> list[str]:
        """Name references to products not on screen ("so với loa rezo play")
        are looked up in the catalog instead of asking which product."""
        focused_names = [
            _normalized(str(item.get("name") or "")) for item in state.get("focused_products", [])
        ]
        references = list(resolved)
        # Products the assistant named earlier in the chat: "mẫu Samsung lúc
        # nãy" is the one it showed, not the catalog's shortest Samsung name.
        mentioned = " ".join(
            _normalized(str(item.get("content") or ""))
            for item in state.get("history", [])
            if item.get("role") == "assistant"
        )
        for reference in task.references:
            if reference.kind != "name" or len(references) >= 6:
                continue
            name = _normalized(reference.name)
            if not name or any(name in focused for focused in focused_names):
                continue
            product_id = await self._lookup_product_by_name(reference.name, mentioned)
            if product_id and product_id not in references:
                references.append(product_id)
        return references

    async def _lookup_product_by_name(self, name: str, mentioned: str = "") -> str | None:
        """The catalog product whose name contains every word the user said:
        one the assistant already named in this chat first, else the one with
        the fewest extra words ("rezo play" -> "Rezo Play", not "Rezo Play
        Pro 2"); None when no listing carries all the words."""
        wanted = re.findall(r"\w+", _normalized(name))
        if not wanted:
            return None
        try:
            hits = await self.retriever.search(name, SearchFilters(in_stock=False), limit=8)
        except Exception as error:
            log.warning("name lookup failed: %s: %s", type(error).__name__, str(error)[:200])
            return None
        best: tuple[int, str] | None = None
        for hit in hits:
            text = str((hit.get("payload") or {}).get("text") or "")
            title = text.splitlines()[0] if text else ""
            title = title.split(":", 1)[1] if title.startswith("Tên sản phẩm:") else title
            words = re.findall(r"\w+", _normalized(title))
            if not words or not set(wanted) <= set(words):
                continue
            extra = len(set(words) - set(wanted))
            seen = bool(mentioned) and _normalized(title.strip()) in mentioned
            rank = (0 if seen else 1, extra)
            if best is None or rank < best[0]:
                best = (rank, str(hit.get("productId") or ""))
        if best and re.fullmatch(r"[a-fA-F0-9]{24}", best[1]):
            return best[1]
        return None

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
            values = [str(item) for item in value] if isinstance(value, list) else [str(value)]
            if key == "payment_method":
                continue
            if key == "product_type" and isinstance(value, str):
                filters.product_type = value
            elif key == "category_path" and isinstance(value, str):
                filters.category_path = value
            elif key == "audience" and value in {"nam", "nu", "tre_em", "unisex"}:
                filters.audience = value
            elif key == "brand" and isinstance(value, str):
                if not _VAGUE_BRAND.search(_normalized(value)):
                    filters.brand = value
            elif key in {"color", "colors", "variant.color"}:
                for color in values:
                    expanded = _NEUTRAL_COLORS if _NEUTRAL.search(_normalized(color)) else [color]
                    filters.colors = list(dict.fromkeys([*filters.colors, *expanded]))[:8]
            elif key in {"size", "sizes", "variant.size"}:
                sizes = [item for item in values if _SIZE_VALUE.fullmatch(_normalized(item).strip())]
                if sizes:
                    filters.sizes = list(dict.fromkeys([*filters.sizes, *sizes]))[:8]
                else:
                    # "nhỏ gọn" is a wish about the product, not a variant size.
                    filters.spec_constraints.append(constraint.model_copy(update={"strength": "soft"}))
            elif key in {"max_price", "min_price", "price"} and _price_value(value) is None:
                # "rẻ hơn các mẫu vừa xem": a relative wish in a price slot.
                # Not a number, so it cannot filter; it must not fail the turn.
                continue
            elif key in {"max_price", "price"} and constraint.operator in {"lt", "lte"}:
                filters.max_price = _price_value(value)
            elif key in {"min_price", "price"} and constraint.operator in {"gt", "gte"}:
                filters.min_price = _price_value(value)
            elif key == "price" and constraint.operator == "eq":
                # A stated price is a budget, never an exact match.
                filters.min_price = round(_price_value(value) * 0.5)
                filters.max_price = round(_price_value(value) * 1.1)
            elif _UNVERIFIABLE_KEY.search(key):
                # Delivery time, gift wrap, warranty, total for several items:
                # no listing field proves them, so they cannot filter results.
                continue
            else:
                filters.spec_constraints.append(_soften(constraint))
        return SearchFilters.model_validate(filters.model_dump())

    async def _plan_semantic(self, state: AgentState, turn: SemanticTurn) -> dict:
        request = state.get("request", {})
        focused = state.get("focused_products", [])
        skipped_tasks: list[str] = []
        asked_about_list = (
            turn.needs_clarification
            and focused
            and turn.tasks
            and turn.tasks[0].intent in {"product_detail", "compare_products"}
        )
        if asked_about_list:
            # "mẫu nào có màn OLED" right after a list: the list is the subject,
            # so answer from it rather than ask which product.
            turn = turn.model_copy(update={"needs_clarification": False, "clarification_question": ""})
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
        if task.intent in {"product_detail", "compare_products", "cart_add"}:
            references = await self._catalog_references(task, state, references)
        guarded = self._detail_task_guard(
            task, references, state.get("message", ""), state.get("history", [])
        )
        if guarded is not task:
            # Later nodes (attribute answer, web research) read the turn.
            turn = turn.model_copy(
                update={"tasks": [guarded if item is task else item for item in turn.tasks]}
            )
            task = guarded
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

        assumed_product = False
        filters = self._semantic_filters(task)
        if task.intent == "product_search" and not references and turn.focus_update != "clear":
            filters = self._carry_over(filters, state.get("last_search") or {})
        intent = task.intent
        clarification = ""
        if turn.needs_clarification or intent == "clarify":
            intent = "general"
            clarification = turn.clarification_question or "Bạn có thể nói rõ hơn nhu cầu cần hỗ trợ không?"
        elif task.intent == "support_request":
            intent = "general"
        elif task.intent == "out_of_scope":
            intent = "general"
            clarification = (
                "Câu này nằm ngoài phạm vi của mình rồi. Mình là trợ lý mua sắm của shop: có thể giúp bạn tìm "
                "và so sánh sản phẩm, xem giỏ hàng, thanh toán, tra đơn hoặc giải đáp chính sách. Bạn đang cần tìm gì nhé?"
            )
        elif (
            task.web_research
            and task.intent in {"compare_products", "product_detail"}
            and not references
        ):
            # A knowledge question about products not on screen ("Snapdragon
            # 8 Gen 3 hay Dimensity 9300"): answered from web research.
            intent = "general"
        elif task.intent == "compare_products":
            if not references and len(focused) >= 2:
                references = [str(item.get("id") or "") for item in focused[:4] if item.get("id")]
            if len(references) == 1 and focused:
                # "so với Rezo Play thì cái nào rẻ hơn" while a list is on
                # screen: the named product is compared with that list.
                references = list(dict.fromkeys([
                    references[0],
                    *(str(item.get("id") or "") for item in focused[:4]),
                ]))
                references = [item for item in references if re.fullmatch(r"[a-fA-F0-9]{24}", item)]
            if len(references) < 2:
                intent = "general"
                clarification = "Bạn muốn so sánh những sản phẩm nào trong danh sách?"
            else:
                intent = "product_search"
        elif task.intent == "product_detail" and len(references) > 1:
            # "RAM bao nhiêu" about the whole list: answered side by side.
            references = references[:4]
            intent = "product_search"
        elif task.intent == "product_detail" and not references and focused and str(focused[0].get("id") or ""):
            # "có màu đen không" right after a list: answer for the product
            # the assistant just recommended (else the first result) and name it.
            references = [self._last_recommended(state, focused)]
            assumed_product = True
        elif task.intent == "product_detail" and len(references) != 1:
            intent = "general"
            clarification = "Bạn muốn hỏi chi tiết sản phẩm nào?"
        elif task.intent == "cart_add" and not 1 <= len(references) <= 4:
            intent = "general"
            clarification = "Bạn muốn thêm sản phẩm nào vào giỏ?"
        elif task.intent in {"cart_update", "cart_remove"} and len(references) > 1:
            # Without a reference the order agent matches the cart lines.
            intent = "general"
            clarification = "Bạn muốn thay đổi sản phẩm nào trong giỏ hàng?"
        payment_method = next(
            (
                str(item.value)
                for item in task.constraints
                if item.key.casefold() == "payment_method"
                and str(item.value) in {"cod", "bank_transfer"}
            ),
            None,
        )

        query = task.query or resolved_message(state)
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
            order_id=task.order_id,
            payment_method=payment_method,
        )
        if intent == "product_search" and not references and (filters.category_path or filters.product_type):
            try:
                category_tree = build_catalog_tree(await self.marketplace.categories())
                filters.category_ids = self._resolve_categories(category_tree, filters)
                plan.filters = filters
            except Exception:
                pass
        # "áo thun đen XL và 1 cái tất": every other product search of the
        # turn runs beside the main route (search_side) instead of being
        # dropped because the turn already searched once.
        extra_searches: list[dict] = []
        if not turn.needs_clarification and intent not in {"clarify", "out_of_scope"}:
            extra_tasks = [
                item for item in turn.tasks
                if item is not task and item.intent == "product_search" and item.query.strip()
            ][:2]
            category_tree = None
            for extra in extra_tasks:
                extra_filters = self._semantic_filters(extra)
                if extra_filters.category_path or extra_filters.product_type:
                    try:
                        if category_tree is None:
                            category_tree = build_catalog_tree(await self.marketplace.categories())
                        extra_filters.category_ids = self._resolve_categories(category_tree, extra_filters)
                    except Exception:
                        pass
                extra_searches.append({"query": extra.query.strip(), "filters": extra_filters.model_dump()})
            if extra_searches:
                label = _INTENT_LABELS["product_search"]
                handled = len(extra_searches)
                kept = []
                for item in skipped_tasks:
                    if item == label and handled:
                        handled -= 1
                        continue
                    kept.append(item)
                skipped_tasks = kept
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
            "warnings": [*state.get("warnings", []), *(["ASSUMED_FIRST_PRODUCT"] if assumed_product else [])],
            "route": task.intent if task.intent in {"clarify", "out_of_scope"} else intent,
            "skipped_tasks": skipped_tasks,
            "extra_searches": extra_searches,
            "semantic_turn": turn.model_dump(),
            **(
                {"last_search": self._search_criteria(query, filters)}
                if intent == "product_search" and not references
                else {}
            ),
            "committed": False,
        }

    async def plan(self, state: AgentState) -> dict:
        request = state.get("request", {})
        if request.get("confirmActionId") or request.get("cancelActionId"):
            return {"route": "resolve_pending", "committed": False}
        ui_intent = _ui_selection_intent(request)
        if ui_intent:
            product_id = request.get("referenceProductId") if ui_intent == "cart_add" else None
            plan = AgentPlan(
                intent=ui_intent,
                query=state.get("message", ""),
                product_id=product_id,
                product_ids=[product_id] if product_id else [],
                quantity=request.get("quantity") or 1,
                payment_method=request.get("paymentMethod"),
            )
            return {
                "plan": plan.model_dump(),
                "query": plan.query,
                "products": [],
                "render_product_cards": False,
                "active_product_id": product_id or state.get("active_product_id"),
                "tool_result": {},
                "route": ui_intent,
                "skipped_tasks": [],
                "committed": False,
            }
        pending = state.get("pending_action") or {}
        decision =(state.get("semantic_turn") or {}).get("pending_decision", "none")
        if (
            decision in {"confirm", "cancel"}
            and "TEXT_CONFIRMATION" not in state.get("warnings", [])
            and not _explicit_pending_answer(state.get("message", ""), decision)
        ):
            # The model read "có thể, nhưng..." as a yes: a cart change or an
            # order needs words that clearly answer the confirmation.
            decision = "none"
        if pending.get("id") and decision in {"confirm", "cancel"}:
            # A typed answer to the waiting action is the same as its button;
            # a policy question in the same message still runs alongside.
            key = "confirmActionId" if decision == "confirm" else "cancelActionId"
            return {
                "route": "resolve_pending",
                "committed": False,
                "request": {**request, key: pending["id"]},
            }
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
        updates["query"] = updates.get("query") or resolved_message(state)
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
                updates["query"] = search_context.semantic_query or resolved_message(state)
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
                filters.category_ids = self._resolve_categories(category_tree, filters)
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

    def _advised(self, state: AgentState, main: str) -> bool:
        """Hybrid mode: advice turns go to the tool-calling advisor. A plain
        detail question ("còn size M không") stays on the graph, which reads
        variants and size charts exactly; one with another part goes too."""
        advisor = getattr(self, "advisor", None)
        if advisor is None or not advisor.enabled():
            return False
        if (state.get("request") or {}).get("image"):
            return False
        if main == "product_search":
            return True
        return main == "product_detail" and bool(state.get("skipped_tasks"))

    def route_after_plan(self, state: AgentState) -> list[str]:
        main = self._main_route(state)
        if self._advised(state, main):
            main = "advisor"
        return [main, "policy_side", "research_side", "search_side"]

    def route_after_advisor(self, state: AgentState) -> str:
        if state.get("advisor_answer"):
            return "collect"
        main = self._main_route(state)
        return "product_detail" if main == "product_detail" else "retrieve"

    async def run_advisor(self, state: AgentState) -> dict:
        try:
            result = await self.advisor.run(state)
        except Exception as error:
            log.warning("advisor failed, using the graph: %s: %s", type(error).__name__, str(error)[:200])
            result = None
        if not result:
            return {"advisor_failed": True, "warnings": [*state.get("warnings", []), "ADVISOR_FALLBACK"]}
        products = result["products"]
        return {
            "route": "product_search",
            "advisor_answer": result["answer"],
            "products": products,
            "render_product_cards": bool(products),
            "active_product_id": str(products[0]["id"]) if len(products) == 1 else state.get("active_product_id"),
            "tool_result": {"advisor": {"calls": result["calls"]}, "found": len(products)},
            "skipped_tasks": [],
            "warnings": [*state.get("warnings", []), "ADVISOR"],
            **({"last_search": result["last_search"]} if result["last_search"] else {}),
        }

    async def collect(self, _state: AgentState) -> dict:
        """Join point of the main route before the policy barrier."""
        return {}

    async def _category_suggestions(self, limit: int = 5) -> list[str]:
        try:
            tree = build_catalog_tree(await self.marketplace.categories())
        except Exception:
            return []
        counter = getattr(self.retriever, "category_product_counts", None)
        counts = await counter() if counter else {}
        if counts:
            # Busiest branches first: suggestions should lead somewhere.
            tree = sorted(
                tree,
                key=lambda node: sum(counts.get(str(item), 0) for item in node.get("categoryIds", [])),
                reverse=True,
            )
        return [str(node.get("name")) for node in tree if node.get("name")][:limit]

    async def search_side(self, state: AgentState) -> dict:
        """The other product searches of one message ("và 1 cái tất"), run
        next to the main route: a plain catalog search, top few each."""
        extras = state.get("extra_searches") or []
        if not extras or state.get("route") == "resolve_pending":
            return {}
        limit = int(getattr(self.settings, "retrieval_limit", 20) or 20)

        async def run(extra: dict) -> dict:
            filters = SearchFilters.model_validate(extra.get("filters") or {})
            try:
                hits = await self.retriever.search(extra["query"], filters, limit=limit)
                products = await self.marketplace.hydrate_products(hits, filters, _EXTRA_SEARCH_RESULTS)
            except Exception as error:
                log.warning("extra search failed: %s: %s", type(error).__name__, str(error)[:200])
                products = []
            return {"query": extra["query"], "products": list(products)[:_EXTRA_SEARCH_RESULTS]}

        return {"extra_results": list(await asyncio.gather(*(run(item) for item in extras[:2])))}

    async def clarify_guard(self, state: AgentState) -> dict:
        """Escalate repeated clarifications instead of asking the same thing again.

        1st: one question with quick replies. 2nd (or the same message again):
        offer structured choices. 3rd and later: offer a human handoff.
        """
        plan = state.get("plan", {})
        clarification = str(plan.get("clarification") or "")
        message_key = _normalized(state.get("message", "")).strip()[:200]
        previous_count = int(state.get("clarify_count") or 0)
        repeated = bool(message_key) and message_key == state.get("last_clarify_key")
        if "MODEL_UNAVAILABLE" in state.get("warnings", []):
            # Our own outage is not the customer being unclear: ask once,
            # plainly, and do not move them towards a human handoff for it.
            # The key stays the previous one: the customer was asked to send
            # this message again, and doing so must not count as repeating.
            return {
                "route": "clarify",
                "render_product_cards": False,
                "tool_result": {
                    "clarification": "Xin lỗi, mình xử lý câu vừa rồi hơi chậm. "
                    "Bạn gửi lại giúp mình, hoặc nói ngắn gọn sản phẩm và ngân sách bạn cần nhé."
                },
                "suggestions": await self._category_suggestions(4),
                "handoff": False,
                "clarify_count": previous_count,
                "last_clarify_key": state.get("last_clarify_key", ""),
            }
        # Each new, different message is a fresh attempt: escalate only when
        # the customer repeats themselves or the model keeps asking.
        count = previous_count + 1
        if repeated:
            count = max(count, 3)
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
        if count >= 4:
            text = (
                (clarification + " ") if clarification else ""
            ) + "Nếu tiện, bạn có thể chat trực tiếp với nhân viên shop để được hỗ trợ nhanh hơn."
            suggestions = product_choices or await self._category_suggestions(3)
            handoff = True
        elif count == 3:
            text = (
                (clarification + " ") if clarification else ""
            ) + "Bạn cũng có thể chọn nhanh một mục bên dưới, hoặc nói theo kiểu “loại sản phẩm + ngân sách” (ví dụ: “tai nghe dưới 1 triệu”)."
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
        raw = state.get("semantic_turn")
        support = next(
            (task for task in SemanticTurn.model_validate(raw).tasks if task.intent == "support_request"),
            None,
        ) if raw else None
        if support:
            # Say plainly what the assistant cannot do, and hand over to staff.
            return {
                "route": "general",
                "render_product_cards": False,
                "handoff": True,
                "tool_result": {
                    "supportRequest": support.query or state.get("message", ""),
                    "assistantCannot": "tạo yêu cầu hỗ trợ, hủy hoặc sửa đơn, đổi địa chỉ giao, giục đơn vị vận chuyển",
                    "assistantCan": "tra trạng thái đơn theo mã đơn của tài khoản, giải thích chính sách hủy/đổi trả, chuyển sang nhân viên shop",
                },
            }
        if raw and any(task.web_research for task in SemanticTurn.model_validate(raw).tasks):
            # A product-knowledge question: the product agent's web research
            # (side branch) supplies the facts for the answer.
            return {"route": "general", "render_product_cards": False, "tool_result": {"question": state.get("message", "")}}
        return {
            "route": "general",
            "tool_result": {
                "capabilities": [
                    "tư vấn, tìm và so sánh sản phẩm (product agent)",
                    "tra cứu chính sách và thông tin sản phẩm trên web",
                    "xem hoặc cập nhật giỏ hàng có xác nhận (order agent)",
                    "thanh toán và theo dõi đơn hàng (order agent)",
                ]
            },
        }

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
            if result.get("handoffMessage"):
                return result["handoffMessage"]
            if result.get("cartSummary"):
                return result["cartSummary"]
            if "cart" in result:
                count = len(result.get("cart", {}).get("products", []))
                return f"Giỏ hàng hiện có {count} dòng sản phẩm."
            if result.get("found") == 0:
                kind = str((state.get("plan", {}).get("filters") or {}).get("product_type") or "sản phẩm")
                return (
                    f"Hiện shop chưa có {kind} còn hàng khớp đủ các tiêu chí này. "
                    "Bạn thử bỏ bớt một tiêu chí, ví dụ tầm giá hoặc màu, để mình tìm lại nhé."
                )
        products = state.get("products", [])
        if products:
            return f"Mình tìm thấy {len(products)} sản phẩm phù hợp và còn hàng."
        return "Mình có thể giúp tìm sản phẩm, quản lý giỏ hàng, xem đơn và checkout có xác nhận."

    async def _named_but_hidden(
        self, state: AgentState, answer: str, shown: list[dict], rendered: bool
    ) -> list[dict]:
        """Cards of the products the reply names that the turn does not show:
        shown earlier in the session, or found but hidden on this turn."""
        loaded = {str(item["id"]): item for item in shown if item.get("id")}
        known = {
            str(item["id"]): item
            for item in [*state.get("recent_products", []), *state.get("focused_products", []), *shown]
            if item.get("id")
        }
        named = [
            item for item in named_products(answer, known.values())
            if not (rendered and item in loaded)
        ][:MAX_NAMED_CARDS]
        cards = await asyncio.gather(
            *(self.marketplace.product_card(item) for item in named if item not in loaded),
            return_exceptions=True,
        )
        for card in cards:
            if isinstance(card, dict) and card.get("id"):
                loaded[str(card["id"])] = card
        return [loaded[item] for item in named if item in loaded]

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
        if state.get("extra_results") and not state.get("advisor_answer"):
            # The other searches of the message share the list (see below).
            products = products[:_MAIN_RESULTS_WITH_EXTRAS]
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
        web = state.get("web_research") or {}
        web_summary = str(web.get("summary") or "").strip()
        if web_summary and isinstance(model_result, dict):
            model_result["webResearch"] = {
                "summary": web_summary,
                "sources": [item.get("title") for item in web.get("sources") or []],
            }
            sources = sources + [
                {
                    "number": len(sources) + index,
                    "title": str(item.get("title") or item.get("url") or "")[:500],
                    "url": str(item.get("url") or ""),
                }
                for index, item in enumerate(web.get("sources") or [], 1)
            ]
        should_be_deterministic = isinstance(result, dict) and any(
            key in result
            for key in (
                "error", "clarification", "confirmationRequired", "cancelled", "success", "policyAnswer",
                "cartSummary", "handoffMessage",
            )
        )
        # LLM-first: product answers are written by the model from catalog
        # facts (and web research); attribute facts and the search template
        # are what it is given and what is shown if it fails. Transactional
        # results stay deterministic.
        model_answers = bool(
            getattr(self.settings, "llm_first", False)
            and state.get("semantic_turn")
            and "MODEL_UNAVAILABLE" not in state.get("warnings", [])
        ) or bool(web_summary)
        if attribute_answer and isinstance(model_result, dict):
            model_result["verifiedFacts"] = attribute_answer
        comparison = _spec_comparison(state)
        if comparison and isinstance(model_result, dict):
            model_result["specComparison"] = comparison
        if "ASSUMED_FIRST_PRODUCT" in state.get("warnings", []) and isinstance(model_result, dict):
            model_result["assumedFirstProduct"] = True
        if state.get("advisor_answer"):
            # The advisor looked up and answered the whole message itself.
            answer = str(state["advisor_answer"])
        elif attribute_answer and not model_answers:
            answer = attribute_answer
        elif should_be_deterministic:
            answer = direct
        elif template_answer and not model_answers:
            answer = template_answer
        else:
            try:
                memory = memory_note(state)
                answer = await self.models.answer(
                    state.get("message", ""),
                    state.get("plan", {}),
                    model_result,
                    products,
                    state.get("history", []),
                    # Only when there is memory: test doubles keep the old signature.
                    **({"memory": memory} if memory else {}),
                )
            except Exception as error:
                log.warning("answer failed, using template: %s: %s", type(error).__name__, str(error)[:200])
                answer = attribute_answer or (template_answer if not relaxed else "") or direct
                if products and relaxed and not attribute_answer:
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
        answer = _drop_unbacked_action_claims(answer, state.get("tool_result") or {})
        # A second task is covered only by a route that does the same work: a
        # list answers another search, a side-by-side answers a comparison,
        # and either answers a detail question. A single product's detail does
        # not answer "gợi ý mẫu nào nên mua".
        compared = len(plan.get("product_ids") or []) >= 2
        covered_by = {
            "tìm sản phẩm": state.get("route") == "product_search",
            "so sánh sản phẩm": state.get("route") == "product_search" and compared,
            "hỏi chi tiết sản phẩm": state.get("route") in {"product_search", "product_detail"},
        }
        skipped = [
            label
            for label in state.get("skipped_tasks") or []
            if not covered_by.get(label, False)
        ]
        if skipped:
            answer += (
                "\n\nCòn phần " + ", ".join(skipped)
                + ", bạn nhắn tiếp ngay sau đây là mình làm luôn nhé."
            )
        shown = list(state.get("products", []))
        extra_update: dict = {}
        extra_results = [] if state.get("advisor_answer") else list(state.get("extra_results") or [])
        if extra_results:
            # Each part of "áo thun XL và 1 cái tất" gets its own short list.
            shown = shown[:_MAIN_RESULTS_WITH_EXTRAS] if state.get("render_product_cards", True) else []
            seen = {str(item.get("id")) for item in shown}
            for extra in extra_results:
                found = [item for item in extra["products"] if str(item.get("id")) not in seen]
                seen.update(str(item.get("id")) for item in found)
                shown.extend(found)
                if found:
                    listed = "; ".join(
                        f"{item.get('name', 'Sản phẩm')} ({_price_text(item.get('price'))})" for item in found
                    )
                    answer += f"\n\nVới “{extra['query']}”, mình tìm thấy: {listed}."
                else:
                    answer += f"\n\nMình chưa tìm thấy “{extra['query']}” còn hàng phù hợp."
            extra_update = {"products": shown, "render_product_cards": bool(shown)}
        if state.get("route") in {"product_search", "product_detail", "general"}:
            rendered = extra_update.get("render_product_cards", state.get("render_product_cards", True))
            missing = await self._named_but_hidden(state, answer, shown, rendered)
            if missing:
                extra_update = {
                    "products": [*shown, *missing] if rendered else missing,
                    "render_product_cards": True,
                }
                shown_ids = {str(item.get("id")) for item in shown}
                shown.extend(item for item in missing if str(item.get("id")) not in shown_ids)
        if policy_appendix:
            answer = f"{answer}\n\n{policy_appendix}" if answer else policy_appendix
        clarifying = state.get("route") in {"clarify", "out_of_scope"}
        new_focused = [
            {"id": item.get("id"), "name": item.get("name", "")}
            for item in shown
            if item.get("id")
        ][:10 if extra_results else 6]
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
        recent = {str(item["id"]): item for item in state.get("recent_products", []) if item.get("id")}
        for item in shown:
            if item.get("id"):
                product_id = str(item["id"])
                recent.pop(product_id, None)
                recent[product_id] = {"id": product_id, "name": item.get("name", "")}
        return {
            **extra_update,
            "answer": answer,
            "focused_products": focused,
            "recent_products": list(recent.values())[-_MAX_RECENT_PRODUCTS:],
            "sources": sources,
            "suggestions": suggestions[:8],
            "handoff": bool(state.get("handoff")) and (clarifying or "supportRequest" in (state.get("tool_result") or {})),
            "clarify_count": int(state.get("clarify_count") or 0) if clarifying else 0,
            "last_clarify_key": state.get("last_clarify_key", "") if clarifying else "",
            "route": "multi" if multi_route else state.get("route", "general"),
            "committed": True,
        }
