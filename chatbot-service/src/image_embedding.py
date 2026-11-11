"""Local CPU models shared by the assistants and the visual indexer; no public host port.

/embed   CLIP image embeddings (photo search and image indexing)
/rerank  multilingual cross-encoder scores (second-stage product ranking)
"""
import asyncio
import base64
import io
import os
import threading

from fastapi import FastAPI, HTTPException, Request
from PIL import Image

from .infrastructure.clients import normalize_image
from .product.visual import IMAGE_MODEL, IMAGE_REVISION, image_identity

app = FastAPI(title="Internal image embedding")
_lock = threading.Lock()
_model = None
_processor = None
_rerank_lock = threading.Lock()
_reranker = None
_rerank_tokenizer = None
RERANK_MODEL = os.getenv("RERANK_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")
RERANK_REVISION = os.getenv("RERANK_REVISION", "1427fd652930e4ba29e8149678df786c240d8825")
# Query + product document (name, category, price, specs, variants) in tokens;
# 128 cut the price and specs off most documents.
RERANK_MAX_LENGTH = int(os.getenv("RERANK_MAX_LENGTH", "256"))


def encode(image):
    global _model, _processor
    with _lock:
        import torch
        from transformers import CLIPImageProcessor, CLIPVisionModelWithProjection
        if _model is None:
            name = os.getenv("CHATBOT_IMAGE_MODEL", IMAGE_MODEL)
            revision = os.getenv("CHATBOT_IMAGE_REVISION", IMAGE_REVISION)
            _processor = CLIPImageProcessor.from_pretrained(name, revision=revision)
            _model = CLIPVisionModelWithProjection.from_pretrained(name, revision=revision).eval()
        inputs = _processor(images=Image.open(io.BytesIO(base64.b64decode(image))).convert("RGB"), return_tensors="pt")
        with torch.inference_mode():
            vector = _model(**inputs).image_embeds
            vector = torch.nn.functional.normalize(vector, p=2, dim=-1)
        return vector[0].tolist()


def _configure_threads():
    # Few threads per request: many shoppers in parallel beat one fast
    # request on a shared CPU (16 cores, 8 threads each oversubscribed it).
    import torch
    torch.set_num_threads(int(os.getenv("MODEL_THREADS", "2")))


def _load_reranker():
    global _reranker, _rerank_tokenizer
    with _rerank_lock:
        if _reranker is None:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            _rerank_tokenizer = AutoTokenizer.from_pretrained(RERANK_MODEL, revision=RERANK_REVISION)
            _reranker = AutoModelForSequenceClassification.from_pretrained(
                RERANK_MODEL, revision=RERANK_REVISION
            ).eval()
    return _reranker, _rerank_tokenizer


def rerank_scores(query: str, documents: list[str]) -> list[float]:
    import torch
    # The lock only guards loading: concurrent shoppers score in parallel
    # instead of queueing behind one another.
    model, tokenizer = _reranker and (_reranker, _rerank_tokenizer) or _load_reranker()
    inputs = tokenizer(
        [query] * len(documents), documents,
        padding=True, truncation=True, max_length=RERANK_MAX_LENGTH, return_tensors="pt",
    )
    with torch.inference_mode():
        return model(**inputs).logits.squeeze(-1).reshape(-1).tolist()


def _warm_up():
    """Load both models before the first shopper waits for them."""
    import logging
    _configure_threads()
    try:
        rerank_scores("khởi động", ["sản phẩm"])
        encode(base64.b64encode(_blank_png()).decode())
    except Exception:
        logging.getLogger(__name__).exception("Model warm-up failed; models load on first use")


def _blank_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, "PNG")
    return buffer.getvalue()


@app.on_event("startup")
async def warm_up():
    threading.Thread(target=_warm_up, daemon=True).start()


@app.get("/health")
async def health():
    return {
        "identity": image_identity(),
        "loaded": _model is not None,
        "reranker": {"model": f"{RERANK_MODEL}@{RERANK_REVISION}", "loaded": _reranker is not None},
    }


@app.post("/rerank")
async def rerank(request: Request):
    try:
        body = await request.json()
        query = str(body["query"]).strip()[:500]
        documents = [str(item)[:2000] for item in body["documents"]]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "Expected {query, documents}")
    if not query or not documents or len(documents) > 50:
        raise HTTPException(400, "Need a query and 1-50 documents")
    scores = await asyncio.to_thread(rerank_scores, query, documents)
    return {"model": RERANK_MODEL, "scores": scores}


@app.post("/embed")
async def embed(request: Request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 8 * 1024 * 1024:
            raise HTTPException(413, "Image payload too large")
    try:
        import json
        encoded = json.loads(raw)["image"]
        image = await asyncio.to_thread(normalize_image, base64.b64decode(encoded, validate=True), 5 * 1024 * 1024)
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "Invalid image")
    vector = await asyncio.to_thread(encode, image)
    return {"identity": image_identity(), "embedding": vector}
