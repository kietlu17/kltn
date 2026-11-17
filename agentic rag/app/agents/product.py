"""Product agent: customer Q&A over the catalog, shop policies and the web.

It owns every question about products: browsing the catalog, search,
details of one product, comparisons, policy questions and, for the hard
cases the catalog cannot answer, grounded web research. It never touches
the cart or orders; those belong to the order agent.

Ranking is model-first. Hybrid search (dense + BM25) builds the candidate
pool, the local cross-encoder pre-sorts it, and the chat model grades the
short list against the customer's need, which decides the top-k (and the
ambiguous specs) instead of name/keyword rules. The rules stay as the
fallback when the model is unavailable or out of budget.
"""

from __future__ import annotations

import asyncio
import logging
import re

from ..conversation import (
    _RELAX_LABELS,
    _apply_relaxation,
    _focused_references,
    _has_size_chart,
    _next_relaxation,
    _normalized,
    _product_head,
    _soft_context_keys,
    _variant_dimensions,
    _variant_selection,
)
from ..brands import brand_in_text, canonical_brand
from ..rerank import adaptive_top_k
from ..retrieval import _search_terms
from ..memory import resolved_message
from ..schemas import (
    AgentPlan,
    AgentState,
    SearchContext,
    SearchFilters,
    SemanticTask,
    SemanticTurn,
)
from ..specs import (
    canonical_spec_key,
    normalize_specifications,
    requires_semantic_verifier,
    verify_spec_constraints,
)
from ..taxonomy import build_catalog_tree, compact_catalog_tree
from ..visual import InvalidImage

log = logging.getLogger(__name__)

PRODUCT_NODES = ("browse_categories", "retrieve", "relax", "web_expand", "product_detail", "policy")
def _is_brand(name, product_brand, wanted: str) -> bool:
    """True when a listing is of the wanted brand: its brand field or the
    brand its name carries ("iPhone 17" is Apple), else the word in its name."""
    target = canonical_brand(wanted)
    if not target:
        return False
    listed = canonical_brand(str(product_brand or "")) or brand_in_text(str(name or ""))
    if listed:
        return _normalized(listed) == _normalized(target)
    return bool(re.search(
        rf"(?<!\w){re.escape(_normalized(target))}(?!\w)", _normalized(str(name or ""))
    ))


_PRODUCT_INTENTS = {"product_search", "product_detail", "compare_products", "browse_categories", "general"}


class ProductAgent:
    def __init__(
        self,
        settings,
        models_gateway,
        retriever,
        marketplace,
        policy=None,
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

    def register(self, builder, join: str) -> None:
        builder.add_node("browse_categories", self.browse_categories)
        builder.add_node("retrieve", self.retrieve)
        builder.add_node("relax", self.relax_constraints)
        builder.add_node("web_expand", self.web_expand)
        builder.add_node("product_detail", self.product_detail)
        builder.add_node("policy", self.policy_answer)
        # Side branches run next to the main route; the supervisor joins them.
        builder.add_node("policy_side", self.policy_side)
        builder.add_node("research_side", self.research_side)
        builder.add_conditional_edges(
            "retrieve",
            self.route_after_retrieval,
            {"relax": "relax", "web_expand": "web_expand", "collect": join},
        )
        builder.add_edge("relax", "retrieve")
        builder.add_conditional_edges(
            "web_expand",
            lambda state: "retrieve" if state.get("expanded_queries") else "collect",
            {"retrieve": "retrieve", "collect": join},
        )
        for node in ("browse_categories", "product_detail", "policy"):
            builder.add_edge(node, join)

    # -- model helpers ---------------------------------------------------

    def _judge_enabled(self, plan: AgentPlan, image_search: bool) -> bool:
        settings = self.settings
        return (
            getattr(settings, "llm_first", False)
            and getattr(settings, "rerank_mode", "cross_encoder") == "llm"
            and hasattr(self.models, "rank_candidates")
            and not image_search
            and not plan.product_ids
        )

    def _web_enabled(self) -> bool:
        return bool(getattr(self.settings, "web_search_enabled", False)) and hasattr(
            self.models, "web_research"
        )

    @staticmethod
    def _need(state: AgentState) -> str:
        """The customer's need as the semantic model phrased it, else the query."""
        raw = state.get("semantic_turn")
        if raw:
            turn = SemanticTurn.model_validate(raw)
            task = next((item for item in turn.tasks if item.intent == "product_search"), None)
            if task and task.query.strip():
                return task.query.strip()[:500]
        return str(state.get("query") or resolved_message(state))[:500]

    async def _research(self, question: str) -> dict | None:
        if not self._web_enabled() or not question.strip():
            return None
        try:
            research = await self.models.web_research(question)
        except Exception as error:
            log.warning("web research failed: %s: %s", type(error).__name__, str(error)[:200])
            return None
        return research.model_dump()

    async def _judge(
        self,
        state: AgentState,
        plan: AgentPlan,
        products: list[dict],
        verification: list[dict],
        needs_semantic_verifier: bool,
    ) -> tuple[list[dict], list[dict], list[dict], bool] | None:
        """Grade the short list with the chat model.

        Returns (products, verification, ranking, partial) or None when the
        model is unavailable, so the caller falls back to the rule path.
        """
        need = self._need(state)
        candidates = products
        if self.reranker and plan.sort_by == "relevance" and len(products) > 1:
            # Cheap local pre-sort: the model reads the most promising ones.
            candidates = await self.reranker.rerank(need, products)
        window = candidates[: getattr(self.settings, "llm_rerank_candidates", 10)]
        hard_specs = [item for item in plan.filters.spec_constraints if item.strength == "hard"]
        constraints = (
            [item.model_dump() for item in plan.filters.spec_constraints]
            if needs_semantic_verifier
            else []
        )
        try:
            ranking = await self.models.rank_candidates(need, constraints, window)
        except Exception as error:
            log.warning("LLM rank failed, using rule ranking: %s: %s", type(error).__name__, str(error)[:200])
            return None
        deterministic = {str(item.get("productId")): item.get("verdict") for item in verification}
        by_index = {item.index: item for item in ranking.results}
        judged = []
        for position, product in enumerate(window, 1):
            result = by_index.get(position)
            if result is None or result.relevance == 0:
                continue
            product_id = str(product.get("id"))
            if (
                constraints
                and hard_specs
                and result.verdict != "match"
                and deterministic.get(product_id) != "match"
            ):
                # A hard spec must be proven, by the catalog or the model.
                continue
            judged.append((result, position, product))
        if plan.sort_by == "relevance":
            judged.sort(key=lambda item: (-item[0].relevance, item[1]))
        strong = [item for item in judged if item[0].relevance >= 2]
        partial = bool(judged) and not strong
        chosen = strong or judged
        if constraints:
            judged_ids = {str(product.get("id")) for _result, _position, product in judged}
            verification = [
                item for item in verification if str(item.get("productId")) not in judged_ids
            ] + [
                {
                    "productId": product.get("id"),
                    "verdict": result.verdict,
                    "evidence": list(result.evidence),
                    "reason": result.reason,
                }
                for result, _position, product in judged
            ]
        ranked_products = [
            {**product, "relevance": result.relevance, "matchReason": result.reason}
            for result, _position, product in chosen
        ]
        ranking_summary = [
            {"name": product.get("name"), "relevance": result.relevance, "reason": result.reason}
            for result, _position, product in chosen
        ]
        return ranked_products, verification, ranking_summary, partial

    async def _search_expanded(self, queries: list[str], plan: AgentPlan, limit: int) -> list[dict]:
        """Catalog search for the product kinds web research suggested,
        interleaved by rank and deduplicated by product."""
        results = await asyncio.gather(
            *(
                self.retriever.search(query, plan.filters, limit=limit, sort_by=plan.sort_by)
                for query in queries[:3]
            ),
            return_exceptions=True,
        )
        lists = [result for result in results if isinstance(result, list)]
        merged: list[dict] = []
        seen: set[str] = set()
        for rank in range(max((len(items) for items in lists), default=0)):
            for items in lists:
                if rank < len(items):
                    hit = items[rank]
                    product_id = str(hit.get("productId") or "")
                    if product_id and product_id not in seen:
                        seen.add(product_id)
                        merged.append(hit)
        return merged[:limit]

    # -- nodes -----------------------------------------------------------

    @staticmethod
    def _asked_brands(plan: AgentPlan, state: AgentState) -> list[str]:
        """Brands the customer named this turn: the brand filter, and brands
        the model listed as a constraint ("JBL với Sony"). Read from the
        semantic turn too, since relaxing may already have dropped the filter."""
        constraints = list(plan.filters.spec_constraints)
        raw = state.get("semantic_turn")
        if raw:
            for task in SemanticTurn.model_validate(raw).tasks:
                constraints.extend(task.constraints)
        brands = [plan.filters.brand] if plan.filters.brand else []
        for item in constraints:
            if item.key.casefold() == "brand":
                values = item.value if isinstance(item.value, list) else [item.value]
                brands.extend(str(value) for value in values)
        seen: dict[str, str] = {}
        for brand in brands:
            key = _normalized(str(brand)).strip()
            if key and key not in seen:
                seen[key] = str(brand).strip()
        return list(seen.values())[:3]

    async def _brand_availability(self, plan: AgentPlan, products: list[dict], state: AgentState) -> dict:
        """For each brand asked about but missing from the results, what the
        catalog has of it in the same kind of product. Missing from a ranked
        top-k is not "the shop does not sell it"."""
        availability: dict[str, list[dict]] = {}
        kind = plan.filters.product_type or plan.filters.category_path or ""
        for brand in self._asked_brands(plan, state):
            if re.search(r"(?:cung|khac) hang|thuong hieu", _normalized(brand)):
                continue
            def carries(name: str, product_brand, brand=brand) -> bool:
                return _is_brand(name, product_brand, brand)

            if any(carries(str(item.get("name") or ""), item.get("brand")) for item in products):
                continue
            try:
                hits = await self.retriever.search(
                    f"{kind} {brand}".strip(),
                    SearchFilters(category_ids=plan.filters.category_ids),
                    limit=30,
                )
            except Exception as error:
                log.warning("brand lookup failed: %s: %s", type(error).__name__, str(error)[:200])
                continue
            found = []
            for hit in hits:
                payload = hit.get("payload") or {}
                title = str(payload.get("text") or "").splitlines()[0] if payload.get("text") else ""
                title = title.split(":", 1)[1].strip() if title.startswith("Tên sản phẩm:") else title.strip()
                if title and carries(title, payload.get("brand")):
                    found.append({"name": title, "price": payload.get("minPrice")})
            found.sort(key=lambda item: float(item.get("price") or 0))
            availability[brand] = found[:6]
        return availability

    async def retrieve(self, state: AgentState) -> dict:
        plan = AgentPlan.model_validate(state["plan"])
        image = str((state.get("request") or {}).get("image") or "")
        visual = getattr(self, "visual", None)
        reranker = getattr(self, "reranker", None)
        image_search = bool(image and visual and not plan.product_ids)
        expanded = [query for query in (state.get("expanded_queries") or []) if str(query).strip()]
        search_limit = max(
            self.settings.retrieval_limit,
            plan.result_limit or self.settings.result_limit,
        )
        if plan.product_ids:
            hits = [
                {"productId": product_id, "vectorScore": None, "sources": ["conversation"]}
                for product_id in plan.product_ids
            ]
        elif image_search:
            try:
                hits = await visual.search(image, search_limit)
            except InvalidImage as error:
                return {"route": "product_search", "products": [], "retrieval_rounds": self.settings.max_retrieval_rounds,
                        "tool_result": {"error": str(error)}}
            except Exception as error:
                log.warning("Image search failed: %s: %s", type(error).__name__, str(error)[:200])
                return {"route": "product_search", "products": [], "retrieval_rounds": self.settings.max_retrieval_rounds,
                        "tool_result": {"error": "Tìm bằng hình ảnh đang tạm gián đoạn, bạn thử mô tả sản phẩm bằng chữ nhé."}}
        elif expanded:
            hits = await self._search_expanded(expanded, plan, search_limit)
        else:
            hits = await self.retriever.search(
                state["query"],
                plan.filters,
                limit=search_limit,
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
        brand = _normalized(plan.filters.brand or "").strip()
        if brand and not plan.product_ids:
            # Brands missing from the facet vocabulary are dropped from the
            # Qdrant filter, so "tai nghe sony" would list any headphones.
            # Relaxation removes the brand, and says so, if none is left.
            products = [
                product for product in products
                if _is_brand(product.get("name"), product.get("brand"), plan.filters.brand)
            ]
        verification: list[dict] = []
        warnings = list(state.get("warnings", []))
        needs_semantic_verifier = False
        if plan.filters.spec_constraints:
            needs_semantic_verifier = requires_semantic_verifier(
                plan.filters.spec_constraints
            )
            verdicts = {
                str(product.get("id")): verify_spec_constraints(
                    product, plan.filters.spec_constraints
                )
                for product in products
            }
            if any(item.verdict == "unknown" for item in verdicts.values()) and any(
                item.strength == "hard" for item in plan.filters.spec_constraints
            ):
                # Most listings carry no structured spec ("16GB" sits in the
                # name or description): let the model read them instead of
                # dropping every product and answering "nothing found".
                needs_semantic_verifier = True
            grounded_products: list[dict] = []
            for product in products:
                verdict = verdicts[str(product.get("id"))]
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

        ranking: list[dict] = []
        partial_match = False
        judged = None
        if products and self._judge_enabled(plan, image_search):
            judged = await self._judge(state, plan, products, verification, needs_semantic_verifier)
            if judged is None:
                warnings.append("RANK_FALLBACK")
        if judged is not None:
            products, verification, ranking, partial_match = judged
            warnings.append("LLM_RANKED")
        else:
            products, verification, reranked = await self._rule_ranking(
                state, plan, products, verification, needs_semantic_verifier,
                image_search, bool(expanded), warnings,
            )
        referenced_ids = list(plan.product_ids)
        if not referenced_ids:
            # Name matching only backs up the rule path: when the model judged
            # the list, a named product already came back as a reference.
            named_products = [] if judged is not None else _focused_references(
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
            elif judged is None and reranked:
                products = adaptive_top_k(
                    products,
                    requested_limit,
                    getattr(self.settings, "rerank_relative_cutoff", 0.3),
                )
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
        shown = {str(product.get("name")) for product in products}
        brand_availability: dict = {}
        final_round = (
            bool(products)
            or rounds >= self.settings.max_retrieval_rounds
            or not _next_relaxation(plan.filters, search_context.relaxed_keys)
        )
        if not plan.product_ids and final_round:
            brand_availability = await self._brand_availability(plan, products, state)
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
                "ranking": [item for item in ranking if str(item.get("name")) in shown],
                "partialMatch": partial_match,
                "expandedQueries": expanded,
                # brand -> catalog listings of it (cheapest first); [] means
                # the catalog has none of that kind. Only brands asked about
                # and missing from products are checked.
                **({"brandAvailability": brand_availability} if brand_availability else {}),
            },
        }

    async def _rule_ranking(
        self,
        state: AgentState,
        plan: AgentPlan,
        products: list[dict],
        verification: list[dict],
        needs_semantic_verifier: bool,
        image_search: bool,
        expanded: bool,
        warnings: list[str],
    ) -> tuple[list[dict], list[dict], bool]:
        """Fallback ranking without the LLM judge: product-kind checks on
        names, the spec verifier and the cross-encoder."""
        reranker = getattr(self, "reranker", None)
        semantic_scope_constraint: dict | None = None
        raw_turn = state.get("semantic_turn")
        # A photo search has no product words to check names against, and an
        # expanded search looks for other kinds than the words of the query.
        if raw_turn and not plan.product_ids and not image_search and not expanded:
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
        head = "" if image_search or expanded else _product_head(plan.filters.product_type or "")
        relaxed_keys = SearchContext.model_validate(state.get("search_context") or {}).relaxed_keys
        if not head and not image_search and not expanded and "spec.hard" in relaxed_keys:
            # Once even the hard specs are dropped, nearest neighbours of a
            # product the catalog lacks are unrelated ("sạc dự phòng" ->
            # "áo phông"): keep only names that start the same way.
            phrase = plan.filters.product_type or state.get("query") or ""
            head = next(iter(re.findall(r"[a-z]{2,}", _normalized(phrase))), "")
        if (
            products
            and head
            and not (plan.filters.category_ids or plan.filters.category_id or plan.filters.category_path)
        ):
            # No category matched the phrase, so nothing scoped the search to
            # the product kind: "nồi chiên" must not return "dầu thơm".
            products = [
                product for product in products
                if re.search(rf"(?<!\w){re.escape(head)}(?!\w)", _normalized(str(product.get("name") or "")))
            ]
        if products and semantic_scope_constraint and not needs_semantic_verifier:
            # Scope alone is checked against product names: hybrid search has
            # already ranked by relevance, a model call here only adds latency.
            query_terms = set(_search_terms(str(semantic_scope_constraint["value"])))
            products = [
                product
                for product in products
                if query_terms & set(_search_terms(str(product.get("name") or "")))
            ]
            semantic_scope_constraint = None
        if products and needs_semantic_verifier:
            verifier_constraints = [
                item.model_dump() for item in plan.filters.spec_constraints
            ]
            if semantic_scope_constraint:
                verifier_constraints.append(semantic_scope_constraint)
            # Products whose specs already matched deterministically skip the
            # model; only the undecided ones are sent.
            deterministic_match = {
                str(item.get("productId"))
                for item in verification
                if item.get("verdict") == "match"
            } if not semantic_scope_constraint else set()
            undecided = [
                product for product in products
                if str(product.get("id")) not in deterministic_match
            ]
            try:
                checked = (
                    await self.models.verify_candidates(
                        state["query"], verifier_constraints, undecided
                    )
                    if undecided
                    else None
                )
                by_id = {item.productId: item for item in (checked.results if checked else [])}
                products = [
                    product
                    for product in products
                    if str(product.get("id")) in deterministic_match
                    or (
                        by_id.get(str(product.get("id")))
                        and by_id[str(product.get("id"))].verdict == "match"
                    )
                ]
                if checked:
                    verified = {item.productId for item in checked.results}
                    verification = [
                        item for item in verification
                        if str(item.get("productId")) not in verified
                    ] + [item.model_dump() for item in checked.results]
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
        reranked = False
        if (
            products
            and reranker
            and not image_search
            and not plan.product_ids
            and plan.sort_by == "relevance"
            and getattr(self.settings, "rerank_mode", "cross_encoder") != "off"
        ):
            # Second stage: the cross-encoder reads query and product together
            # and decides which candidates make the top-k.
            products = await reranker.rerank(self._need(state), products)
            reranked = True
        return products, verification, reranked

    def route_after_retrieval(self, state: AgentState) -> str:
        if state.get("products"):
            return "collect"
        plan = AgentPlan.model_validate(state["plan"])
        context = SearchContext.model_validate(state.get("search_context") or {})
        if int(state.get("retrieval_rounds", 0)) < self.settings.max_retrieval_rounds and (
            (context.mode == "similar" and _soft_context_keys(context))
            or _next_relaxation(plan.filters, context.relaxed_keys)
        ):
            return "relax"
        # Hard case: the catalog has nothing even after relaxing. Web research
        # may name the product kinds the catalog uses for this need.
        if (
            self._web_enabled()
            and getattr(self.settings, "llm_first", False)
            and not plan.product_ids
            and not (state.get("request") or {}).get("image")
            and "WEB_EXPANDED" not in (state.get("warnings") or [])
            and not (state.get("tool_result") or {}).get("error")
        ):
            return "web_expand"
        # Retrying the same query with the same filters cannot change the result.
        return "collect"

    async def web_expand(self, state: AgentState) -> dict:
        """Turn a need the catalog does not name into catalog product kinds."""
        research = dict(state.get("web_research") or {})
        if not research.get("catalog_queries"):
            research = await self._research(
                f"Nên tìm mua loại sản phẩm nào cho nhu cầu: {self._need(state)}"
            ) or research
        queries = [str(query) for query in research.get("catalog_queries") or [] if str(query).strip()][:3]
        plan = AgentPlan.model_validate(state["plan"])
        # The suggested kinds replace the original kind; budget and audience stay.
        plan.filters = SearchFilters(
            min_price=plan.filters.min_price,
            max_price=plan.filters.max_price,
            audience=plan.filters.audience,
            exclude_product_ids=plan.filters.exclude_product_ids,
        )
        return {
            "plan": plan.model_dump(),
            "web_research": research,
            "expanded_queries": queries,
            "warnings": [*state.get("warnings", []), "WEB_EXPANDED"],
        }

    async def research_side(self, state: AgentState) -> dict:
        """Web research the semantic model asked for, next to the main route."""
        raw = state.get("semantic_turn")
        if not raw or state.get("route") in {"resolve_pending", "policy"}:
            return {}
        turn = SemanticTurn.model_validate(raw)
        task = next(
            (item for item in turn.tasks if item.web_research and item.intent in _PRODUCT_INTENTS),
            None,
        )
        if not task:
            return {}
        research = await self._research(
            task.research_query or task.query or resolved_message(state)
        )
        return {"web_research": research} if research else {}

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
        result = {
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
        task = self._detail_task(state)
        if card and task and not task.web_research and getattr(self.settings, "llm_first", False):
            # The listing lacks what was asked ("Woburn III có mấy màu"): look
            # it up instead of answering "chưa có thông tin". research_side
            # only writes when the model already asked for research.
            missing = self._missing_attributes(task.requested_attributes, card)
            if missing:
                research = await self._research(f"{card.get('name', '')} {' '.join(missing)}")
                if research:
                    result["web_research"] = research
                    result["tool_result"]["missingInCatalog"] = missing
        return result

    @staticmethod
    def _detail_task(state: AgentState) -> SemanticTask | None:
        raw = state.get("semantic_turn")
        if not raw:
            return None
        turn = SemanticTurn.model_validate(raw)
        return next((item for item in turn.tasks if item.intent == "product_detail"), None)

    @staticmethod
    def _missing_attributes(requested: list[str], card: dict) -> list[str]:
        """Requested attributes the listing has no data for, as search words."""
        facts = normalize_specifications(card.get("specifications") or [])
        keys = {fact.get("key") for fact in facts}
        missing: list[str] = []
        for attribute in requested:
            if attribute in {"price", "stock", "specification", "size", "fit", "reviews", "rating"}:
                # Reviews come from the shop's buyers, never from the web.
                continue
            if attribute == "color":
                # A product without variants gets one id-less stand-in offer.
                real_variants = [item for item in card.get("variants") or [] if item.get("id")]
                if not real_variants and not any(
                    "mau" in _normalized(str(fact.get("rawName") or "")) for fact in facts
                ):
                    missing.append("màu sắc")
                continue
            if canonical_spec_key(attribute) not in keys:
                missing.append(attribute.replace("_", " "))
        return missing[:3]

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
            # A model that answers without "[Nguồn n]" still answered from
            # these documents: show them rather than no source at all.
            return answer, cited_sources or sources[:3]
        except Exception:
            excerpt = str(context[0].get("text") or "")[:900]
            return f"Theo tài liệu đã truy xuất: {excerpt} [Nguồn {context[0]['number']}]", sources

    async def policy_answer(self, state: AgentState) -> dict:
        answer, sources = await self._policy_result(
            state.get("query") or resolved_message(state)
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
        if not raw or state.get("route") == "policy":
            return {}
        turn = SemanticTurn.model_validate(raw)
        task = next((item for item in turn.tasks if item.intent == "policy"), None)
        if not task:
            return {}
        answer, sources = await self._policy_result(
            task.query or resolved_message(state)
        )
        return {"policy_appendix": answer, "policy_sources": sources}

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
            if {"reviews", "rating"} & set(requested):
                # The answer model summarises what buyers wrote.
                return None
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
            missing = False
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
                    missing = True
            if not answers:
                # No structured spec ("chống ồn" usually lives in the
                # description): let the answer model read the product
                # instead of printing an internal key such as
                # "noise_cancellation".
                return None
            note = " Các thông tin còn lại chưa có trong thông số của sản phẩm." if missing else ""
            return f"{product.get('name', 'Sản phẩm')}: " + "; ".join(answers) + "." + note
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
