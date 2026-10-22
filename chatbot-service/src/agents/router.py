"""Top-level LangGraph router for domain agents."""
import re
import unicodedata
from typing import Annotated, Literal

from langgraph.channels import UntrackedValue
from langgraph.graph import END, START, StateGraph

from .product import ProductAgent, ProductState


class RouterState(ProductState, total=False):
    route_name: Literal["product", "customer_service", "order"]
    policy_context: Annotated[list[dict], UntrackedValue(list)]
    sources: Annotated[list[dict], UntrackedValue(list)]


class RouterAgent:
    """Supervisor graph that dispatches requests to domain subgraphs."""

    def __init__(self, product_agent: ProductAgent, customer_service_agent=None, order_agent=None,
                 checkpointer=None):
        self.product_agent = product_agent
        self.customer_service_agent = customer_service_agent
        self.order_agent = order_agent
        graph = StateGraph(RouterState)
        graph.add_node("plan", self.route)
        # ProductAgent is a real subgraph node and shares the router state.
        graph.add_node("product_agent", product_agent.graph)
        routes = {"product": "product_agent"}
        if customer_service_agent:
            graph.add_node("customer_service_agent", customer_service_agent.graph)
            routes["customer_service"] = "customer_service_agent"
        if order_agent:
            graph.add_node("order_agent", order_agent.graph)
            routes["order"] = "order_agent"
        graph.add_edge(START, "plan")
        graph.add_conditional_edges("plan", self.next_agent, routes)
        graph.add_edge("product_agent", END)
        if customer_service_agent:
            graph.add_edge("customer_service_agent", END)
        if order_agent:
            graph.add_edge("order_agent", END)
        self.graph = graph.compile(checkpointer=checkpointer)

    async def route(self, state):
        if self.order_agent and self._is_order(state.get("message", "")):
            return {"route_name": "order"}
        if self.customer_service_agent and self._is_customer_service(state.get("message", "")):
            return {"route_name": "customer_service"}
        return {"route_name": "product"}

    @staticmethod
    def _is_order(message):
        text = unicodedata.normalize("NFD", message.casefold()).replace("đ", "d")
        text = "".join(char for char in text if not unicodedata.combining(char))
        text = re.sub(r"\s+", " ", text).strip()
        order_word = r"don(?: hang)?"
        if re.match(rf"^{order_word}\b(?!\s+(?:gian|vi|sac|dieu)\b)", text):
            return True
        if re.search(rf"\b(?:bao nhieu|may|so luong)\s+{order_word}\b", text):
            return True
        if re.search(rf"\b(?:cac|nhung|tat ca|danh sach|liet ke)\s+{order_word}\b", text):
            return True
        if re.search(rf"\b{order_word}\s+(?:khac|cu|truoc|gan day|nao)\b", text):
            return True
        if re.search(r"\b(don hang|don)\s*(?:#\s*\d+|cua toi|cua minh|nay|do)\b", text):
            return True
        if re.search(r"\b(ma van don|theo doi don|kiem tra don|don hang.*(?:o dau|den dau|toi dau|trang thai))\b", text):
            return True
        personal = re.search(r"\b(toi|minh|em)\b", text)
        purchased = re.search(r"\b(da mua|mua duoc|mua dc|nhan hang|da nhan)\b", text)
        return bool(personal and purchased and re.search(r"\b(doi|tra|hoan tien)\b", text))

    @staticmethod
    def _is_customer_service(message):
        text = unicodedata.normalize("NFD", message.casefold()).replace("đ", "d")
        text = "".join(char for char in text if not unicodedata.combining(char))
        phrases = (
            "chinh sach", "bao mat", "du lieu ca nhan", "quyen rieng tu", "cookie",
            "dieu khoan", "khieu nai", "khieu kieu", "hoan tien", "doi tra",
            "tra hang", "bao hanh", "van chuyen", "giao hang", "tai khoan",
            "cham soc khach hang", "ho tro khach hang",
        )
        return any(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text) for phrase in phrases)

    @staticmethod
    def next_agent(state):
        return state["route_name"]
