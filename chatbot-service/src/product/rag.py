"""LangChain retrieval pipeline for fresh, grounded product candidates."""
import logging
import math
import os

from langchain_core.runnables import RunnableLambda

from .catalog import eligible_cards, product_document

log = logging.getLogger(__name__)


class ProductRAG:
    """LCEL retrieval pipeline combining text RAG and direct image retrieval."""

    def __init__(self, api, models, vectors, visual=None):
        self.api = api
        self.models = models
        self.vectors = vectors
        self.visual = visual
        self.candidate_pool = max(6, min(100, int(os.getenv("CHATBOT_RERANK_CANDIDATES", "30"))))
        self.bayesian_prior_weight = max(1.0, float(os.getenv("CHATBOT_RERANK_BAYESIAN_PRIOR", "20")))
        self.chain = RunnableLambda(self.retrieve).with_config(run_name="product_rag")

    async def _fresh_cards(self, ordered_ids, plan, *, exclude=None):
        products, stock = [], {}
        for start in range(0, len(ordered_ids), 200):
            fresh, inventory = await self.api.fresh(ordered_ids[start:start + 200])
            products.extend(fresh)
            stock.update(inventory)
        return eligible_cards(products, stock, ordered_ids, plan, exclude=exclude)

    async def _rerank(self, cards, relevance):
        """Blend semantic relevance with Bayesian review quality and popularity."""
        if not cards:
            return []
        try:
            response = await self.api.review_summaries([card["id"] for card in cards])
            response = response if isinstance(response, dict) else {}
        except Exception as error:
            log.warning("Review summaries unavailable; reranking without review signals: %s", error)
            response = {}

        summaries = {
            str(item.get("productId")): item
            for item in response.get("items", [])
            if isinstance(item, dict) and item.get("productId")
        }
        try:
            global_average = float(response.get("globalAverageRating") or 4.0)
        except (TypeError, ValueError):
            global_average = 4.0
        global_average = min(5.0, max(1.0, global_average))

        raw_relevance = []
        for index, card in enumerate(cards):
            try:
                score = float(relevance.get(card["id"], 0.0))
            except (TypeError, ValueError):
                score = 0.0
            raw_relevance.append(score if math.isfinite(score) and score > 0 else 1 / (60 + index + 1))
        max_relevance = max(raw_relevance, default=1.0) or 1.0
        max_reviews = max(
            (max(0, int(summaries.get(card["id"], {}).get("reviewCount", 0) or 0)) for card in cards),
            default=0,
        )
        max_sold = max((max(0, int(card.get("sold", 0) or 0)) for card in cards), default=0)

        ranked = []
        for index, (card, semantic_raw) in enumerate(zip(cards, raw_relevance)):
            summary = summaries.get(card["id"], {})
            try:
                review_count = max(0, int(summary.get("reviewCount", 0) or 0))
                average_rating = float(summary.get("averageRating") or global_average)
            except (TypeError, ValueError):
                review_count, average_rating = 0, global_average
            average_rating = min(5.0, max(1.0, average_rating))
            bayesian_rating = (
                review_count * average_rating + self.bayesian_prior_weight * global_average
            ) / (review_count + self.bayesian_prior_weight)
            semantic_score = semantic_raw / max_relevance
            review_popularity = math.log1p(review_count) / math.log1p(max_reviews) if max_reviews else 0.0
            sold = max(0, int(card.get("sold", 0) or 0))
            sold_popularity = math.log1p(sold) / math.log1p(max_sold) if max_sold else 0.0
            final_score = (
                0.60 * semantic_score
                + 0.20 * (bayesian_rating / 5.0)
                + 0.10 * review_popularity
                + 0.10 * sold_popularity
            )
            enriched = {
                **card,
                "averageRating": round(average_rating, 2) if review_count else None,
                "reviewCount": review_count,
                "sold": sold,
            }
            ranked.append((final_score, -index, enriched))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in ranked]

    async def _text_candidates(self, state):
        plan = state["plan"]
        reference = plan.get("reference_product_id") if plan["intent"] == "similar" else None
        query = plan["query"] or state["message"] or state.get("visual_description", "")
        category = None
        if reference:
            source = await self.api.product(reference)
            if not source:
                return {"products": [], "answer": "Sản phẩm tham chiếu hiện không còn hiển thị. Bạn chọn sản phẩm khác nhé."}
            category = str(source.get("categoryId") or "")
            query = product_document(source).page_content + "\nYêu cầu: " + query
        if not query.strip():
            return {"products": [], "answer": "Bạn muốn tìm sản phẩm nào?"}

        queries = [query[:10000]]
        if reference:
            for caption in await self.vectors.source_visuals(reference):
                queries.append((caption + "\nYêu cầu: " + plan["query"])[:3000])
        if state.get("visual_description"):
            queries.append((state["visual_description"] + "\nYêu cầu: " + plan["query"])[:3000])

        embeddings = await self.models.embed_queries(queries)
        ranks = {}
        cards = []
        for offset in (0, 80, 160):
            for index, vector in enumerate(embeddings):
                hits = await self.vectors.query(
                    vector,
                    kind="image_description" if index else "text",
                    exclude=reference,
                    category=category,
                    offset=offset,
                )
                seen = set()
                for rank, hit in enumerate(hits, offset + 1):
                    product_id = hit.payload["productId"]
                    if product_id in seen:
                        continue
                    seen.add(product_id)
                    ranks[product_id] = ranks.get(product_id, 0) + 1 / (60 + rank)
            ordered_ids = sorted(ranks, key=ranks.get, reverse=True)
            cards = await self._fresh_cards(ordered_ids, plan, exclude=reference)
            if len(cards) >= self.candidate_pool:
                break
        cards = await self._rerank(cards[:self.candidate_pool], ranks)
        return {"products": cards[:6]}

    async def retrieve(self, state):
        direct_image = state.get("visual_only", False)
        result = {"products": []} if direct_image else await self._text_candidates(state)
        result.update(rounds=state.get("rounds", 0) + 1, retrieval_mode="text")
        if direct_image and not self.visual:
            raise RuntimeError("Direct image search is unavailable")
        if not self.visual or result.get("answer"):
            return result

        plan = state["plan"]
        reference = plan.get("reference_product_id") if plan["intent"] == "similar" else None
        image_vector = state.get("image_vector") if (
            state.get("image_namespace") == self.visual.collection
            and (state.get("image") or plan.get("use_previous_image"))
        ) else None
        try:
            if state.get("image") and not image_vector:
                image_vector = await self.visual.embed(state["image"])
            image_vectors = [image_vector] if image_vector else []
            category = None
            if reference:
                source = await self.api.product(reference)
                if source:
                    category = str(source.get("categoryId") or "")
                    image_vectors.extend(await self.visual.source_vectors(reference))
            if not image_vectors:
                return {**result, "image_vector": [], "image_namespace": ""}
            if not await self.visual.exists():
                if direct_image:
                    raise RuntimeError("Image index is not ready")
                return {**result, "warnings": ["Chỉ mục ảnh đang được chuẩn bị; đang tìm bằng mô tả."]}

            ranks = {product["id"]: 1 / (60 + rank) for rank, product in enumerate(result["products"], 1)}
            visual_ranks = {}
            for vector in image_vectors:
                hits = await self.visual.query(vector, exclude=reference, category=category)
                for rank, hit in enumerate(hits, 1):
                    product_id = hit.payload["productId"]
                    # One best image per product avoids favoring products with more photos.
                    visual_ranks[product_id] = max(visual_ranks.get(product_id, 0), 2 / (60 + rank))
            for product_id, score in visual_ranks.items():
                ranks[product_id] = ranks.get(product_id, 0) + score
            ordered_ids = sorted(ranks, key=ranks.get, reverse=True)
            cards = await self._fresh_cards(ordered_ids, plan, exclude=reference)
            cards = await self._rerank(cards[:self.candidate_pool], ranks)
            return {
                **result,
                "products": cards[:6],
                "image_vector": image_vector or [],
                "image_namespace": self.visual.collection,
                "retrieval_mode": "image_vector" if direct_image else "text_and_image_vector",
            }
        except Exception:
            if direct_image:
                raise
            log.exception("Visual retrieval unavailable; preserving text retrieval")
            return {**result, "warnings": ["Tìm kiếm ảnh trực tiếp tạm thời lỗi; đang dùng kết quả theo mô tả."]}
