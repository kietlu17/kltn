"""One CPU model process shared by API and visual indexer; no public host port."""
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


def encode(image):
    global _model, _processor
    with _lock:
        import torch
        from transformers import CLIPImageProcessor, CLIPVisionModelWithProjection
        if _model is None:
            torch.set_num_threads(4)
            name = os.getenv("CHATBOT_IMAGE_MODEL", IMAGE_MODEL)
            revision = os.getenv("CHATBOT_IMAGE_REVISION", IMAGE_REVISION)
            _processor = CLIPImageProcessor.from_pretrained(name, revision=revision)
            _model = CLIPVisionModelWithProjection.from_pretrained(name, revision=revision).eval()
        inputs = _processor(images=Image.open(io.BytesIO(base64.b64decode(image))).convert("RGB"), return_tensors="pt")
        with torch.inference_mode():
            vector = _model(**inputs).image_embeds
            vector = torch.nn.functional.normalize(vector, p=2, dim=-1)
        return vector[0].tolist()


@app.get("/health")
async def health():
    return {"identity": image_identity(), "loaded": _model is not None}


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
