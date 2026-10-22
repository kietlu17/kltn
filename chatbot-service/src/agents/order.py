"""Order-domain subgraph backed by authenticated, read-only commerce tools."""
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from langgraph.graph import END, START, StateGraph

from .state import ChatState


ORDER_STATUSES = {
    "pending_payment": "chờ thanh toán",
    "payment_processing": "đang xử lý thanh toán",
    "paid": "đã thanh toán",
    "confirmed": "đã xác nhận",
    "shipped": "đang giao",
    "delivered": "đã giao",
    "completed": "hoàn tất",
    "payment_failed": "thanh toán thất bại",
    "cancelled": "đã hủy",
    "refund_processing": "đang hoàn tiền",
    "refunded": "đã hoàn tiền",
}
SHIPMENT_STATUSES = {
    "requested": "đã tạo vận đơn",
    "handed_over": "đã bàn giao cho đơn vị vận chuyển",
    "picked_up": "đã lấy hàng",
    "in_transit": "đang vận chuyển",
    "delivered": "đã giao",
}


def _normalize(message: str) -> str:
    text = unicodedata.normalize("NFD", (message or "").casefold()).replace("đ", "d")
    return "".join(char for char in text if not unicodedata.combining(char))


def _order_id(message: str) -> str:
    match = re.search(r"(?:#\s*|\b(?:don(?: hang)?|order)\s*(?:so|ma|id|#)?\s*)(\d{1,12})\b", _normalize(message))
    return match.group(1) if match else ""


def _product_query(message: str) -> str:
    text = re.sub(r"\s+", " ", _normalize(message)).strip()
    match = re.match(r"^don(?: hang)?\s+(.+)", text)
    if not match:
        return ""
    query = re.split(
        r"\b(?:dang|hien|o dau|den dau|toi dau|trang thai|tinh trang|cua toi|cua minh|nay|do)\b",
        match.group(1), maxsplit=1,
    )[0].strip(" ?!.,")
    return query if re.search(r"[a-z]", query) else ""


def _order_products(order: dict) -> list[dict]:
    products = order.get("products")
    if isinstance(products, str):
        try:
            products = json.loads(products)
        except ValueError:
            return []
    return [item for item in products if isinstance(item, dict)] if isinstance(products, list) else []


def _date(value) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone(timedelta(hours=7))).strftime("%d/%m/%Y")
    except ValueError:
        return ""


class OrderState(ChatState, total=False):
    order_context: dict
    shipment_context: dict | None
    order_intent: str
    order_selection: str
    order_count: int
    order_list: list[dict]
    order_candidates: list[dict]
    order_product_query: str
    order_product_name: str


class OrderAgent:
    def __init__(self, commerce):
        self.commerce = commerce
        graph = StateGraph(OrderState)
        graph.add_node("load_order", self.load_order)
        graph.add_node("answer_order", self.answer_order)
        graph.add_edge(START, "load_order")
        graph.add_edge("load_order", "answer_order")
        graph.add_edge("answer_order", END)
        self.graph = graph.compile()

    async def load_order(self, state):
        message = _normalize(state.get("message", ""))
        is_return = bool(re.search(r"\b(doi|tra hang|tra lai|tra duoc|hoan tien|hoan hang)\b", message))
        order_word = r"don(?: hang)?"
        is_count = bool(re.search(rf"\b(?:bao nhieu|may|so luong)\s+{order_word}\b", message))
        is_list = bool(
            re.search(rf"\b(?:cac|nhung|tat ca|danh sach|liet ke)\s+{order_word}\b", message)
            or re.search(rf"\b{order_word}\s+(?:khac|cu|truoc|gan day|nao)\b", message)
        )
        intent = "return" if is_return else "count" if is_count else "list" if is_list else "status"
        user_id = str(state.get("authenticated_user_id", "")).strip()
        if not user_id or state.get("actor_role") != "buyer":
            return {"order_intent": intent, "order_selection": "unauthorized"}

        orders = await self.commerce.user_orders(user_id)
        if intent == "count":
            return {"order_intent": intent, "order_selection": "count", "order_count": len(orders)}
        if not orders:
            return {"order_intent": intent, "order_selection": "empty"}
        if intent == "list":
            focused_id = str(state.get("focused_order_id") or "")
            only_other = bool(re.search(rf"\b{order_word}\s+khac\b", message))
            listed = [item for item in orders if not (only_other and str(item.get("id")) == focused_id)]
            return {
                "order_intent": intent,
                "order_selection": "list",
                "order_count": len(listed),
                "order_list": listed[:10],
            }

        requested_id = _order_id(state.get("message", ""))
        product_query = _product_query(state.get("message", "")) if not requested_id else ""
        if requested_id:
            order = next((item for item in orders if str(item.get("id")) == requested_id), None)
            if order is None:
                return {"order_intent": intent, "order_selection": "missing"}
        elif product_query:
            terms = re.findall(r"\w+", product_query)
            matches = []
            for candidate in orders:
                for item in _order_products(candidate):
                    name = str(item.get("productName") or item.get("name") or "")
                    searchable = _normalize(name + " " + str(item.get("variantName") or ""))
                    if name and all(re.search(rf"\b{re.escape(term)}\b", searchable) for term in terms):
                        matches.append({"order": candidate, "product_name": name})
                        break
            if not matches:
                return {"order_intent": intent, "order_selection": "product_missing",
                        "order_product_query": product_query}
            if len(matches) > 1:
                return {"order_intent": intent, "order_selection": "product_ambiguous",
                        "order_product_query": product_query, "order_count": len(matches),
                        "order_candidates": matches[:5]}
            order = matches[0]["order"]
            product_name = matches[0]["product_name"]
        elif state.get("focused_order_id"):
            requested_id = str(state["focused_order_id"])
            order = next((item for item in orders if str(item.get("id")) == requested_id), None)
            if order is None:
                return {"order_intent": intent, "order_selection": "missing"}
        elif intent == "return" and len(orders) > 1:
            return {"order_intent": intent, "order_selection": "ambiguous"}
        else:
            order = orders[0]

        shipment = None
        if intent == "status" and order.get("status") in {"confirmed", "shipped", "delivered"}:
            shipment = await self.commerce.order_shipment(user_id, int(order["id"]))
        return {
            "order_intent": intent,
            "order_selection": "selected",
            "order_context": order,
            "shipment_context": shipment,
            "focused_order_id": str(order["id"]),
            "order_product_name": product_name if product_query else "",
        }

    async def answer_order(self, state):
        selection = state.get("order_selection")
        if selection == "unauthorized":
            answer = "Bạn cần đăng nhập bằng tài khoản người mua để tôi tra cứu đơn hàng của bạn."
        elif selection == "count":
            count = state["order_count"]
            answer = f"Bạn có {count} đơn hàng." if count else "Tài khoản của bạn hiện chưa có đơn hàng nào."
        elif selection == "list":
            count = state["order_count"]
            if not count:
                answer = "Bạn không có đơn hàng nào khác."
            else:
                rows = []
                for order in state["order_list"]:
                    status = ORDER_STATUSES.get(str(order.get("status", "")).lower(), "chưa rõ")
                    created = _date(order.get("created_at"))
                    rows.append(f"#{order['id']}: {status}" + (f", đặt ngày {created}" if created else ""))
                label = "Các đơn hàng còn lại" if "khac" in _normalize(state.get("message", "")) else "Đơn hàng của bạn"
                answer = f"{label} ({count} đơn): " + "; ".join(rows) + "."
                if count > len(rows):
                    answer += " Đây là 10 đơn gần nhất; bạn có thể hỏi theo mã đơn để xem chi tiết."
        elif selection == "empty":
            answer = "Tài khoản của bạn hiện chưa có đơn hàng nào."
        elif selection == "missing":
            answer = "Tôi không tìm thấy mã đơn này trong các đơn hàng của tài khoản bạn. Bạn kiểm tra lại mã đơn nhé."
        elif selection == "product_missing":
            answer = ("Tôi chưa tìm thấy đơn hàng khớp với tên sản phẩm bạn nêu trong tài khoản này. "
                      "Bạn cho tôi tên sản phẩm đầy đủ hơn hoặc mã đơn để kiểm tra nhé.")
        elif selection == "product_ambiguous":
            rows = [f"#{entry['order']['id']} ({entry['product_name']})" for entry in state["order_candidates"]]
            answer = (f"Tôi tìm thấy {state['order_count']} đơn hàng khớp: " + "; ".join(rows) +
                      ". Bạn cho tôi mã đơn muốn kiểm tra nhé.")
        elif selection == "ambiguous":
            answer = "Bạn có nhiều đơn hàng. Vui lòng cho tôi mã đơn (ví dụ: đơn #123) để kiểm tra điều kiện trả hàng."
        else:
            order = state["order_context"]
            order_id = order["id"]
            status = ORDER_STATUSES.get(str(order.get("status", "")).lower(), "chưa rõ")
            if state.get("order_intent") == "return":
                delivered = _date(order.get("delivered_at"))
                if order.get("status") == "delivered":
                    detail = f" Đơn đã giao ngày {delivered}." if delivered else " Đơn đã được giao."
                    answer = (f"Đơn #{order_id} hiện {status}.{detail} Hệ thống cho phép gửi yêu cầu trả hàng/hoàn tiền "
                              "cho đơn đã giao tại trang Đơn hàng; yêu cầu sẽ được xem xét. "
                              "Hiện chưa có quy định thời hạn đổi trả của sàn trong hệ thống, nên tôi chưa thể xác nhận "
                              "đơn này có còn được đổi hay không.")
                else:
                    answer = (f"Đơn #{order_id} hiện {status}. Hệ thống chỉ nhận yêu cầu trả hàng/hoàn tiền "
                              "khi đơn đã giao. Hiện chưa có quy định thời hạn đổi trả của sàn để tôi xác nhận quyền đổi hàng.")
            else:
                parts = [f"Đơn #{order_id} hiện {status}."]
                shipment = state.get("shipment_context")
                if shipment:
                    shipment_status = SHIPMENT_STATUSES.get(str(shipment.get("status", "")).lower())
                    if shipment_status:
                        parts.append(f"Vận chuyển: {shipment_status}.")
                    tracking_code = str(shipment.get("tracking_code") or "")
                    if re.fullmatch(r"[\w-]{1,64}", tracking_code):
                        parts.append(f"Mã vận đơn: {tracking_code}.")
                elif order.get("shipment_tracking_code"):
                    tracking_code = str(order["shipment_tracking_code"])
                    if re.fullmatch(r"[\w-]{1,64}", tracking_code):
                        parts.append(f"Mã vận đơn: {tracking_code}.")
                answer = " ".join(parts)
            if state.get("order_product_name"):
                answer += f" Sản phẩm khớp: {state['order_product_name']}."
        return {"answer": answer, "products": [], "sources": []}
