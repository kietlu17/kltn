"""Top-level LangGraph router for domain agents."""
from typing import Annotated, Literal

from langgraph.channels import UntrackedValue
from langgraph.graph import END, START, StateGraph

from .intent import understand_intent
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
        intent = await understand_intent(getattr(self.product_agent, "models", None), state)
        route = "product" if intent.commerce_intent or intent.browse_catalog else intent.route
        if route == "order" and not self.order_agent:
            route = "product"
        if route == "customer_service" and not self.customer_service_agent:
            route = "product"
        return {"route_name": route, "turn_understanding": intent.model_dump()}

    @staticmethod
    def next_agent(state):
        return state["route_name"]
