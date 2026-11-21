"""Order agent: cart, checkout and order tracking.

The supervisor hands every transactional intent (cart_view, cart_add,
cart_update, cart_remove, checkout, order_status and the confirmation of a
pending action) to this agent. Its model resolves what the customer means
against the real cart lines and product variants ("bỏ cái tai nghe", "lấy màu
đen size L", "thêm 1 cái nữa"); deterministic matching is only the fallback
when the model is unavailable. Nothing is written without an explicit
confirmation: every mutation becomes a PendingAction first.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time

from ..conversation import (
    _normalized,
    _price_text,
    _variant_dimensions,
    _variant_selection,
)
from ..schemas import AgentPlan, AgentState, OrderDecision, PendingAction, SearchFilters

log = logging.getLogger(__name__)

ORDER_NODES = ("cart_view", "prepare_cart", "prepare_checkout", "order_status", "resolve_pending")
_RULE_WARNINGS = {"MODEL_UNAVAILABLE", "FAST_PATH", "PARSED_SEARCH"}
# Matched on _normalized text (no diacritics, đ -> d).
_WHOLE_CART = re.compile(r"\b(?:ca gio|toan bo|tat ca|het gio|thanh toan het|ca hai|ca ba|moi thu)\b")
# Words of a checkout request that never name a product.
_CHECKOUT_STOP_WORDS = {
    "chi", "thanh", "toan", "don", "hang", "dat", "mua", "cho", "minh", "toi", "em", "anh", "chi",
    "rieng", "luon", "nhe", "nha", "di", "voi", "cai", "con", "gio", "san", "pham", "nay", "do",
    "thoi", "ma", "la", "va", "the", "giup", "ban", "oi", "checkout", "lay", "muon", "can", "ok", "oke",
}


def _model_decided(state: AgentState) -> bool:
    """True when the semantic model, not a parser, decided this turn."""
    return bool(state.get("semantic_turn")) and not (_RULE_WARNINGS & set(state.get("warnings") or []))


def _variant_id(variant: dict) -> str:
    return str(variant.get("id") or variant.get("_id") or "")


def _line_id(item: dict) -> str:
    """Same cart line id as the storefront: "<productId>::<variantId>"."""
    return f"{item['productId']}::{item.get('variantId') or ''}"


def _in_stock(variant: dict) -> bool:
    return float(variant.get("availableStock") or 0) > 0


class OrderAgent:
    def __init__(self, settings, models_gateway, marketplace):
        self.settings = settings
        self.models = models_gateway
        self.marketplace = marketplace

    def register(self, builder, join: str) -> None:
        for node in ORDER_NODES:
            builder.add_node(node, getattr(self, node))
            builder.add_edge(node, join)

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _auth_error(state: AgentState) -> dict | None:
        if not state.get("user_id") or state.get("role") not in {"buyer", "admin"}:
            return {
                "tool_result": {
                    "error": "Bạn cần đăng nhập bằng tài khoản người mua để thực hiện thao tác này."
                }
            }
        return None

    def _llm_available(self) -> bool:
        return bool(getattr(self.settings, "llm_first", False)) and hasattr(self.models, "resolve_order")

    async def _resolve(self, state: AgentState, context: dict) -> OrderDecision | None:
        """Ask the order model; None when it is off, failing or out of budget."""
        if not self._llm_available():
            return None
        try:
            return await self.models.resolve_order({
                "user_message": state.get("message", ""),
                "recent_history": [
                    {"role": item.get("role"), "content": str(item.get("content") or "")[:300]}
                    for item in (state.get("history") or [])[-4:]
                ],
                "selected_options": state.get("selected_options", {}),
                **context,
            })
        except Exception as error:
            log.warning("order model failed: %s: %s", type(error).__name__, str(error)[:200])
            return None

    async def _cart_lines(self, cart: dict) -> list[dict]:
        """Cart lines with product and variant names, so the model and the
        confirmation summary can name what is being changed."""
        lines = [
            item for item in (cart or {}).get("products", [])
            if item.get("productId") and int(item.get("quantity") or 0) > 0
        ][:20]
        lookup = getattr(self.marketplace, "product", None)
        details = await asyncio.gather(
            *(lookup(str(item["productId"])) for item in lines),
            return_exceptions=True,
        ) if lookup else [None] * len(lines)
        resolved = []
        for index, (item, product) in enumerate(zip(lines, details), 1):
            product = product if isinstance(product, dict) else {}
            variant = next(
                (
                    entry for entry in product.get("variants", [])
                    if _variant_id(entry) == str(item.get("variantId") or "")
                ),
                None,
            )
            resolved.append({
                "index": index,
                "productId": str(item["productId"]),
                "variantId": item.get("variantId"),
                "quantity": int(item.get("quantity") or 1),
                "name": str(product.get("name") or "Sản phẩm"),
                "variant": str((variant or {}).get("name") or ""),
            })
        return resolved

    async def _cart_summary(self, cart: dict) -> str:
        """Name, quantity and price of every line, so the answer is useful
        without another model call."""
        lines = [item for item in (cart or {}).get("products", []) if item.get("productId")]
        if not lines:
            return "Giỏ hàng của bạn đang trống."
        details = await asyncio.gather(
            *(self.marketplace.product(str(item["productId"])) for item in lines[:10]),
            return_exceptions=True,
        )
        rows, total = [], 0.0
        for item, product in zip(lines, details):
            if not isinstance(product, dict):
                continue
            variant = next(
                (v for v in product.get("variants", []) if str(v.get("_id") or v.get("id")) == str(item.get("variantId"))),
                None,
            )
            price = float((variant or {}).get("price") or product.get("price") or 0)
            quantity = int(item.get("quantity") or 1)
            total += price * quantity
            label = product.get("name", "Sản phẩm") + (f" ({variant['name']})" if variant and variant.get("name") else "")
            rows.append(f"{label} × {quantity} – {_price_text(price * quantity)}")
        if not rows:
            return f"Giỏ hàng của bạn có {len(lines)} sản phẩm."
        more = f" (và {len(lines) - len(rows)} sản phẩm khác)" if len(lines) > len(rows) else ""
        return (
            f"Giỏ hàng của bạn có {len(lines)} sản phẩm{more}:\n• "
            + "\n• ".join(rows)
            + f"\nTạm tính: {_price_text(total)}."
        )

    @staticmethod
    def _rule_variant(state: AgentState, card: dict) -> str | None:
        """Fallback: the single in-stock variant matching the colour/size the
        customer named now or picked earlier."""
        matches = OrderAgent._rule_variants(state, card)
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _rule_variants(state: AgentState, card: dict) -> list[str]:
        """Every variant matching the colours/sizes the customer named now or
        picked earlier ("size L và XL" matches two)."""
        variants = card.get("variants", [])
        mentioned = _variant_selection(state.get("message", ""), variants, card.get("name", ""))
        selected = state.get("selected_options", {}) or {}
        colors = {_normalized(value) for value in (mentioned["colors"] or selected.get("colors") or [])}
        sizes = {_normalized(value) for value in (mentioned["sizes"] or selected.get("sizes") or [])}
        if not colors and not sizes:
            return []
        records = _variant_dimensions(variants, card.get("name", ""))["records"]
        return [
            _variant_id(record["variant"]) for record in records
            if (not colors or record["color"] in colors)
            and (not sizes or record["sizes"] & sizes)
        ]

    @staticmethod
    def _variant_picker(card: dict, checked=(), quantity: int = 1) -> dict:
        """Checkbox list of a product's variants: the customer may tick several
        (size L and XL of one shirt) and add them in one confirmation."""
        checked = {str(item) for item in checked if item}
        return {
            "type": "variant_select",
            "multiple": True,
            "productId": str(card.get("id") or ""),
            "productName": str(card.get("name") or ""),
            "quantity": quantity,
            "submitLabel": "Thêm vào giỏ",
            "options": [
                {
                    "id": _variant_id(variant),
                    "label": str(variant.get("name") or card.get("name") or "Phiên bản"),
                    "price": float(variant.get("price") or card.get("price") or 0),
                    "disabled": not _in_stock(variant),
                    "checked": _variant_id(variant) in checked and _in_stock(variant),
                }
                for variant in card.get("variants", [])[:30]
                if _variant_id(variant)
            ],
        }

    def _pending_variants(self, card: dict, variant_ids: list, quantity: int) -> dict:
        """One confirmation for one or several variants of a product."""
        names = {
            _variant_id(variant): str(variant.get("name") or "")
            for variant in card.get("variants", [])
        }
        product_id = str(card.get("id"))
        if len(variant_ids) == 1:
            variant_name = names.get(str(variant_ids[0] or ""), "")
            label = card["name"] + (f" ({variant_name})" if variant_name and variant_name != card["name"] else "")
            return self._pending(
                "cart_add",
                f"Thêm {label} — số lượng {quantity}",
                {"productId": product_id, "variantId": variant_ids[0], "quantity": quantity},
            )
        labels = ", ".join(names.get(item) or "phiên bản" for item in variant_ids)
        return self._pending(
            "cart_add",
            f"Thêm {card['name']} ({labels}) — mỗi phiên bản số lượng {quantity}",
            {"items": [
                {"productId": product_id, "variantId": item, "quantity": quantity}
                for item in variant_ids
            ]},
        )

    def _pending(self, kind: str, summary: str, payload: dict) -> dict:
        action = PendingAction(
            id=f"act_{secrets.token_urlsafe(18)}",
            kind=kind,
            summary=summary,
            payload=payload,
            expires_at=time.time() + self.settings.action_ttl,
        )
        return {
            "route": kind,
            "pending_action": action.model_dump(),
            "tool_result": {
                "confirmationRequired": True,
                "summary": summary,
                "actionId": action.id,
            },
        }

    # -- nodes -----------------------------------------------------------

    async def cart_view(self, state: AgentState) -> dict:
        denied = self._auth_error(state)
        if denied:
            return denied
        cart = await self.marketplace.cart(state["user_id"])
        return {"route": "cart_view", "tool_result": {"cart": cart, "cartSummary": await self._cart_summary(cart)}}

    async def prepare_cart(self, state: AgentState) -> dict:
        denied = self._auth_error(state)
        if denied:
            return denied
        plan = AgentPlan.model_validate(state["plan"])
        if plan.intent == "cart_add":
            return await self._prepare_add(state, plan)
        return await self._prepare_line_change(state, plan)

    async def _prepare_add(self, state: AgentState, plan: AgentPlan) -> dict:
        product_ids = [item for item in plan.product_ids if item][:4]
        if len(product_ids) >= 2:
            return await self._prepare_add_many(state, plan, product_ids)
        return await self._prepare_add_one(state, plan)

    async def _prepare_add_many(self, state: AgentState, plan: AgentPlan, product_ids: list[str]) -> dict:
        """"Thêm mỗi loại một chai": every product is resolved to one variant
        and the whole set is confirmed once; a product that still needs a
        colour/size choice is asked about first."""
        lines = []
        for product_id in product_ids:
            single = plan.model_copy(update={"product_id": product_id, "product_ids": [product_id], "variant_id": None})
            prepared = await self._prepare_add_one(state, single)
            pending = prepared.get("pending_action")
            if not pending:
                return prepared
            label = pending["summary"].removeprefix("Thêm ")
            payload = pending["payload"]
            for item in payload.get("items") or [payload]:
                lines.append({**item, "label": label})
                label = ""
        summary = "Thêm " + "; ".join(line["label"] for line in lines if line["label"])
        return self._pending(
            "cart_add",
            summary,
            {"items": [{key: line[key] for key in ("productId", "variantId", "quantity")} for line in lines]},
        )

    async def _prepare_add_one(self, state: AgentState, plan: AgentPlan) -> dict:
        if not plan.product_id:
            return {"tool_result": {"clarification": "Bạn hãy chọn rõ sản phẩm cần thêm vào giỏ hàng."}}
        card = await self.marketplace.product_card(plan.product_id, plan.filters)
        if not card and (plan.filters.colors or plan.filters.sizes):
            # The product exists but not in the colour/size asked for: say so
            # and list what there is, instead of "no longer sold".
            available = await self.marketplace.product_card(plan.product_id, SearchFilters())
            if available:
                wanted = ", ".join([*plan.filters.colors, *plan.filters.sizes])
                names = [
                    variant.get("name")
                    for variant in available.get("variants", [])
                    if variant.get("id") and variant.get("name") and variant.get("name") != available.get("name")
                ]
                if not names:
                    return {
                        "route": "cart_add",
                        "products": [available],
                        "tool_result": {
                            "clarification": f"{available.get('name', 'Sản phẩm')} chỉ có một phiên bản và tin đăng không ghi "
                            f"màu/size, nên mình chưa chắc có bản {wanted}. Bạn vẫn muốn thêm bản đang bán vào giỏ không?",
                        },
                    }
                return {
                    "route": "cart_add",
                    "products": [available],
                    "tool_result": {
                        "clarification": f"{available.get('name', 'Sản phẩm')} không có phiên bản {wanted} còn hàng. "
                        f"Các phiên bản hiện có: {', '.join(names[:8])}. "
                        "Bạn tick một hoặc nhiều phiên bản bên dưới nhé.",
                        "selection": self._variant_picker(available, quantity=plan.quantity),
                    },
                }
        if not card:
            return {"tool_result": {"error": "Sản phẩm không còn bán hoặc đã hết hàng."}}
        variants = card.get("variants", [])
        quantity = plan.quantity
        picked = (state.get("request") or {}).get("variantIds")
        if picked:
            # Ticked in the widget's checkbox list: only real, in-stock
            # variants of this product are taken.
            known = {_variant_id(variant): variant for variant in variants}
            chosen = [item for item in dict.fromkeys(picked) if item in known and _in_stock(known[item])]
            if not chosen:
                return {
                    "route": "cart_add",
                    "products": [card],
                    "tool_result": {
                        "clarification": "Các phiên bản bạn chọn đã hết hàng. Bạn chọn lại giúp mình nhé.",
                        "selection": self._variant_picker(card, quantity=quantity),
                    },
                }
            return self._pending_variants(card, chosen, quantity)
        variant_ids = [plan.variant_id] if plan.variant_id else []
        if not variant_ids and len(variants) == 1:
            variant_ids = [variants[0].get("id")]
        clarification = ""
        suggested: list[str] = []
        if not variant_ids and len(variants) > 1:
            decision = await self._resolve(state, {
                "requested_action": "add",
                "requested_quantity": plan.quantity,
                "product": {
                    "name": card.get("name", ""),
                    "variants": [
                        {
                            "index": index,
                            "name": variant.get("name", ""),
                            "price": variant.get("price"),
                            "inStock": _in_stock(variant),
                        }
                        for index, variant in enumerate(variants[:50], 1)
                    ],
                },
            })
            if decision and decision.action == "add":
                indices = list(dict.fromkeys(
                    index for index in [*decision.variant_indices, decision.variant_index]
                    if index and index <= len(variants)
                ))
                variant_ids = [
                    _variant_id(variants[index - 1]) for index in indices
                    if _variant_id(variants[index - 1]) and _in_stock(variants[index - 1])
                ]
                quantity = decision.quantity or quantity
            elif decision is None:
                suggested = self._rule_variants(state, card)
                if len(suggested) == 1:
                    variant_ids = suggested
            else:
                clarification = decision.clarification
        if not variant_ids and len(variants) > 1:
            return {
                "route": "cart_add",
                "products": [card],
                "tool_result": {
                    "clarification": clarification
                    or "Sản phẩm có nhiều phiên bản. Bạn tick một hoặc nhiều màu/size bên dưới "
                    "rồi bấm Thêm vào giỏ nhé.",
                    "variants": variants[:12],
                    "selection": self._variant_picker(card, suggested, quantity),
                },
            }
        return self._pending_variants(card, variant_ids or [None], quantity)

    async def _prepare_line_change(self, state: AgentState, plan: AgentPlan) -> dict:
        cart = await self.marketplace.cart(state["user_id"])
        lines = await self._cart_lines(cart)
        if not lines:
            return {"route": plan.intent, "tool_result": {"error": "Giỏ hàng đang trống."}}
        requested = "remove" if plan.intent == "cart_remove" else "update"
        candidates = [
            line for line in lines
            if line["productId"] == plan.product_id
            and (not plan.variant_id or str(line["variantId"] or "") == plan.variant_id)
        ]
        target = candidates[0] if len(candidates) == 1 else None
        quantity = plan.quantity
        # A removal of one identified line is unambiguous; anything else (an
        # unnamed or repeated product, a relative quantity) is the model's call.
        if not (target and requested == "remove"):
            decision = await self._resolve(state, {
                "requested_action": requested,
                "requested_quantity": plan.quantity,
                "referenced_product_line": target["index"] if target else None,
                "cart_lines": [
                    {key: line[key] for key in ("index", "name", "variant", "quantity")}
                    for line in lines
                ],
            })
            if decision and decision.action == requested and decision.line_index and decision.line_index <= len(lines):
                target = lines[decision.line_index - 1]
                quantity = decision.quantity or quantity
            elif decision is not None:
                target = None
                if decision.clarification:
                    return {
                        "route": plan.intent,
                        "suggestions": [line["name"] for line in lines[:6]],
                        "tool_result": {"clarification": decision.clarification},
                    }
        if not target:
            return {
                "route": plan.intent,
                "suggestions": [line["name"] for line in lines[:6]],
                "tool_result": {"clarification": "Bạn muốn thay đổi sản phẩm nào trong giỏ hàng?"},
            }
        label = target["name"] + (f" ({target['variant']})" if target["variant"] else "")
        summary = f"Xóa {label}" if requested == "remove" else f"Đặt số lượng {label} — số lượng {quantity}"
        return self._pending(
            plan.intent,
            summary,
            {"productId": target["productId"], "variantId": target["variantId"], "quantity": quantity},
        )

    async def prepare_checkout(self, state: AgentState) -> dict:
        denied = self._auth_error(state)
        if denied:
            return denied
        request = state.get("request", {})
        address_id = request.get("addressId")
        payment_method = request.get("paymentMethod")
        if not (address_id and payment_method in {"cod", "bank_transfer"}):
            # The storefront's checkout page owns address, payment method and
            # the final confirmation; the assistant prepares and opens it.
            return await self._checkout_handoff(state)
        cart = await self.marketplace.cart(state["user_id"])
        items = cart.get("products", []) if isinstance(cart, dict) else []
        picked = set(request.get("checkoutLineIds") or [])
        if picked:
            items = [item for item in items if item.get("productId") and _line_id(item) in picked]
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

    @staticmethod
    def _payment_method(state: AgentState) -> str | None:
        """The model's reading of the payment method; keyword matching only
        when no model decided the turn."""
        planned = (state.get("plan") or {}).get("payment_method")
        if planned:
            return planned
        requested = (state.get("request") or {}).get("paymentMethod")
        if _model_decided(state):
            return requested
        message = _normalized(state.get("message", ""))
        return (
            "cod" if re.search(r"\b(?:cod|khi nhan hang|tien mat)\b", message)
            else "bank_transfer" if re.search(r"\bchuyen khoan\b", message)
            else "wallet" if re.search(r"\bvi\b", message)
            else requested
        )

    async def _checkout_scope(
        self, state: AgentState, lines: list[dict]
    ) -> tuple[list[dict], dict | None]:
        """Which cart lines this checkout is for.

        Lines ticked in the widget are taken as they are. "cả giỏ"/"tất cả"
        selects every line; a request that names exactly one line ("chỉ thanh
        toán loa"), or only lines this chat added, selects those. Anything
        else with two or more lines ("thanh toán đơn áo thun" while the cart
        holds an older shirt too) returns a checkbox list instead, pre-ticked
        with the lines this chat added and the customer named.
        Returns (lines, picker); picker is set when asking.
        """
        picked = (state.get("request") or {}).get("checkoutLineIds")
        if picked:
            wanted = set(picked)
            return [item for item in lines if _line_id(item) in wanted], None
        if len(lines) < 2:
            return lines, None
        message = _normalized(state.get("message", ""))
        if _WHOLE_CART.search(message):
            return lines, None
        details = await asyncio.gather(
            *(self.marketplace.product(str(item["productId"])) for item in lines),
            return_exceptions=True,
        )
        products = {
            str(item["productId"]): product if isinstance(product, dict) else {}
            for item, product in zip(lines, details)
        }
        names = {key: str(product.get("name") or "") for key, product in products.items()}
        planned = {str(item) for item in (state.get("plan") or {}).get("product_ids") or []}
        words = [word for word in re.findall(r"\w+", message) if word not in _CHECKOUT_STOP_WORDS]

        def named(item: dict) -> bool:
            if str(item["productId"]) in planned:
                return True
            name_words = re.findall(r"\w+", _normalized(names.get(str(item["productId"]), "")))
            if not name_words:
                return False
            # The head word names the kind ("áo", "loa"); longer words name
            # the brand or model ("xiaomi", "realme").
            return any(word == name_words[0] or (len(word) >= 3 and word in name_words) for word in words)

        added = set(state.get("cart_lines_added") or [])
        selected = [item for item in lines if named(item)]
        selected_added = [item for item in selected if _line_id(item) in added]
        if len(selected) == 1 or (selected and len(selected_added) == len(selected)):
            return selected, None
        discussed = {
            str(state.get("active_product_id") or ""),
            *(str(item.get("id") or "") for item in state.get("focused_products", [])),
        } - {""}
        session_lines = [
            item for item in lines
            if _line_id(item) in added or str(item["productId"]) in discussed
        ]
        if not selected and not session_lines:
            # Nothing named and nothing from this chat: a plain "thanh toán"
            # still lets the customer untick lines, with all of them ticked.
            checked = lines
        else:
            checked = selected_added or selected or session_lines
        checked_ids = {_line_id(item) for item in checked}

        def label(item: dict) -> tuple[str, float]:
            product = products.get(str(item["productId"])) or {}
            variant = next(
                (
                    entry for entry in product.get("variants", [])
                    if _variant_id(entry) == str(item.get("variantId") or "")
                ),
                None,
            )
            name = product.get("name") or "Sản phẩm"
            if variant and variant.get("name") and variant.get("name") != name:
                name += f" ({variant['name']})"
            price = float((variant or {}).get("price") or product.get("price") or 0)
            return name, price

        options = []
        for item in lines:
            name, price = label(item)
            quantity = int(item.get("quantity") or 1)
            options.append({
                "id": _line_id(item),
                "label": name,
                "quantity": quantity,
                "price": price * quantity,
                "note": "vừa thêm trong chat" if _line_id(item) in added else "",
                "checked": _line_id(item) in checked_ids,
            })
        return lines, {
            "type": "checkout_select",
            "multiple": True,
            "submitLabel": "Thanh toán các mục đã chọn",
            "options": options,
        }

    async def _checkout_handoff(self, state: AgentState) -> dict:
        cart = await self.marketplace.cart(state["user_id"])
        lines = [
            item for item in (cart.get("products", []) if isinstance(cart, dict) else [])
            if item.get("productId") and int(item.get("quantity") or 0) > 0
        ]
        if not lines:
            return {"route": "checkout", "tool_result": {
                "error": "Giỏ hàng đang trống, bạn thêm sản phẩm trước khi thanh toán nhé."
            }}
        cart_size = len(lines)
        lines, picker = await self._checkout_scope(state, lines)
        if picker:
            return {"route": "checkout", "tool_result": {
                "clarification": (
                    f"Giỏ hàng của bạn có {cart_size} sản phẩm. Bạn tick những sản phẩm muốn thanh toán "
                    "bên dưới (mình đã chọn sẵn các món bạn vừa thêm/nhắc tới) rồi bấm Thanh toán nhé."
                ),
                "selection": picker,
            }}
        if not lines:
            return {"route": "checkout", "tool_result": {
                "error": "Các sản phẩm bạn chọn không còn trong giỏ hàng. Bạn kiểm tra lại giỏ nhé."
            }}
        cart = {**cart, "products": lines}
        partial = len(lines) < cart_size
        try:
            addresses = await self.marketplace.addresses(state["user_id"])
        except Exception:
            addresses = []
        if not addresses:
            return {"route": "checkout", "tool_result": {
                "status": "handoff_required",
                "tool": "open_addresses",
                "handoffMessage": (
                    "Bạn chưa có địa chỉ giao hàng. Mình mở trang Địa chỉ để bạn thêm, "
                    "sau đó nhắn \"thanh toán\" lại nhé."
                ),
            }}
        default = next((item for item in addresses if item.get("isDefault")), addresses[0])
        summary = await self._cart_summary(cart)
        if partial:
            # Only the chosen lines are paid; the rest stays in the cart.
            summary = summary.replace(
                "Giỏ hàng của bạn có", "Mình chỉ thanh toán", 1
            ) + f"\nCác sản phẩm còn lại ({cart_size - len(lines)}) vẫn được giữ trong giỏ."
        return {"route": "checkout", "tool_result": {
            "status": "handoff_required",
            "tool": "open_checkout",
            # Same line ids as the cart page: "<productId>::<variantId>".
            "selectedProductIds": [_line_id(item) for item in lines],
            "addressId": str(default.get("_id") or default.get("id") or ""),
            "paymentMethod": self._payment_method(state),
            "voucherCode": (state.get("request") or {}).get("voucherCode") or "",
            "handoffMessage": summary + "\nMình mở trang thanh toán để bạn kiểm tra địa chỉ, "
            "phương thức thanh toán và bấm Đặt hàng nhé.",
        }}

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
        updates: dict = {}
        if action.kind == "cart_add":
            added = [
                _line_id(item) for item in (payload.get("items") or [payload])
                if item.get("productId")
            ]
            updates["cart_lines_added"] = list(dict.fromkeys(
                [*(state.get("cart_lines_added") or []), *added]
            ))[-20:]
        if action.kind == "cart_add" and payload.get("items"):
            results = [
                await self.marketplace.add_to_cart(
                    state["user_id"],
                    item["productId"],
                    item.get("variantId"),
                    int(item["quantity"]),
                    f"{action.id}:{index}",
                )
                for index, item in enumerate(payload["items"])
            ]
            result = {"status": "completed", "cartChanged": True, "items": results}
        elif action.kind == "cart_add":
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
        if action.kind == "cart_add":
            # The widget offers "Thanh toán" for exactly the lines just added
            # and refreshes the cart badge on cartChanged.
            result = {
                **(result if isinstance(result, dict) else {}),
                "cartChanged": True,
                "addedLines": added,
            }
        return {
            **updates,
            "pending_action": None,
            "route": action.kind,
            "tool_result": {
                "success": True,
                "summary": action.summary,
                "result": result,
            },
        }
