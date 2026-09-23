import asyncio
import base64
import binascii
import json
import logging
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import FastAPI, HTTPException, Path as ApiPath, Query
from pydantic import BaseModel, Field, ValidationError, model_validator
from qdrant_client.http.exceptions import UnexpectedResponse

from .agents.product import ProductAgent
from .agents.router import RouterAgent
from .agents.state import SearchPlan
from .api.speech import router as speech_router
from .core.settings import Settings
from .infrastructure.clients import CatalogAPI, normalize_image
from .infrastructure.models import ModelClients
from .policy.agent import CustomerServiceAgent
from .policy.catalog import PolicyCatalog
from .product.catalog import VectorCatalog
from .product.visual import VisualCatalog

log = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=2000)
    image: str | None = Field(default=None, max_length=7_000_000)
    sessionId: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{43}$")
    referenceProductId: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{24}$")

    @model_validator(mode="after")
    def has_input(self):
        if not self.message.strip() and not self.image and not self.referenceProductId:
            raise ValueError("Nhập câu hỏi hoặc chọn ảnh sản phẩm.")
        return self


class Sessions:
    def __init__(self, settings):
        Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(settings.data_dir) / "sessions.sqlite"))
        self.db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, state TEXT, expires REAL)")
        self.ttl = settings.session_ttl

    def load(self, session_id):
        now = time.time()
        self.db.execute("DELETE FROM sessions WHERE expires < ?", (now,))
        self.db.commit()
        row = self.db.execute("SELECT state FROM sessions WHERE id=?", (session_id,)).fetchone() if session_id else None
        if session_id and not row:
            raise HTTPException(410, "Phiên chat đã hết hạn. Hãy bắt đầu cuộc trò chuyện mới.")
        return json.loads(row[0]) if row else {}

    def save(self, session_id, state):
        self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?)",
                        (session_id, json.dumps(state, ensure_ascii=False), time.time() + self.ttl))
        self.db.commit()


@asynccontextmanager
async def lifespan(app):
    settings = Settings()
    api, models, vectors = CatalogAPI(settings), ModelClients(settings), VectorCatalog(settings)
    app.state.settings = settings
    visual = VisualCatalog(settings)
    policies = PolicyCatalog(settings)
    product_agent = ProductAgent(api, models, vectors, visual)
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
async def chat(request: ChatRequest):
    session_id = request.sessionId or secrets.token_urlsafe(32)
    if session_id in app.state.busy_sessions:
        raise HTTPException(409, "Vui lòng đợi câu trả lời trước.")
    if app.state.active_requests >= 4:
        raise HTTPException(429, "Trợ lý đang bận. Bạn thử lại sau ít phút nhé.")
    previous = app.state.sessions.load(request.sessionId)
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
                 "previous_plan": previous.get("plan", {}), "previous_products": previous.get("products", []),
                 "visual_description": previous.get("visual_description", ""),
                 "image_vector": [] if image else previous.get("image_vector", []),
                 "image_namespace": "" if image else previous.get("image_namespace", "")}
        result = await asyncio.wait_for(app.state.agent.graph.ainvoke(state), timeout=360)
        history = (state["history"] + [{"role": "user", "content": request.message or "[Ảnh sản phẩm]"},
                                      {"role": "assistant", "content": result["answer"]}])[-12:]
        # Keep compact context and reusable visual features, never shopper image bytes.
        products = [{"id": p["id"], "name": p["name"]} for p in result.get("products", [])]
        app.state.sessions.save(session_id, {"history": history, "plan": result.get("plan", previous.get("plan", {})),
            "products": products or previous.get("products", []), "visual_description": result.get("visual_description", ""),
            "image_vector": result.get("image_vector", []) if result.get("visual_description") else [],
            "image_namespace": result.get("image_namespace", "") if result.get("visual_description") else ""})
        return {"sessionId": session_id, "answer": result["answer"], "products": result.get("products", []),
                "imageSearchMode": result.get("retrieval_mode") if result.get("visual_description") else None,
                "retrievalRounds": result.get("rounds", 0), "warnings": result.get("warnings", []),
                "sources": result.get("sources", []), "route": result.get("route_name", "product")}
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
