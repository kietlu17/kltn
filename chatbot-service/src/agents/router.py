"""Top-level LangGraph router for domain agents."""
import re
import unicodedata
from typing import Literal

from langgraph.graph import END, START, StateGraph

from .product import ProductAgent, ProductState


class RouterState(ProductState, total=False):
    route_name: Literal["product", "customer_service"]
    policy_context: list[dict]
    sources: list[dict]


class RouterAgent:
    """Supervisor graph whose first registered domain node is ProductAgent."""

    def __init__(self, product_agent: ProductAgent, customer_service_agent=None):
        self.product_agent = product_agent
        self.customer_service_agent = customer_service_agent
        graph = StateGraph(RouterState)
        graph.add_node("route", self.route)
        # ProductAgent is a real subgraph node and shares the router state.
        graph.add_node("product_agent", product_agent.graph)
        routes = {"product": "product_agent"}
        if customer_service_agent:
            graph.add_node("customer_service_agent", customer_service_agent.graph)
            routes["customer_service"] = "customer_service_agent"
        graph.add_edge(START, "route")
        graph.add_conditional_edges("route", self.next_agent, routes)
        graph.add_edge("product_agent", END)
        if customer_service_agent:
            graph.add_edge("customer_service_agent", END)
        self.graph = graph.compile()

    async def route(self, state):
        if self.customer_service_agent and self._is_customer_service(state.get("message", "")):
            return {"route_name": "customer_service"}
        return {"route_name": "product"}

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
