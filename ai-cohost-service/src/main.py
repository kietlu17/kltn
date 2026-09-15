import asyncio
import json
import os
import re
import ssl
import threading
import time
import unicodedata
from contextlib import asynccontextmanager
from typing import Any

import httpx
import uvicorn
from aiokafka import AIOKafkaProducer
from dotenv import load_dotenv
from fastapi import FastAPI
from livekit import agents


load_dotenv()

AGENT_NAME = os.getenv("LIVEKIT_AGENT_NAME", "live-commerce-cohost")
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost:9092")
CART_SERVICE_URL = os.getenv("CART_SERVICE_URL", "https://localhost:3005").rstrip("/")
PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "https://localhost:3004").rstrip("/")
PORT = int(os.getenv("PORT", "3020"))
LLM_ENABLED = os.getenv("LLM_ENABLED", "true").lower() == "true"
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://ollama:11434/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:3b-instruct")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "4"))
LLM_MIN_CONFIDENCE = float(os.getenv("LLM_MIN_CONFIDENCE", "0.7"))
LLM_FALLBACK_RULES = os.getenv("LLM_FALLBACK_RULES", "false").lower() == "true"

FALLBACK_BUY_KEYWORDS = (
    "toi muon mua",
    "muon mua",
    "mua san pham",
    "mua mon",
    "lay san pham",
    "lay mon",
    "lay cai",
    "cho toi",
    "them vao gio",
    "add cart",
    "add to cart",
)

INTENT_SYSTEM_PROMPT = """
Bạn là bộ phân loại intent cho livestream shopping.
Nhiệm vụ duy nhất: đọc tin nhắn chat của khách và trả về JSON hợp lệ.

Quy tắc an toàn:
- Chỉ được nhận diện ý định thêm sản phẩm đang ghim vào giỏ hàng.
- Không được thanh toán, đặt hàng, tạo order, xử lý ví/thẻ/ngân hàng.
- Nếu khách chỉ hỏi thông tin, chào hỏi, mặc cả, hỏi giá, hỏi ship: intent là ask_product_info hoặc none.
- Nếu đang chờ khách chọn biến thể, câu trả lời như "màu đen", "size L", "lấy đen" có thể là add_to_cart với variant_hint.
- Khi không chắc, trả về none.

Schema JSON bắt buộc:
{
  "intent": "add_to_cart" | "ask_product_info" | "none",
  "confidence": number từ 0 đến 1,
  "quantity": số nguyên từ 1 đến 20,
  "product_reference": "active_pinned_product",
  "variant_hint": chuỗi ngắn hoặc null,
  "reason": chuỗi ngắn
}
Chỉ trả về JSON, không markdown, không giải thích ngoài JSON.
""".strip()

GENERIC_VARIANT_WORDS = {
    "mau",
    "size",
    "kich",
    "co",
    "loai",
    "phien",
    "ban",
    "variant",
    "sku",
}

kafka_producer: AIOKafkaProducer | None = None
pending_variant_requests: dict[str, dict[str, Any]] = {}


def normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d")
    return re.sub(r"\s+", " ", text).strip()


def now_ms() -> int:
    return int(time.time() * 1000)


def mtls_options() -> dict[str, Any]:
    if os.getenv("MTLS_ENABLED") != "true":
        return {}
    context = ssl.create_default_context(cafile=os.getenv("MTLS_CA_PATH"))
    context.load_cert_chain(
        certfile=os.getenv("MTLS_CLIENT_CERT_PATH"),
        keyfile=os.getenv("MTLS_CLIENT_KEY_PATH"),
    )
    return {"verify": context}


def get_buyer_key(live_id: str | None, buyer_id: str | None) -> str:
    return f"{live_id or ''}:{buyer_id or ''}"


async def get_kafka_producer() -> AIOKafkaProducer:
    global kafka_producer
    if kafka_producer is None:
        kafka_producer = AIOKafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            client_id=os.getenv("KAFKA_CLIENT_ID", "ai-cohost-service"),
        )
        await kafka_producer.start()
    return kafka_producer


async def publish_kafka(topic: str, payload: dict[str, Any], key: str | None = None) -> None:
    try:
        producer = await get_kafka_producer()
        event = {
            **payload,
            "eventType": topic,
            "occurredAt": payload.get("occurredAt") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        await producer.send_and_wait(
            topic,
            json.dumps(event, ensure_ascii=False).encode("utf-8"),
            key=(key or payload.get("liveId") or payload.get("id") or "").encode("utf-8") or None,
        )
    except Exception as exc:
        print(f"Kafka publish failed for {topic}: {exc}", flush=True)


async def publish_room_data(room: Any, payload: dict[str, Any]) -> None:
    if isinstance(room, list):
        room.append(payload)
        return
    participant = getattr(room, "local_participant", None)
    if participant is None:
        return
    await participant.publish_data(
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        reliable=True,
        topic=payload.get("type") or "live.event",
    )


async def fetch_product(product_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=5, **mtls_options()) as client:
        response = await client.get(f"{PRODUCT_SERVICE_URL}/products/{product_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()


async def add_to_cart(*, buyer_id: str, product_id: str, quantity: int, variant_id: str | None = None) -> dict[str, Any]:
    payload = {
        "userId": buyer_id,
        "productId": product_id,
        "quantity": quantity,
        "variantId": variant_id,
    }
    async with httpx.AsyncClient(timeout=5, **mtls_options()) as client:
        response = await client.post(f"{CART_SERVICE_URL}/cart/add", json=payload)
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if response.status_code >= 400:
            raise RuntimeError(body.get("message") or f"cart-service returned {response.status_code}")
        return body


def parse_llm_json(content: str) -> dict[str, Any] | None:
    try:
        value = json.loads(content)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None


def clamp_quantity(value: Any) -> int:
    try:
        return min(20, max(1, int(value)))
    except (TypeError, ValueError):
        return 1


def sanitize_llm_intent(payload: dict[str, Any]) -> dict[str, Any] | None:
    intent_name = str(payload.get("intent") or "none").strip().lower()
    if intent_name not in {"add_to_cart", "ask_product_info", "none"}:
        intent_name = "none"

    try:
        confidence = float(payload.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0
    confidence = min(1, max(0, confidence))

    if intent_name != "add_to_cart" or confidence < LLM_MIN_CONFIDENCE:
        return None

    variant_hint = payload.get("variant_hint")
    if variant_hint is not None:
        variant_hint = str(variant_hint).strip()[:120] or None

    return {
        "name": "add_to_cart",
        "confidence": confidence,
        "quantity": clamp_quantity(payload.get("quantity")),
        "productReference": "active_pinned_product",
        "variantHint": variant_hint,
        "source": "llm",
    }


async def classify_intent_with_llm(text: str, has_pending_variant: bool = False) -> dict[str, Any] | None:
    if not LLM_ENABLED or not text.strip():
        return None

    body = {
        "model": LLM_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "text": text,
                        "has_pending_variant_request": has_pending_variant,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"} if LLM_API_KEY else {}

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{LLM_BASE_URL}/chat/completions", json=body, headers=headers)
            if response.status_code == 400:
                body.pop("response_format", None)
                response = await client.post(f"{LLM_BASE_URL}/chat/completions", json=body, headers=headers)
            response.raise_for_status()
            result = response.json()
    except Exception as exc:
        print(f"LLM intent classification failed: {exc}", flush=True)
        return None

    content = (((result.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    parsed = parse_llm_json(content)
    if not parsed:
        return None
    return sanitize_llm_intent(parsed)


def fallback_purchase_intent(text: str, has_pending_variant: bool = False) -> dict[str, Any] | None:
    normalized = normalize_text(text)
    has_buy_intent = any(keyword in normalized for keyword in FALLBACK_BUY_KEYWORDS)
    if not has_buy_intent and not has_pending_variant:
        return None
    quantity_match = re.search(r"\b(\d{1,2})\s*(cai|sp|san pham|mon|chai|hop|bo)?\b", normalized)
    return {
        "name": "add_to_cart",
        "confidence": 0.86 if has_buy_intent else 0.72,
        "quantity": clamp_quantity(quantity_match.group(1)) if quantity_match else 1,
        "productReference": "active_pinned_product",
        "variantHint": text if has_pending_variant and not has_buy_intent else None,
        "source": "fallback",
    }


async def detect_purchase_intent(text: str, has_pending_variant: bool = False) -> dict[str, Any] | None:
    intent = await classify_intent_with_llm(text, has_pending_variant)
    if intent:
        return intent
    if LLM_FALLBACK_RULES or not LLM_ENABLED:
        return fallback_purchase_intent(text, has_pending_variant)
    return None


def normalize_variant(variant: dict[str, Any]) -> dict[str, Any]:
    variant_id = str(variant.get("_id") or variant.get("id") or variant.get("variantId") or "")
    return {
        "variantId": variant_id,
        "name": variant.get("name") or "Biến thể",
        "sku": variant.get("sku") or "",
        "price": variant.get("price"),
        "stock": int(float(variant.get("quantity") or 0)),
        "imageUrl": variant.get("imageUrl") or "",
    }


def resolve_variant(product: dict[str, Any], text: str) -> dict[str, Any]:
    variants = [normalize_variant(item) for item in product.get("variants") or []]
    in_stock = [item for item in variants if item["variantId"] and item["stock"] > 0]
    if not variants:
        stock = int(float(product.get("quantity") or 0))
        return {"status": "ready", "variant": None, "options": [], "stock": stock}
    if not in_stock:
        return {"status": "out_of_stock", "variant": None, "options": variants, "stock": 0}
    if len(in_stock) == 1:
        return {"status": "ready", "variant": in_stock[0], "options": in_stock, "stock": in_stock[0]["stock"]}

    normalized_text = normalize_text(text)
    scored: list[tuple[int, dict[str, Any]]] = []
    for variant in in_stock:
        name = normalize_text(variant["name"])
        sku = normalize_text(variant["sku"])
        tokens = [token for token in re.split(r"[^a-z0-9]+", name) if token and token not in GENERIC_VARIANT_WORDS]
        score = 0
        if name and name in normalized_text:
            score += 100
        if sku and sku in normalized_text:
            score += 90
        score += sum(12 for token in tokens if re.search(rf"\b{re.escape(token)}\b", normalized_text))
        if score > 0:
            scored.append((score, variant))

    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score = scored[0][0]
        best = [variant for score, variant in scored if score == best_score]
        if len(best) == 1:
            return {"status": "ready", "variant": best[0], "options": in_stock, "stock": best[0]["stock"]}

    return {"status": "variant_required", "variant": None, "options": in_stock, "stock": sum(item["stock"] for item in in_stock)}


def variant_options_payload(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "variantId": item["variantId"],
            "name": item["name"],
            "sku": item["sku"],
            "price": item["price"],
            "stock": item["stock"],
            "imageUrl": item["imageUrl"],
        }
        for item in options
    ]


async def request_variant(room: Any, chat_event: dict[str, Any], product: dict[str, Any], quantity: int, options: list[dict[str, Any]]) -> None:
    key = get_buyer_key(chat_event.get("liveId"), chat_event.get("buyerId"))
    pending_variant_requests[key] = {
        "product": product,
        "quantity": quantity,
        "chatEvent": chat_event,
        "expiresAt": time.time() + 300,
    }
    event = {
        "type": "live.intent.variant_required",
        "id": f"variant-required-{now_ms()}",
        "liveId": chat_event.get("liveId"),
        "shopId": chat_event.get("shopId"),
        "buyerId": chat_event.get("buyerId"),
        "productId": str(product.get("_id") or product.get("id")),
        "productName": product.get("name"),
        "quantity": quantity,
        "variantOptions": variant_options_payload(options),
        "reply": "Sản phẩm này có nhiều biến thể. Bạn chọn màu/size rồi bấm thêm vào giỏ nhé.",
    }
    await publish_room_data(room, event)


async def publish_intent(room: Any, chat_event: dict[str, Any], intent: dict[str, Any], product_id: str | None, reply: str) -> None:
    event = {
        "type": "live.intent.detected",
        "id": f"intent-{now_ms()}",
        "liveId": chat_event.get("liveId"),
        "shopId": chat_event.get("shopId"),
        "buyerId": chat_event.get("buyerId"),
        "intent": intent["name"],
        "productId": product_id,
        "quantity": intent["quantity"],
        "confidence": intent["confidence"],
        "productReference": intent.get("productReference"),
        "variantHint": intent.get("variantHint"),
        "source": intent.get("source"),
        "reply": reply,
    }
    await publish_kafka("live.intent.detected", event, event.get("liveId"))
    await publish_room_data(room, event)


async def add_resolved_item(room: Any, chat_event: dict[str, Any], product: dict[str, Any], quantity: int, variant: dict[str, Any] | None) -> None:
    product_id = str(product.get("_id") or product.get("id"))
    await add_to_cart(
        buyer_id=chat_event["buyerId"],
        product_id=product_id,
        quantity=quantity,
        variant_id=variant["variantId"] if variant else None,
    )
    variant_name = f" ({variant['name']})" if variant else ""
    event = {
        "type": "live.cart.item_added",
        "id": f"cart-{now_ms()}",
        "liveId": chat_event.get("liveId"),
        "shopId": chat_event.get("shopId"),
        "buyerId": chat_event.get("buyerId"),
        "productId": product_id,
        "productName": product.get("name"),
        "variantId": variant["variantId"] if variant else None,
        "variantName": variant["name"] if variant else None,
        "quantity": quantity,
        "reply": f"Đã thêm {quantity} {product.get('name') or 'sản phẩm'}{variant_name} vào giỏ hàng.",
    }
    await publish_kafka("live.cart.item_added", event, event.get("liveId"))
    await publish_room_data(room, event)


async def handle_chat_message(room: Any, message: dict[str, Any], job_metadata: dict[str, Any]) -> None:
    chat_event = {
        "type": "live.chat.message.created",
        "id": message.get("id") or f"chat-{now_ms()}",
        "liveId": message.get("liveId") or job_metadata.get("liveId"),
        "shopId": message.get("shopId") or job_metadata.get("shopId"),
        "buyerId": message.get("buyerId") or message.get("senderId"),
        "senderId": message.get("senderId"),
        "senderRole": message.get("senderRole"),
        "senderName": message.get("senderName"),
        "text": message.get("text") or "",
        "activePinnedProductId": message.get("activePinnedProductId") or job_metadata.get("activePinnedProductId"),
    }
    if not job_metadata.get("skipChatKafka"):
        await publish_kafka("live.chat.message.created", chat_event, chat_event.get("liveId"))

    if chat_event["senderRole"] != "buyer" or not chat_event.get("buyerId"):
        print(
            "Ignored chat message for AI cart intent: "
            f"senderRole={chat_event.get('senderRole')} buyerId={chat_event.get('buyerId')}",
            flush=True,
        )
        return

    pending_key = get_buyer_key(chat_event.get("liveId"), chat_event.get("buyerId"))
    pending = pending_variant_requests.get(pending_key)
    if pending and pending["expiresAt"] < time.time():
        pending_variant_requests.pop(pending_key, None)
        pending = None

    intent = await detect_purchase_intent(chat_event["text"], has_pending_variant=bool(pending))
    if not intent:
        print(f"No purchase intent detected for chat: {chat_event['text']}", flush=True)
        return

    product_id = chat_event.get("activePinnedProductId")
    product = None
    if pending:
        product = pending["product"]
        product_id = str(product.get("_id") or product.get("id"))
        intent["quantity"] = intent["quantity"] or pending["quantity"]

    if not product_id:
        print("Purchase intent detected but no active pinned product is available", flush=True)
        await publish_intent(room, chat_event, intent, None, "Cửa hàng chưa ghim sản phẩm để thêm vào giỏ.")
        return

    product = product or await fetch_product(product_id)
    if not product:
        print(f"Purchase intent detected but pinned product was not found: {product_id}", flush=True)
        await publish_intent(room, chat_event, intent, product_id, "Không tìm thấy sản phẩm đang ghim.")
        return

    await publish_intent(
        room,
        chat_event,
        intent,
        product_id,
        f"Đã nhận yêu cầu thêm {intent['quantity']} {product.get('name') or 'sản phẩm'} vào giỏ.",
    )

    resolution = resolve_variant(product, intent.get("variantHint") or chat_event["text"])
    if resolution["status"] == "out_of_stock":
        await publish_room_data(room, {
            "type": "live.cart.item_add_failed",
            "id": f"cart-failed-{now_ms()}",
            "liveId": chat_event.get("liveId"),
            "buyerId": chat_event.get("buyerId"),
            "productId": product_id,
            "reply": "Sản phẩm đang hết hàng.",
        })
        return
    if resolution["status"] == "variant_required":
        await request_variant(room, chat_event, product, intent["quantity"], resolution["options"])
        return
    if resolution["status"] == "ready" and resolution["variant"] is None and resolution["stock"] <= 0:
        await publish_room_data(room, {
            "type": "live.cart.item_add_failed",
            "id": f"cart-failed-{now_ms()}",
            "liveId": chat_event.get("liveId"),
            "buyerId": chat_event.get("buyerId"),
            "productId": product_id,
            "reply": "Sản phẩm đang hết hàng.",
        })
        return

    pending_variant_requests.pop(pending_key, None)
    try:
        await add_resolved_item(room, chat_event, product, intent["quantity"], resolution["variant"])
    except Exception as exc:
        await publish_room_data(room, {
            "type": "live.cart.item_add_failed",
            "id": f"cart-failed-{now_ms()}",
            "liveId": chat_event.get("liveId"),
            "buyerId": chat_event.get("buyerId"),
            "productId": product_id,
            "reply": str(exc) or "Không thể thêm sản phẩm vào giỏ.",
        })


async def entrypoint(ctx: agents.JobContext) -> None:
    metadata = json.loads(ctx.job.metadata or "{}") if getattr(ctx, "job", None) else {}
    room = ctx.room

    @room.on("data_received")
    def on_data_received(data_packet: Any) -> None:
        payload = getattr(data_packet, "data", data_packet)
        participant = getattr(data_packet, "participant", None)
        try:
            message = json.loads(bytes(payload).decode("utf-8"))
        except Exception as exc:
            print(f"Failed to decode LiveKit data packet: {exc}", flush=True)
            return
        if message.get("type") != "live.chat.message":
            return
        if participant is not None:
            message.setdefault("senderId", getattr(participant, "identity", None))
            message.setdefault("senderName", getattr(participant, "name", None) or getattr(participant, "identity", None))
        print(
            "Received live chat message: "
            f"liveId={message.get('liveId')} senderRole={message.get('senderRole')} "
            f"buyerId={message.get('buyerId') or message.get('senderId')} "
            f"activePinnedProductId={message.get('activePinnedProductId') or metadata.get('activePinnedProductId')}",
            flush=True,
        )
        asyncio.create_task(handle_chat_message(room, message, metadata))

    await ctx.connect(auto_subscribe=agents.AutoSubscribe.SUBSCRIBE_ALL)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    if kafka_producer is not None:
        await kafka_producer.stop()


app = FastAPI(title="AI Livestream Co-host Service", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "agentName": AGENT_NAME,
        "pendingVariantRequests": len(pending_variant_requests),
        "llmEnabled": LLM_ENABLED,
        "llmBaseUrl": LLM_BASE_URL,
        "llmModel": LLM_MODEL,
        "llmFallbackRules": LLM_FALLBACK_RULES,
    }


@app.post("/intent/preview")
async def intent_preview(payload: dict[str, Any]) -> dict[str, Any]:
    text = payload.get("text") or ""
    intent = await detect_purchase_intent(text, has_pending_variant=bool(payload.get("hasPendingVariant")))
    return {
        "intent": intent,
        "normalizedText": normalize_text(text),
        "llmEnabled": LLM_ENABLED,
        "llmModel": LLM_MODEL,
    }


@app.post("/live-chat")
async def live_chat(payload: dict[str, Any]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    message = payload.get("message") or payload
    metadata = {**(payload.get("metadata") or {}), "skipChatKafka": True}
    await handle_chat_message(events, message, metadata)
    return {
        "ok": True,
        "events": events,
    }


def start_fastapi() -> None:
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    asyncio.run(server.serve())


if __name__ == "__main__":
    threading.Thread(target=start_fastapi, daemon=True).start()
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=AGENT_NAME,
        )
    )
