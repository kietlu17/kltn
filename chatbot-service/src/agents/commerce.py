"""Deterministic, policy-gated shopping actions used by ProductAgent."""

from __future__ import annotations

import html
import logging
import re
import secrets
import unicodedata

from ..infrastructure.clients import CommerceError


log = logging.getLogger(__name__)

CHECKOUT_PATTERN = re.compile(
    r"\b(?:thanh toan|tinh tien|checkout|chot gio|chot don|dat hang|mua ngay|di thanh toan)\b"
)
VOUCHER_PATTERN = re.compile(r"\b(?:voucher|ma giam gia|ma khuyen mai|uu dai)\b")


def normalized(value: str) -> str:
    text = unicodedata.normalize("NFD", (value or "").casefold()).replace("đ", "d")
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def _plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value or ""))).strip()


def _money(value) -> str:
    try:
        return f"{float(value):,.0f}".replace(",", ".") + " đ"
    except (TypeError, ValueError):
        return "chưa có giá"


def resolve_product_references(
    message: str,
    products: list[dict],
    explicit_ids: list[str] | None = None,
    focused_ids: list[str] | None = None,
) -> list[str]:
    """Resolve one or more mentions only against IDs already shown to the shopper."""
    known = {str(item.get("id", "")): item for item in products if item.get("id")}
    ordered = list(known)
    resolved: list[str] = []
    for product_id in explicit_ids or []:
        if str(product_id) in known and str(product_id) not in resolved:
            resolved.append(str(product_id))

    text = normalized(message)
    ordinal_words = {
        "dau": 0, "nhat": 0, "mot": 0, "hai": 1, "ba": 2,
        "tu": 3, "bon": 3, "nam": 4, "sau": 5,
    }
    position_markers = r"mon|san pham|sp|cai|mau"
    positions = [
        int(number) - 1
        for number in re.findall(rf"\b(?:{position_markers})\s+(?:thu\s+)?([1-6])\b|\bthu\s+([1-6])\b", text)
        for number in number if number
    ]
    positions += [
        index
        for word, index in ordinal_words.items()
        if re.search(rf"\b(?:(?:{position_markers})\s+(?:thu\s+)?|thu\s+){word}\b", text)
    ]
    if re.search(r"\bso sanh\b", text):
        positions += [int(number) - 1 for number in re.findall(r"\b[1-6]\b", text)]
    for index in sorted(set(positions)):
        if index < len(ordered) and ordered[index] not in resolved:
            resolved.append(ordered[index])

    ignored = {
        "a", "an", "cai", "cho", "cuon", "gi", "hang", "i", "mon", "noi", "pham",
        "quyen", "san", "sach", "sp", "the", "them", "toi", "va", "vao", "ve",
        "chon", "lay", "mua", "ngay",
    }
    message_tokens = set(re.findall(r"[a-z0-9]+", text)) - ignored
    product_tokens = {
        product_id: set(re.findall(r"[a-z0-9]+", normalized(str(item.get("name", ""))))) - ignored
        for product_id, item in known.items()
    }
    token_frequency = {
        token: sum(token in tokens for tokens in product_tokens.values())
        for token in message_tokens
    }
    matches = []
    for product_id, item in known.items():
        name = normalized(str(item.get("name", "")))
        name_tokens = product_tokens[product_id]
        overlap = len(message_tokens & name_tokens)
        exact = bool(name and name in text)
        distinctive = any(
            len(token) >= 4 and token_frequency.get(token) == 1
            for token in message_tokens & name_tokens
        )
        if exact or distinctive or (overlap >= 2 and overlap / max(1, len(name_tokens)) >= 0.4):
            matches.append((1 if exact else 0, overlap, overlap / max(1, len(name_tokens)), product_id))
    matches.sort(reverse=True)
    if matches and (len(matches) == 1 or matches[0][:3] > matches[1][:3]):
        if matches[0][3] not in resolved:
            resolved.append(matches[0][3])

    if not resolved:
        for product_id in focused_ids or []:
            if str(product_id) in known and str(product_id) not in resolved:
                resolved.append(str(product_id))
    if not resolved and len(ordered) == 1:
        resolved.append(ordered[0])
    return resolved


def resolve_product_reference(
    message: str,
    products: list[dict],
    explicit_id: str | None = None,
    focused_id: str | None = None,
) -> str:
    references = resolve_product_references(
        message, products, [explicit_id] if explicit_id else [], [focused_id] if focused_id else []
    )
    return references[-1] if references else ""


class CommerceAgent:
    """Owns grounded product conversations and reversible cart preparation."""

    YES = {"co", "co a", "ok", "okay", "dong y", "xac nhan", "dung", "ap dung"}
    NO = {"khong", "khong dung", "bo qua", "khong ap", "doi dia chi"}
    CANCELLATIONS = {"huy", "huy thao tac", "khong mua nua", "bo qua"}
    FINAL_CONFIRMATIONS = {
        "xac nhan dat hang", "dong y dat hang", "dong y chot don",
        "chot don", "dat hang", "tien hanh dat hang",
    }
    CART_CONFIRMATIONS = {
        "xac nhan", "xac nhan thay doi gio", "xac nhan them vao gio",
        "xac nhan xoa khoi gio", "xac nhan doi san pham", "dong y thay doi gio",
    }

    def __init__(self, catalog, commerce):
        self.catalog = catalog
        self.commerce = commerce

    def _references(self, state: dict) -> list[str]:
        explicit = [str(state["reference_product_id"])] if state.get("reference_product_id") else []
        return resolve_product_references(
            state.get("message", ""), state.get("previous_products", []), explicit,
            state.get("focused_product_ids") or [state.get("focused_product_id", "")],
        )

    def detect(self, state: dict) -> str:
        text = normalized(state.get("message", ""))
        pending = state.get("pending_action") or {}
        if pending.get("type") == "cart_quantity_selection":
            if state.get("cancel_action_id") or text in self.CANCELLATIONS or text in self.NO:
                return "cancel_pending"
            return "configure_quantity"
        if pending.get("type") == "cart_mutation_confirmation":
            requested = state.get("confirm_action_id")
            if (requested and str(requested) == str(pending.get("actionId"))) or text in self.CART_CONFIRMATIONS:
                return "confirm_cart_mutation"
            if state.get("cancel_action_id") or text in self.CANCELLATIONS or text in self.NO:
                return "cancel_pending"
            return "await_cart_mutation"
        if pending.get("type") == "checkout_confirmation":
            requested = state.get("confirm_action_id")
            if (requested and str(requested) == str(pending.get("quoteId"))) or text in self.FINAL_CONFIRMATIONS:
                return "confirm_checkout"
            if state.get("cancel_action_id") or text in self.CANCELLATIONS or text in self.NO:
                return "cancel_pending"
            return "await_checkout_confirmation"
        if pending and text in {"huy", "huy thao tac", "khong mua nua"}:
            return "cancel_pending"
        if pending.get("type") == "cart_configuration":
            return "configure_cart"
        if pending.get("type") == "checkout_selection":
            return "checkout"
        if pending.get("type") == "checkout_handoff":
            return "checkout"
        references = self._references(state)
        if (
            text in {"gio", "gio hang", "cart"}
            or re.search(r"\b(xem|show|kiem tra|mo|liet ke)\b.*\b(gio|cart)\b", text)
            or re.search(r"\b(gio|cart)(?: hang)?\b.*\b(co gi|gom gi|hien tai|cua toi)\b", text)
            or re.search(r"\b(trong gio|trong cart)\b.*\b(co gi|nhung gi)\b", text)
        ):
            return "view_cart"
        if len(references) >= 2 and re.search(r"\b(so sanh|mon|san pham|sp|cai)\b", text):
            return "compare_products"
        if references and re.search(
            r"\b(chi tiet|noi dung|mo ta|thong tin|may sao|bao nhieu sao|rating|review|danh gia|khach hang noi)\b", text,
        ):
            return "product_details"
        if re.search(r"\b(xoa|bo|khong lay)\b", text) and (
            re.search(r"\b(gio|san pham|mon|cai|nua)\b", text)
            or pending.get("type") == "cart_view_context"
        ):
            return "remove_cart"
        if re.search(r"\b(doi|thay)\b.*\b(size|topping|bien the|san pham|mon|cai)\b", text):
            return "replace_cart"
        if (
            re.search(r"\b(so luong|qty)\b\s*(?:la|thanh)?\s*\d+|\bdoi\b.*\b\d+\b", text)
            or re.search(r"\b(tang|giam|bot)\b.*(?:\bso luong\b|\blen\b|\bxuong\b|\bthem\b|\bmon\b|\bcai\b|\d+)", text)
        ):
            return "set_quantity"
        if re.search(r"\b(them|bo)\b.*\b(gio hang|gio)\b", text):
            return "add_to_cart"
        if re.search(r"\b(mua|lay)\s+\d{1,3}\s*(?:cai|chiec|san pham)\b", text):
            return "add_to_cart"
        if references and re.search(r"\b(mua|lay|chon)\b", text) and not re.search(r"\bmua ngay\b", text):
            return "add_to_cart"
        if CHECKOUT_PATTERN.search(text) or VOUCHER_PATTERN.search(text):
            return "checkout"
        return ""

    @staticmethod
    def _quantity(message: str, default: int | None = 1) -> int | None:
        text = normalized(message)
        match = re.search(r"(?:so luong|qty|x|len|xuong|thanh)\s*(?:la|thanh)?\s*(\d{1,3})\b", text)
        if not match:
            match = re.search(r"\b(\d{1,3})\s*(?:cai|chiec|san pham|phan|quyen)\b", text)
        return int(match.group(1)) if match else default

    @staticmethod
    def _quantity_delta(message: str) -> int | None:
        text = normalized(message)
        match = re.search(r"\b(tang|giam|bot)\b(.*)", text)
        if not match or re.search(r"\b(len|xuong|thanh)\s*\d+\b", match.group(2)):
            return None
        amount = re.search(r"\b(\d{1,3})\b", match.group(2))
        value = int(amount.group(1)) if amount else 1
        return value if match.group(1) == "tang" else -value

    @staticmethod
    def _payment_method(state: dict) -> str:
        supplied = state.get("payment_method")
        if supplied in {"cod", "bank_transfer", "wallet"}:
            return supplied
        text = normalized(state.get("message", ""))
        if re.search(r"\b(cod|nhan hang|tien mat)\b", text):
            return "cod"
        if re.search(r"\b(chuyen khoan|bank transfer|sepay|qr)\b", text):
            return "bank_transfer"
        if re.search(r"\b(vi|wallet)\b", text):
            return "wallet"
        return ""

    async def execute(self, state: dict) -> dict:
        intent = state.get("commerce_intent", "")
        try:
            if intent == "product_details":
                return await self._product_details(state)
            if intent == "compare_products":
                return await self._compare_products(state)
            user_id = state.get("authenticated_user_id", "")
            if not user_id or state.get("actor_role") != "buyer":
                return {
                    "answer": "Bạn cần đăng nhập bằng tài khoản người mua trước khi tôi thay đổi giỏ hàng hoặc chuẩn bị thanh toán.",
                    "products": [], "action_result": {"status": "authentication_required", "intent": intent},
                }
            handlers = {
                "view_cart": self._view_cart,
                "add_to_cart": self._add_to_cart, "configure_cart": self._configure_cart,
                "configure_quantity": self._configure_quantity,
                "set_quantity": self._set_quantity, "remove_cart": self._remove_cart,
                "replace_cart": self._replace_cart, "checkout": self._checkout,
                "confirm_cart_mutation": self._confirm_cart_mutation,
                "confirm_checkout": self._confirm_checkout,
            }
            if intent == "await_cart_mutation":
                return self._await_cart_mutation(state)
            if intent == "await_checkout_confirmation":
                return self._await_checkout_confirmation(state)
            if intent == "cancel_pending":
                return self._cancel_pending()
            if intent in handlers:
                return await handlers[intent](state, user_id)
        except CommerceError as exc:
            return {
                "answer": str(exc), "products": [],
                "action_result": {"status": "rejected", "intent": intent, "code": exc.code},
            }
        return {"answer": "Tôi chưa xác định được thao tác mua hàng.", "products": []}

    def _product_id(self, state: dict) -> str:
        references = self._references(state)
        if len(references) == 1:
            return references[0]
        products = state.get("previous_products", [])
        return str(products[0].get("id")) if len(products) == 1 else ""

    @staticmethod
    def _variant_matches(message: str, variants: list[dict]) -> list[dict]:
        text = normalized(message)
        exact = [item for item in variants if normalized(str(item.get("name", ""))) in text]
        if exact:
            return exact
        tokens = set(re.findall(r"[a-z0-9]+", text)) - {"doi", "size", "topping", "chon", "lay", "them"}
        scored = []
        for item in variants:
            name_tokens = set(re.findall(r"[a-z0-9]+", normalized(str(item.get("name", "")))))
            score = len(tokens & name_tokens)
            if score:
                scored.append((score, item))
        if not scored:
            return variants
        best = max(score for score, _ in scored)
        return [item for score, item in scored if score == best]

    @staticmethod
    def _variant_options(variants: list[dict]) -> str:
        return ", ".join(f"{item.get('name', 'Mặc định')} ({_money(item.get('price'))})" for item in variants[:10])

    async def _product_details(self, state: dict) -> dict:
        references = self._references(state)
        if len(references) != 1:
            return {
                "answer": "Bạn hãy chọn đúng một sản phẩm để xem chi tiết.",
                "products": state.get("previous_products", []),
                "action_result": {"status": "clarification_required", "intent": "product_details"},
            }
        product_id = references[0]
        product = await self.catalog.product(product_id)
        if not product:
            raise CommerceError(404, "Sản phẩm không còn khả dụng.")
        summaries = await self.catalog.review_summaries([product_id])
        raw_reviews = await self.catalog.reviews(product_id)
        summary = next((item for item in summaries.get("items", []) if str(item.get("productId")) == product_id), {})
        reviews = raw_reviews.get("items", []) if isinstance(raw_reviews, dict) else raw_reviews
        description = _plain_text(product.get("description") or product.get("detail") or "")
        rating = summary.get("averageRating", product.get("averageRating"))
        count = summary.get("reviewCount", product.get("reviewCount", 0))
        rating_text = f"{float(rating):.1f}/5 từ {int(count or 0)} đánh giá" if rating is not None else "chưa có đánh giá"
        comments = []
        for review in (reviews or [])[:3]:
            comment = _plain_text(str(review.get("comment") or review.get("content") or ""))
            if comment:
                comments.append(f"{review.get('rating', '?')}★: “{comment[:180]}”")
        variants = product.get("variants") or []
        answer = f"{product.get('name', 'Sản phẩm')} — {_money(product.get('price'))}. {description[:700] or 'Catalog chưa có mô tả chi tiết.'} Đánh giá: {rating_text}."
        if variants:
            answer += f" Có {len(variants)} lựa chọn: {self._variant_options(variants)}."
        answer += " Phản hồi gần đây: " + ("; ".join(comments) if comments else "chưa có bình luận bằng chữ.")
        card = next((item for item in state.get("previous_products", []) if str(item.get("id")) == product_id), {"id": product_id, "name": product.get("name"), "price": product.get("price")})
        return {"answer": answer, "products": [card], "focused_product_id": product_id, "focused_product_ids": [product_id]}

    async def _compare_products(self, state: dict) -> dict:
        references = self._references(state)[:4]
        if len(references) < 2:
            return {"answer": "Bạn hãy chọn ít nhất hai sản phẩm để so sánh.", "products": state.get("previous_products", [])}
        summaries = await self.catalog.review_summaries(references)
        summary_map = {str(item.get("productId")): item for item in summaries.get("items", [])}
        lines, cards = [], []
        for product_id in references:
            product = await self.catalog.product(product_id)
            if not product:
                continue
            summary = summary_map.get(product_id, {})
            rating = summary.get("averageRating")
            reviews = int(summary.get("reviewCount") or 0)
            stars = f"{float(rating):.1f}/5 ({reviews} đánh giá)" if rating is not None else "chưa có đánh giá"
            lines.append(f"• {product.get('name')}: {_money(product.get('price'))}, {stars}, {len(product.get('variants') or [])} biến thể.")
            cards.append(next((item for item in state.get("previous_products", []) if str(item.get("id")) == product_id), {"id": product_id, "name": product.get("name"), "price": product.get("price")}))
        return {
            "answer": "So sánh theo dữ liệu hiện có:\n" + "\n".join(lines), "products": cards,
            "focused_product_id": references[-1], "focused_product_ids": references,
        }

    async def _view_cart(self, state: dict, user_id: str) -> dict:
        items, _ = await self._checkout_items(user_id)
        if not items:
            return {
                "answer": "Giỏ hàng của bạn đang trống.",
                "products": [],
                "pending_action": None,
                "action_result": {"status": "shown", "intent": "view_cart", "items": [], "subtotal": 0},
            }
        lines, subtotal = [], 0.0
        for index, item in enumerate(items, 1):
            line_total = float(item.get("price", 0)) * int(item.get("quantity", 0))
            subtotal += line_total
            variant = f" ({item.get('variantName')})" if item.get("variantName") else ""
            lines.append(
                f"{index}. {item.get('productName')}{variant} × {item.get('quantity')} — {_money(line_total)}"
            )
        context_items = [
            {
                "productId": item.get("productId"),
                "variantId": item.get("variantId"),
                "productName": item.get("productName"),
                "variantName": item.get("variantName"),
                "quantity": item.get("quantity"),
                "price": item.get("price"),
            }
            for item in items
        ]
        return {
            "answer": "Giỏ hàng hiện có:\n" + "\n".join(lines) + f"\nTạm tính: {_money(subtotal)}.",
            "products": [],
            "pending_action": {"type": "cart_view_context", "lineOptions": context_items},
            "action_result": {"status": "shown", "intent": "view_cart", "items": context_items, "subtotal": subtotal},
        }

    async def _add_to_cart(self, state: dict, user_id: str) -> dict:
        product_id = self._product_id(state)
        if not product_id:
            return {
                "answer": "Bạn hãy chọn đúng một sản phẩm cần thêm vào giỏ.",
                "products": state.get("previous_products", []),
                "action_result": {"status": "clarification_required", "intent": "add_to_cart"},
            }
        product = await self.catalog.product(product_id)
        if not product:
            raise CommerceError(409, "Sản phẩm không còn khả dụng.")
        variants = product.get("variants") or []
        variant_id = state.get("variant_id")
        inherited_terms = " ".join(state.get("previous_plan", {}).get("variant_terms") or [])
        selection = f"{state.get('message', '')} {inherited_terms}".strip()
        candidates = self._variant_matches(selection, variants) if variants and not variant_id else []
        if not variant_id and len(candidates) == 1:
            variant_id = str(candidates[0].get("_id") or candidates[0].get("id"))
        elif variants and not variant_id:
            return self._variant_question(product, candidates, "add", self._quantity(state.get("message", ""), 1) or 1)
        return await self._complete_add(state, user_id, product, variant_id, self._quantity(state.get("message", ""), 1) or 1)

    def _variant_question(self, product: dict, variants: list[dict], operation: str, quantity: int, old_line: dict | None = None) -> dict:
        product_id = str(product.get("_id") or product.get("id"))
        candidates = [{"id": str(item.get("_id") or item.get("id")), "name": item.get("name"), "price": item.get("price")} for item in variants]
        pending = {"type": "cart_configuration", "operation": operation, "productId": product_id, "productName": product.get("name"), "quantity": quantity, "candidates": candidates}
        if old_line:
            pending["oldLine"] = old_line
        return {
            "answer": f"{product.get('name')} có nhiều lựa chọn. Bạn muốn loại nào: {self._variant_options(variants)}?",
            "products": [], "pending_action": pending,
            "action_result": {"status": "clarification_required", "intent": operation},
        }

    async def _configure_cart(self, state: dict, user_id: str) -> dict:
        pending = state.get("pending_action") or {}
        variants = [{"_id": item.get("id"), **item} for item in pending.get("candidates", [])]
        matches = self._variant_matches(state.get("message", ""), variants)
        if len(matches) != 1:
            product = {"_id": pending.get("productId"), "name": pending.get("productName")}
            return self._variant_question(product, matches, pending.get("operation", "add"), int(pending.get("quantity", 1)), pending.get("oldLine"))
        variant_id = str(matches[0].get("_id") or matches[0].get("id"))
        product = await self.catalog.product(str(pending.get("productId")))
        if not product:
            raise CommerceError(409, "Sản phẩm không còn khả dụng.")
        if pending.get("operation") == "replace":
            return await self._complete_replace(user_id, product, variant_id, int(pending.get("quantity", 1)), pending.get("oldLine") or {})
        return await self._complete_add(state, user_id, product, variant_id, int(pending.get("quantity", 1)))

    async def _complete_add(self, state: dict, user_id: str, product: dict, variant_id: str | None, quantity: int) -> dict:
        if quantity < 1 or quantity > 100:
            raise CommerceError(400, "Số lượng mỗi dòng phải từ 1 đến 100.")
        product_id = str(product.get("_id") or product.get("id"))
        variant = next((item for item in product.get("variants", []) if str(item.get("_id") or item.get("id")) == str(variant_id)), None)
        return self._prepare_cart_mutation(
            "add_to_cart",
            productId=product_id,
            productName=product.get("name") or "Sản phẩm",
            variantId=variant_id,
            variantName=variant.get("name") if variant else None,
            quantity=quantity,
        )

    async def _cart_line(self, state: dict, user_id: str) -> dict | None:
        pending = state.get("pending_action") or {}
        lines = (await self.commerce.cart(user_id)).get("products", [])
        if pending.get("type") == "cart_line_context":
            match = next((line for line in lines if str(line.get("productId")) == str(pending.get("productId")) and str(line.get("variantId") or "") == str(pending.get("variantId") or "")), None)
            if match:
                return {**match, "productName": pending.get("productName"), "variantName": pending.get("variantName")}
        if pending.get("type") in {"cart_view_context", "cart_quantity_selection"}:
            options = pending.get("lineOptions", [])
            selected = self._resolve_checkout_selection(state, options)
            if len(selected) == 1:
                option = next((item for item in options if self._line_id(item) == selected[0]), {})
                match = next((line for line in lines if self._line_id(line) == selected[0]), None)
                if match:
                    return {**match, "productName": option.get("productName"), "variantName": option.get("variantName")}
            return None
        product_id = self._product_id(state)
        matches = [line for line in lines if not product_id or str(line.get("productId")) == product_id]
        return matches[0] if len(matches) == 1 else None

    async def _set_quantity(self, state: dict, user_id: str) -> dict:
        delta = self._quantity_delta(state.get("message", ""))
        requested_quantity = self._quantity(state.get("message", ""), None)
        request = {
            "delta": delta,
            "targetQuantity": None if delta is not None else requested_quantity,
            "nextAction": "checkout" if self._checkout_requested(state.get("message", "")) else None,
        }
        line = await self._cart_line(state, user_id)
        if not line:
            pending = state.get("pending_action") or {}
            options = pending.get("lineOptions", []) if pending.get("type") == "cart_view_context" else []
            if not options:
                options, _ = await self._checkout_items(user_id)
            if not options:
                return {"answer": "Giỏ hàng đang trống.", "products": [], "pending_action": None, "action_result": {"status": "rejected", "intent": "set_quantity", "code": "EMPTY_CART"}}
            choices = "; ".join(
                f"{index}. {item.get('productName')}"
                + (f" ({item.get('variantName')})" if item.get("variantName") else "")
                + f" × {item.get('quantity')}"
                for index, item in enumerate(options, 1)
            )
            return {
                "answer": f"Bạn muốn đổi số lượng dòng nào: {choices}?",
                "products": [],
                "pending_action": {"type": "cart_quantity_selection", "lineOptions": options, **request},
                "action_result": {"status": "clarification_required", "intent": "set_quantity"},
            }
        return self._prepare_quantity_change(line, request)

    async def _configure_quantity(self, state: dict, user_id: str) -> dict:
        pending = state.get("pending_action") or {}
        line = await self._cart_line(state, user_id)
        if not line:
            return {
                "answer": "Tôi chưa xác định được dòng giỏ hàng. Bạn chọn theo số thứ tự hoặc nói phần tên riêng của sản phẩm nhé.",
                "products": [],
                "pending_action": pending,
                "action_result": {"status": "clarification_required", "intent": "set_quantity"},
            }
        request = {
            "delta": pending.get("delta"),
            "targetQuantity": pending.get("targetQuantity"),
            "nextAction": pending.get("nextAction"),
        }
        return self._prepare_quantity_change(line, request)

    def _prepare_quantity_change(self, line: dict, request: dict) -> dict:
        current = int(line.get("quantity", 0))
        delta = request.get("delta")
        quantity = current + int(delta) if delta is not None else request.get("targetQuantity")
        if quantity is None:
            return {"answer": "Bạn hãy nói rõ số lượng mới hoặc muốn tăng/giảm bao nhiêu.", "products": [], "action_result": {"status": "clarification_required", "intent": "set_quantity"}}
        quantity = int(quantity)
        if quantity < 0 or quantity > 100:
            raise CommerceError(400, "Số lượng sau thay đổi phải từ 0 đến 100.")
        operation = "remove_cart" if quantity == 0 else "set_quantity"
        return self._prepare_cart_mutation(
            operation,
            productId=line["productId"],
            productName=line.get("productName") or "Sản phẩm đã chọn",
            variantId=line.get("variantId"),
            variantName=line.get("variantName"),
            expectedQuantity=current,
            targetQuantity=quantity,
            nextAction=request.get("nextAction"),
        )

    async def _remove_cart(self, state: dict, user_id: str) -> dict:
        line = await self._cart_line(state, user_id)
        if not line:
            return {"answer": "Bạn hãy chọn đúng dòng sản phẩm cần xóa.", "products": [], "action_result": {"status": "clarification_required", "intent": "remove_cart"}}
        return self._prepare_cart_mutation(
            "remove_cart",
            productId=line["productId"],
            productName=line.get("productName") or "Sản phẩm đã chọn",
            variantId=line.get("variantId"),
            variantName=line.get("variantName"),
            expectedQuantity=int(line.get("quantity", 0)),
            targetQuantity=0,
        )

    async def _replace_cart(self, state: dict, user_id: str) -> dict:
        old_line = await self._cart_line(state, user_id)
        if not old_line:
            return {"answer": "Bạn hãy chọn dòng trong giỏ cần đổi.", "products": [], "action_result": {"status": "clarification_required", "intent": "replace_cart"}}
        references = self._references(state)
        new_product_id = references[-1] if references else str(old_line["productId"])
        product = await self.catalog.product(new_product_id)
        if not product:
            raise CommerceError(409, "Sản phẩm thay thế không còn khả dụng.")
        variants = product.get("variants") or []
        matches = self._variant_matches(state.get("message", ""), variants) if variants else []
        if variants and len(matches) != 1:
            return self._variant_question(product, matches, "replace", int(old_line.get("quantity", 1)), old_line)
        variant_id = str(matches[0].get("_id") or matches[0].get("id")) if matches else None
        return await self._complete_replace(user_id, product, variant_id, int(old_line.get("quantity", 1)), old_line)

    async def _complete_replace(self, user_id: str, product: dict, variant_id: str | None, quantity: int, old_line: dict) -> dict:
        product_id = str(product.get("_id") or product.get("id"))
        variant = next((item for item in product.get("variants", []) if str(item.get("_id") or item.get("id")) == str(variant_id)), None)
        return self._prepare_cart_mutation(
            "replace_cart",
            oldProductId=str(old_line.get("productId")),
            oldProductName=old_line.get("productName") or "Sản phẩm hiện tại",
            oldVariantId=old_line.get("variantId"),
            productId=product_id,
            productName=product.get("name") or "Sản phẩm thay thế",
            variantId=variant_id,
            variantName=variant.get("name") if variant else None,
            quantity=quantity,
        )

    def _prepare_cart_mutation(self, operation: str, **details) -> dict:
        action_id = secrets.token_urlsafe(24)
        pending = {"type": "cart_mutation_confirmation", "actionId": action_id, "operation": operation, **details}
        product = details.get("productName") or "sản phẩm"
        variant = f" ({details.get('variantName')})" if details.get("variantName") else ""
        if operation == "add_to_cart":
            summary = f"thêm {details.get('quantity')} × {product}{variant} vào giỏ"
        elif operation == "set_quantity":
            summary = f"đổi số lượng {product}{variant} từ {details.get('expectedQuantity')} thành {details.get('targetQuantity')}"
        elif operation == "remove_cart":
            summary = f"xóa {product}{variant} khỏi giỏ"
        else:
            summary = f"đổi {details.get('oldProductName', 'sản phẩm hiện tại')} sang {product}{variant}, số lượng {details.get('quantity')}"
        return {
            "answer": f"Tôi chuẩn bị {summary}. Hãy trả lời đúng “xác nhận” để thực hiện hoặc “hủy” để dừng.",
            "products": [],
            "pending_action": pending,
            "action_result": {"status": "confirmation_required", "intent": operation, "actionId": action_id},
        }

    @staticmethod
    def _await_cart_mutation(state: dict) -> dict:
        pending = state.get("pending_action") or {}
        return {
            "answer": "Giỏ hàng chưa thay đổi. Bạn hãy trả lời đúng “xác nhận” để thực hiện hoặc “hủy” để dừng.",
            "products": [],
            "pending_action": pending,
            "action_result": {"status": "confirmation_required", "intent": pending.get("operation"), "actionId": pending.get("actionId")},
        }

    async def _confirm_cart_mutation(self, state: dict, user_id: str) -> dict:
        pending = state.get("pending_action") or {}
        requested = state.get("confirm_action_id")
        confirmed_by_id = requested and str(requested) == str(pending.get("actionId"))
        confirmed_by_text = normalized(state.get("message", "")) in self.CART_CONFIRMATIONS
        if pending.get("type") != "cart_mutation_confirmation" or not (confirmed_by_id or confirmed_by_text):
            return self._await_cart_mutation(state)
        operation = pending.get("operation")
        product_id, variant_id = str(pending.get("productId")), pending.get("variantId")
        if operation == "add_to_cart":
            quantity = int(pending.get("quantity", 1))
            result = await self.commerce.add_to_cart(
                user_id, product_id, variant_id, quantity, str(pending.get("actionId"))
            )
            answer = f"Đã thêm {quantity} × {pending.get('productName', 'sản phẩm')} vào giỏ hàng."
            action_result = {"status": "completed", "intent": operation, "productId": product_id, "variantId": variant_id, "quantity": quantity, "replayed": bool(result.get("replayed"))}
        elif operation in {"set_quantity", "remove_cart"}:
            target = int(pending.get("targetQuantity", 0))
            expected = int(pending.get("expectedQuantity", 0))
            await self.commerce.set_cart_line(user_id, product_id, variant_id, target, expected)
            answer = "Đã xóa sản phẩm khỏi giỏ hàng." if target == 0 else f"Đã đổi số lượng thành {target}."
            action_result = {"status": "completed", "intent": operation, "productId": product_id, "variantId": variant_id, "quantity": target}
        elif operation == "replace_cart":
            quantity = int(pending.get("quantity", 1))
            await self.commerce.replace_cart_line(
                user_id,
                str(pending.get("oldProductId")),
                pending.get("oldVariantId"),
                product_id,
                variant_id,
                quantity,
            )
            answer = f"Đã đổi sang {pending.get('productName', 'sản phẩm mới')}, giữ số lượng {quantity}."
            action_result = {"status": "completed", "intent": operation, "productId": product_id, "variantId": variant_id, "quantity": quantity}
        else:
            return {"answer": "Yêu cầu thay đổi giỏ không còn hợp lệ.", "products": [], "pending_action": None, "action_result": {"status": "rejected", "intent": operation, "code": "INVALID_CART_MUTATION"}}
        context = None if operation == "remove_cart" else {
            "type": "cart_line_context",
            "productId": product_id,
            "productName": pending.get("productName"),
            "variantId": variant_id,
            "variantName": pending.get("variantName"),
            "quantity": action_result.get("quantity"),
        }
        if operation == "add_to_cart":
            try:
                checkout_items, _ = await self._checkout_items(user_id)
                eligible = [
                    voucher
                    for voucher in await self.commerce.checkout_vouchers(user_id, checkout_items)
                    if voucher.get("eligible")
                ]
                action_result["checkoutSuggested"] = True
                action_result["eligibleVouchers"] = eligible[:5]
                if eligible:
                    best = eligible[0]
                    answer += (
                        f" Giỏ hàng hiện có mã {best.get('code')} giảm "
                        f"{_money(best.get('discountAmount'))}. Bạn có muốn chuyển sang trang thanh toán không?"
                    )
                else:
                    answer += " Hiện chưa có voucher phù hợp. Bạn có muốn chuyển sang trang thanh toán không?"
            except Exception as exc:
                # The cart mutation already succeeded; a voucher lookup failure
                # must never turn that completed action into an error.
                log.warning("Voucher suggestion unavailable after cart update: %s", exc)
                action_result["checkoutSuggested"] = True
                answer += " Bạn có muốn chuyển sang trang thanh toán để kiểm tra ưu đãi không?"
        if pending.get("nextAction") == "checkout":
            try:
                checkout = await self._checkout(
                    {**state, "message": "thanh toán", "pending_action": None, "reference_product_id": None},
                    user_id,
                )
                checkout["answer"] = answer + "\n" + checkout["answer"]
                checkout_action = dict(checkout.get("action_result") or {})
                checkout_action.update(cartChanged=True, cartMutation=action_result)
                checkout["action_result"] = checkout_action
                return checkout
            except CommerceError as exc:
                answer += f" Tuy nhiên chưa thể chuẩn bị thanh toán: {exc}"
                action_result["checkoutStatus"] = "unavailable"
        return {"answer": answer, "products": [], "pending_action": context, "action_result": action_result}

    @staticmethod
    def _line_id(line: dict) -> str:
        return f"{line.get('productId')}::{line.get('variantId') or ''}"

    async def _checkout_items(
        self, user_id: str, selected_line_ids: list[str] | None = None
    ) -> tuple[list[dict], list[str]]:
        lines = (await self.commerce.cart(user_id)).get("products", [])
        selected = set(selected_line_ids or [])
        voucher_items, selected_ids = [], []
        for line in lines:
            line_id = self._line_id(line)
            if selected_line_ids is not None and line_id not in selected:
                continue
            product = await self.catalog.product(str(line.get("productId")))
            if not product:
                continue
            variant = next((item for item in product.get("variants", []) if str(item.get("_id") or item.get("id")) == str(line.get("variantId") or "")), None)
            price = variant.get("price") if variant else product.get("price")
            voucher_items.append({
                "productId": str(line.get("productId")),
                "variantId": line.get("variantId"),
                "productName": product.get("name") or "Sản phẩm",
                "variantName": variant.get("name") if variant else None,
                "shopId": str(product.get("shopId") or ""),
                "price": float(price or 0),
                "quantity": int(line.get("quantity", 0)),
            })
            selected_ids.append(line_id)
        return voucher_items, selected_ids

    def _resolve_checkout_selection(self, state: dict, items: list[dict]) -> list[str]:
        if not items:
            return []
        text = normalized(state.get("message", ""))
        all_ids = [self._line_id(item) for item in items]
        if (
            re.search(r"\b(ca gio|toan bo gio|tat ca|het gio|chot gio)\b", text)
            or text in {"thanh toan", "tinh tien", "checkout", "chot don", "dat hang", "mua ngay"}
            or VOUCHER_PATTERN.search(text)
        ):
            return all_ids

        positions = []
        for match in re.finditer(r"\b(?:san pham|sp|mon|dong|cai|so)\s*(?:thu|so)?\s*([1-9]\d*)\b", text):
            positions.append(int(match.group(1)) - 1)
        ordinal_words = {"dau": 0, "nhat": 0, "hai": 1, "ba": 2, "tu": 3, "bon": 3, "nam": 4, "sau": 5}
        for word, index in ordinal_words.items():
            if re.search(rf"\b(?:san pham|sp|mon|dong|cai)\s+(?:thu\s+)?{word}\b", text):
                positions.append(index)
        by_position = [all_ids[index] for index in sorted(set(positions)) if index < len(all_ids)]
        if by_position:
            return by_position

        cart_products = [{"id": item["productId"], "name": item.get("productName", "")} for item in items]
        explicit = [str(state["reference_product_id"])] if state.get("reference_product_id") else []
        product_ids = resolve_product_references(state.get("message", ""), cart_products, explicit_ids=explicit)
        if not product_ids:
            ignored = {
                "tang", "giam", "bot", "them", "len", "xuong", "so", "luong", "thanh", "toan",
                "gio", "hang", "cart", "checkout", "san", "pham", "sp", "mon", "cai", "dong",
                "chi", "muon", "doi", "va", "roi", "sau", "do",
            }
            terms = {
                token for token in re.findall(r"[a-z0-9]+", text)
                if token not in ignored and not token.isdigit() and len(token) > 1
            }
            scored = []
            for item in items:
                label = normalized(
                    f"{item.get('productName', '')} {item.get('variantName', '')}"
                )
                label_terms = set(re.findall(r"[a-z0-9]+", label))
                overlap = len(terms & label_terms)
                if overlap:
                    scored.append((overlap, self._line_id(item)))
            scored.sort(reverse=True)
            if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
                return [scored[0][1]]
            pending = state.get("pending_action") or {}
            if pending.get("type") == "cart_line_context" and len(items) > 1:
                pending_id = self._line_id(pending)
                if pending_id in all_ids:
                    return [pending_id]
            return all_ids if len(items) == 1 else []

        matching = [item for item in items if str(item.get("productId")) in product_ids]
        requested_variant = str(state.get("variant_id") or "")
        if requested_variant:
            matching = [item for item in matching if str(item.get("variantId") or "") == requested_variant]
        elif len(matching) > 1 and len({item.get("productId") for item in matching}) == 1:
            variant_matches = [
                item for item in matching
                if item.get("variantName") and normalized(str(item["variantName"])) in text
            ]
            if len(variant_matches) == 1:
                matching = variant_matches
            else:
                return []
        return [self._line_id(item) for item in matching]

    @staticmethod
    def _checkout_requested(message: str) -> bool:
        return bool(CHECKOUT_PATTERN.search(normalized(message)))

    def _checkout_selection_question(self, items: list[dict]) -> dict:
        choices = "; ".join(
            f"{index}. {item.get('productName')}"
            + (f" ({item.get('variantName')})" if item.get("variantName") else "")
            + f" × {item.get('quantity')}"
            for index, item in enumerate(items, 1)
        )
        return {
            "answer": (
                f"Giỏ hàng có nhiều sản phẩm: {choices}. "
                "Bạn muốn thanh toán cả giỏ hay chỉ sản phẩm số mấy?"
            ),
            "products": [],
            "pending_action": {
                "type": "checkout_selection",
                "lineOptions": [self._line_id(item) for item in items],
            },
            "action_result": {"status": "clarification_required", "intent": "checkout"},
        }

    async def _checkout(self, state: dict, user_id: str) -> dict:
        all_items, all_ids = await self._checkout_items(user_id)
        if not all_ids:
            return {"answer": "Giỏ hàng đang trống. Bạn hãy thêm sản phẩm trước khi thanh toán.", "products": [], "pending_action": None, "action_result": {"status": "rejected", "intent": "checkout", "code": "EMPTY_CART"}}
        pending = state.get("pending_action") or {}
        if pending.get("type") in {"checkout_handoff", "checkout_confirmation"}:
            requested_ids = [str(item) for item in pending.get("selectedProductIds", [])]
            _, selected_ids = await self._checkout_items(user_id, requested_ids)
            if set(selected_ids) != set(requested_ids):
                return {
                    "answer": "Sản phẩm đã chọn trong giỏ vừa thay đổi. Bạn hãy chọn lại sản phẩm cần thanh toán.",
                    "products": [],
                    "pending_action": None,
                    "action_result": {"status": "rejected", "intent": "checkout", "code": "CART_SELECTION_CHANGED"},
                }
        else:
            selected_ids = self._resolve_checkout_selection(state, all_items)
            if not selected_ids:
                return self._checkout_selection_question(all_items)
        return self._checkout_handoff(selected_ids)

    @staticmethod
    def _await_checkout_confirmation(state: dict) -> dict:
        pending = state.get("pending_action") or {}
        return CommerceAgent._checkout_handoff(
            pending.get("selectedProductIds", []),
            payment_method=pending.get("paymentMethod"),
            voucher_code=pending.get("voucherCode"),
            address_id=(pending.get("shippingAddress") or {}).get("_id") or pending.get("addressId"),
        )

    async def _confirm_checkout(self, state: dict, user_id: str) -> dict:
        pending = state.get("pending_action") or {}
        return self._checkout_handoff(
            pending.get("selectedProductIds", []),
            payment_method=pending.get("paymentMethod"),
            voucher_code=pending.get("voucherCode"),
            address_id=(pending.get("shippingAddress") or {}).get("_id") or pending.get("addressId"),
        )

    @staticmethod
    def _checkout_handoff(
        selected_product_ids: list[str],
        payment_method: str | None = None,
        voucher_code: str | None = None,
        address_id: str | None = None,
    ) -> dict:
        return {
            "answer": "Tôi đã chuyển lựa chọn sang trang thanh toán. Bạn vui lòng tự kiểm tra và xác nhận đơn hàng; chatbot sẽ không tạo đơn hoặc thực hiện thanh toán thay bạn.",
            "products": [],
            "pending_action": None,
            "action_result": {
                "status": "handoff_required",
                "intent": "checkout",
                "tool": "open_checkout",
                "selectedProductIds": [str(item) for item in selected_product_ids],
                "paymentMethod": payment_method,
                "voucherCode": voucher_code,
                "addressId": address_id,
                "deliveryMethod": "home_delivery",
            },
        }

    async def _ask_address(self, user_id: str, context: dict, list_all: bool = False) -> dict:
        addresses = await self.commerce.addresses(user_id)
        if not addresses:
            return self._open_addresses(context)
        default = next((item for item in addresses if item.get("isDefault")), addresses[0])
        context = {**context, "stage": "address", "proposedAddressId": str(default.get("_id") or default.get("id"))}
        def label(item):
            return " - ".join(str(item.get(key)) for key in ("label", "line1", "city", "phone") if item.get(key))
        message = "; ".join(label(item) for item in addresses[:5]) if list_all else label(default)
        prefix = "Các địa chỉ của bạn" if list_all else "Tôi sẽ giao tận nơi tới địa chỉ mặc định"
        return {"answer": f"{prefix}: {message}. Bạn xác nhận địa chỉ này chứ?", "products": [], "pending_action": context, "action_result": {"status": "clarification_required", "intent": "checkout"}}

    @staticmethod
    def _open_addresses(context: dict) -> dict:
        return {"answer": "Bạn chưa có địa chỉ giao hàng. Hãy thêm địa chỉ, sau đó quay lại thanh toán.", "products": [], "pending_action": context, "action_result": {"status": "handoff_required", "intent": "checkout", "tool": "open_addresses"}}

    @staticmethod
    def _cancel_pending() -> dict:
        return {"answer": "Đã hủy thao tác đang chờ. Giỏ hàng, đơn hàng và thanh toán đều không thay đổi.", "products": [], "pending_action": None, "action_result": {"status": "cancelled"}}
