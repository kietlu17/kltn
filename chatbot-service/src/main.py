import asyncio
import base64
import binascii
import json
import logging
import os
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import FastAPI, HTTPException, Path as ApiPath, Query, Request
from pydantic import BaseModel, Field, ValidationError, model_validator
from qdrant_client.http.exceptions import UnexpectedResponse

from .agents.product import ProductAgent
from .agents.router import RouterAgent
from .agents.state import SearchPlan
from .agents.commerce import resolve_product_reference, resolve_product_references
from .agents.safety import clean_untrusted_text, is_prompt_injection
from .api.speech import router as speech_router
from .core.settings import Settings
from .infrastructure.clients import CatalogAPI, CommerceAPI, normalize_image
from .infrastructure.models import ModelClients
from .policy.agent import CustomerServiceAgent
from .policy.catalog import PolicyCatalog
from .product.catalog import VectorCatalog
from .product.visual import VisualCatalog

log = logging.getLogger(__name__)


def session_product(product: dict) -> dict:
    """Keep card fields needed by follow-up turns without storing unbounded catalog payloads."""
    fields = (
        "id", "name", "price", "imageUrl", "shopId", "url", "sold",
        "description", "detail", "variants", "averageRating", "reviewCount",
    )
    return {key: product[key] for key in fields if key in product}


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def compact_history(history: list[dict]) -> list[dict]:
    """Keep the newest safe messages within both count and character budgets."""
    message_limit = _bounded_env_int("CHATBOT_CONTEXT_HISTORY_MESSAGES", 8, 2, 20)
    character_limit = _bounded_env_int("CHATBOT_CONTEXT_HISTORY_CHARS", 6000, 1000, 20000)
    selected = []
    remaining = character_limit
    for item in reversed((history or [])[-message_limit:]):
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            continue
        content = clean_untrusted_text(item.get("content", ""), min(1000, remaining))
        if not content or is_prompt_injection(content):
            continue
        selected.append({"role": item["role"], "content": content})
        remaining -= len(content)
        if remaining <= 0:
            break
    return list(reversed(selected))


def compact_session_products(products: list[dict]) -> list[dict]:
    """Store only stable card identity needed for follow-up references."""
    limit = _bounded_env_int("CHATBOT_SESSION_PRODUCT_LIMIT", 6, 1, 12)
    fields = ("id", "name", "price", "imageUrl", "shopId")
    compact = []
    for rank, product in enumerate((products or [])[:limit], 1):
        if not isinstance(product, dict) or not product.get("id"):
            continue
        item = {key: product[key] for key in fields if key in product}
        item["displayRank"] = rank
        compact.append(item)
    return compact


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=2000)
    image: str | None = Field(default=None, max_length=7_000_000)
    sessionId: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{43}$")
    referenceProductId: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{24}$")
    variantId: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{24}$")
    addressId: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{24}$")
    paymentMethod: Literal["cod", "wallet", "bank_transfer"] | None = None
    voucherCode: str | None = Field(default=None, max_length=40)
    actionRequestId: str | None = Field(default=None, pattern=r"^[A-Za-z0-9:_-]{8,128}$")
    confirmActionId: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9:_-]{8,128}$"
    )
    cancelActionId: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9:_-]{8,128}$"
    )

    @model_validator(mode="after")
    def has_input(self):
        if (
            not self.message.strip()
            and not self.image
            and not self.referenceProductId
            and not self.confirmActionId
            and not self.cancelActionId
        ):
            raise ValueError("Nhập câu hỏi hoặc chọn ảnh sản phẩm.")
        return self


class Sessions:
    def __init__(self, settings):
        Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(settings.data_dir) / "sessions.sqlite"))
        self.db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, state TEXT, expires REAL)")
        self.ttl = settings.session_ttl

    @staticmethod
    def _prune_context(state, now):
        state = dict(state or {})
        expiries = dict(state.get("_context_expires", {}))

        if expiries.get("visual", float("inf")) <= now:
            for key in ("visual_description", "image_vector", "image_namespace"):
                state.pop(key, None)
            expiries.pop("visual", None)

        if expiries.get("pending_action", float("inf")) <= now:
            state.pop("pending_action", None)
            expiries.pop("pending_action", None)

        if expiries.get("shopping", float("inf")) <= now:
            for key in ("plan", "products", "focused_product_id", "focused_product_ids"):
                state.pop(key, None)
            expiries.pop("shopping", None)

        if expiries:
            state["_context_expires"] = expiries
        else:
            state.pop("_context_expires", None)
        return state

    def load(self, session_id):
        now = time.time()
        self.db.execute("DELETE FROM sessions WHERE expires < ?", (now,))
        self.db.commit()
        row = self.db.execute("SELECT state FROM sessions WHERE id=?", (session_id,)).fetchone() if session_id else None
        if session_id and not row:
            raise HTTPException(410, "Phiên chat đã hết hạn. Hãy bắt đầu cuộc trò chuyện mới.")
        return self._prune_context(json.loads(row[0]), now) if row else {}

    def save(self, session_id, state):
        self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?)",
                        (session_id, json.dumps(state, ensure_ascii=False), time.time() + self.ttl))
        self.db.commit()


@asynccontextmanager
async def lifespan(app):
    settings = Settings()
    api, commerce, models, vectors = (
        CatalogAPI(settings),
        CommerceAPI(settings),
        ModelClients(settings),
        VectorCatalog(settings),
    )
    app.state.settings = settings
    visual = VisualCatalog(settings)
    policies = PolicyCatalog(settings)
    product_agent = ProductAgent(api, models, vectors, visual, commerce)
    customer_service_agent = CustomerServiceAgent(models, policies)
    app.state.agent = RouterAgent(product_agent, customer_service_agent)
    app.state.sessions = Sessions(settings)
    app.state.busy_sessions = set()
    app.state.active_requests = 0
    try:
        yield
    finally:
        app.state.sessions.db.close()
        await api.close()
        await commerce.close()
        await models.close()
        await vectors.close()
        await visual.close()
        await policies.close()


app = FastAPI(title="Shopping Assistant", lifespan=lifespan)
app.include_router(speech_router)


@app.get("/assistant/health")
async def health():
    agent = app.state.agent.product_agent
    settings = app.state.settings
    try:
        missing_config = ["GEMINI_API_KEY"] if not settings.gemini_api_key else []
        indexed = await agent.vectors.client.collection_exists(agent.vectors.collection)
        visual_indexed = await agent.visual.exists()
        visual_count = (await agent.visual.client.count(agent.visual.collection)).count if visual_indexed else 0
        policy_count = await app.state.agent.customer_service_agent.catalog.count()
        ready = not missing_config and indexed
        return {"status": "ready" if ready else "warming_up", "indexed": indexed,
                "missingModels": [], "missingConfig": missing_config,
                "llmProvider": "gemini",
                "embeddingProvider": "gemini", "embeddingModel": settings.embedding_model,
                "embeddingDimensions": settings.embedding_dimensions, "textCollection": agent.vectors.collection,
                "visionReady": not missing_config,
                "remoteLlmVerified": False,
                "imageSearchMode": "text_and_image_vector", "indexedImages": visual_count,
                "imageIndexReady": visual_count > 0, "productMaxRounds": agent.max_rounds,
                "policyCollection": app.state.agent.customer_service_agent.catalog.collection,
                "indexedPolicyChunks": policy_count, "policyIndexReady": policy_count > 0}
    except Exception:
        raise HTTPException(503, "Chatbot đang chờ kết nối Qdrant.")


@app.post("/assistant/chat")
async def chat(request: ChatRequest, http_request: Request):
    session_id = request.sessionId or secrets.token_urlsafe(32)
    if session_id in app.state.busy_sessions:
        raise HTTPException(409, "Vui lòng đợi câu trả lời trước.")
    if app.state.active_requests >= 4:
        raise HTTPException(429, "Trợ lý đang bận. Bạn thử lại sau ít phút nhé.")
    previous = app.state.sessions.load(request.sessionId)
    previous_products = previous.get("products", [])
    mentioned_product_ids = resolve_product_references(request.message, previous_products)
    previous_focused_ids = previous.get("focused_product_ids") or [previous.get("focused_product_id", "")]
    focused_product_ids = (
        [request.referenceProductId]
        if request.referenceProductId
        else mentioned_product_ids or resolve_product_references(
            "", previous_products, focused_ids=previous_focused_ids
        )
    )
    focused_product_id = focused_product_ids[-1] if focused_product_ids else ""
    actor_user_id = str(http_request.headers.get("x-user-id", "")).strip()
    actor_role = str(http_request.headers.get("x-user-role", "")).strip()
    bound_user_id = str(previous.get("user_id", "")).strip()
    if bound_user_id and bound_user_id != actor_user_id:
        raise HTTPException(403, "Phiên chat này thuộc về một tài khoản khác.")
    app.state.busy_sessions.add(session_id)
    app.state.active_requests += 1
    try:
        image = None
        if request.image:
            try:
                raw = base64.b64decode(request.image.split(",", 1)[-1], validate=True)
                image = await asyncio.to_thread(normalize_image, raw, app.state.settings.max_image_bytes)
            except (ValueError, binascii.Error) as exc:
                raise HTTPException(400, str(exc)) from exc
        state = {"message": request.message.strip(), "image": image,
                 "reference_product_id": request.referenceProductId, "history": previous.get("history", []),
                 "previous_plan": previous.get("plan", {}), "previous_products": previous_products,
                 "focused_product_id": focused_product_id, "focused_product_ids": focused_product_ids,
                 "visual_description": previous.get("visual_description", ""),
                 "image_vector": [] if image else previous.get("image_vector", []),
                 "image_namespace": "" if image else previous.get("image_namespace", ""),
                 "session_id": session_id, "authenticated_user_id": actor_user_id, "actor_role": actor_role,
                 "variant_id": request.variantId, "address_id": request.addressId,
                 "payment_method": request.paymentMethod, "voucher_code": request.voucherCode,
                 "action_request_id": request.actionRequestId, "confirm_action_id": request.confirmActionId,
                 "cancel_action_id": request.cancelActionId, "pending_action": previous.get("pending_action")}
        result = await asyncio.wait_for(app.state.agent.graph.ainvoke(state), timeout=360)
        history = compact_history(state["history"] + [
            {"role": "user", "content": request.message or "[Ảnh sản phẩm]"},
            {"role": "assistant", "content": result["answer"]},
        ])
        # Keep compact context and reusable visual features, never shopper image bytes.
        result_products = result.get("products", [])
        products = compact_session_products(result_products)
        pending_action = result["pending_action"] if "pending_action" in result else previous.get("pending_action")
        if "focused_product_ids" in result:
            next_focused_product_ids = result["focused_product_ids"]
        elif result.get("action_result"):
            next_focused_product_ids = focused_product_ids
        elif mentioned_product_ids:
            next_focused_product_ids = mentioned_product_ids
        elif products:
            next_focused_product_ids = [products[0]["id"]] if len(products) == 1 else []
        elif request.referenceProductId:
            next_focused_product_ids = [request.referenceProductId]
        elif result.get("plan", {}).get("intent") in {"search", "similar"}:
            next_focused_product_ids = []
        else:
            next_focused_product_ids = focused_product_ids
        next_focused_product_id = next_focused_product_ids[-1] if next_focused_product_ids else ""
        now = time.time()
        expiries = dict(previous.get("_context_expires", {}))
        plan = result.get("plan", previous.get("plan", {}))
        saved_products = products or previous.get("products", [])
        if "plan" in result or products:
            expiries["shopping"] = now + _bounded_env_int(
                "CHATBOT_SHOPPING_CONTEXT_TTL_SECONDS", 21600, 300, 86400
            )

        visual_description = result.get("visual_description", previous.get("visual_description", ""))
        image_vector = result.get("image_vector", previous.get("image_vector", [])) if visual_description else []
        image_namespace = result.get("image_namespace", previous.get("image_namespace", "")) if visual_description else ""
        if visual_description:
            expiries["visual"] = now + _bounded_env_int(
                "CHATBOT_IMAGE_CONTEXT_TTL_SECONDS", 3600, 60, 21600
            )
        else:
            expiries.pop("visual", None)

        if pending_action:
            if pending_action != previous.get("pending_action") or "pending_action" not in expiries:
                expiries["pending_action"] = now + _bounded_env_int(
                    "CHATBOT_PENDING_ACTION_TTL_SECONDS", 600, 60, 3600
                )
        else:
            expiries.pop("pending_action", None)

        app.state.sessions.save(session_id, {"history": history, "plan": plan,
            "products": saved_products, "visual_description": visual_description,
            "image_vector": image_vector, "image_namespace": image_namespace,
            "user_id": actor_user_id or bound_user_id, "pending_action": pending_action,
            "focused_product_id": next_focused_product_id,
            "focused_product_ids": next_focused_product_ids, "_context_expires": expiries})
        public_pending = None
        if pending_action:
            public_pending = {key: value for key, value in pending_action.items() if key != "confirmationToken"}
        return {"sessionId": session_id, "answer": result["answer"], "products": result.get("products", []),
                "imageSearchMode": result.get("retrieval_mode") if result.get("visual_description") else None,
                "retrievalRounds": result.get("rounds", 0), "warnings": result.get("warnings", []),
                "sources": result.get("sources", []), "route": result.get("route_name", "product"),
                "pendingAction": public_pending, "actionResult": result.get("action_result")}
    except HTTPException:
        raise
    except (httpx.HTTPError, UnexpectedResponse, asyncio.TimeoutError):
        log.exception("Chat dependency unavailable")
        raise HTTPException(503, "Trợ lý chưa sẵn sàng hoặc xử lý quá lâu. Vui lòng thử lại sau.")
    except (ValidationError, json.JSONDecodeError):
        log.exception("Invalid model search plan")
        raise HTTPException(502, "Tôi chưa hiểu rõ yêu cầu. Bạn thử diễn đạt lại nhé.")
    except Exception:
        log.exception("Chat failed")
        raise HTTPException(503, "Trợ lý tạm thời chưa xử lý được yêu cầu. Bạn thử lại sau nhé.")
    finally:
        app.state.busy_sessions.discard(session_id)
        app.state.active_requests -= 1


@app.get("/assistant/products/{product_id}/similar")
async def similar_products(
    product_id: Annotated[str, ApiPath(pattern=r"^[a-fA-F0-9]{24}$")],
    max_price: Annotated[float | None, Query(ge=0, le=1e12)] = None,
):
    if app.state.active_requests >= 4:
        raise HTTPException(429, "Trợ lý đang bận. Bạn thử lại sau nhé.")
    app.state.active_requests += 1
    try:
        result = await asyncio.wait_for(app.state.agent.product_agent.retrieve({
            "message": "Tìm sản phẩm tương tự", "visual_description": "",
            "plan": SearchPlan(intent="similar", query="", reference_product_id=product_id,
                               max_price=max_price).model_dump(),
        }), timeout=180)
        return {"products": result["products"]}
    except Exception:
        log.exception("Similar product retrieval failed")
        raise HTTPException(503, "Chưa tìm được sản phẩm tương tự. Vui lòng thử lại sau.")
    finally:
        app.state.active_requests -= 1
