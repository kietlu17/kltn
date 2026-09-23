"""Local OpenAI Whisper transcription. Audio is never persisted after inference."""
import asyncio
import logging
import os
import subprocess
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()
_lock = threading.Lock()
_model = None
MAX_BYTES = 5 * 1024 * 1024


def transcribe_audio(raw: bytes) -> str:
    global _model
    if not _lock.acquire(blocking=False):
        raise HTTPException(429, "Đang xử lý một bản ghi khác. Bạn thử lại sau nhé.")
    try:
        import numpy as np
        with tempfile.TemporaryDirectory(prefix="chatbot-audio-") as directory:
            path = Path(directory) / "recording"
            path.write_bytes(raw)
            try:
                decoded = subprocess.run([
                    "ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
                    "-i", str(path), "-t", "61", "-vn", "-ac", "1", "-ar", "16000",
                    "-f", "f32le", "pipe:1",
                ], capture_output=True, timeout=20, check=True)
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                raise HTTPException(400, "Không đọc được âm thanh. Hãy thu lại.") from exc
            audio = np.frombuffer(decoded.stdout, dtype=np.float32).copy()
            if not len(audio) or len(audio) > 60 * 16000:
                raise HTTPException(400, "Bản ghi phải dài từ 1 đến 60 giây.")
            if len(audio) < 16000:
                raise HTTPException(400, "Bản ghi quá ngắn. Hãy nói ít nhất một giây.")
            if float(np.max(np.abs(audio))) < 0.001:
                return ""
            import torch
            import whisper
            if _model is None:
                torch.set_num_threads(4)
                _model = whisper.load_model(os.getenv("CHATBOT_WHISPER_MODEL", "base"), device="cpu",
                    download_root=os.getenv("CHATBOT_WHISPER_CACHE", "/data/whisper"))
            result = _model.transcribe(audio, language=os.getenv("CHATBOT_STT_LANGUAGE", "vi") or None,
                                       task="transcribe", fp16=False, condition_on_previous_text=False)
            return result["text"].strip()
    finally:
        # The worker owns the lock: cancelling the HTTP request must not release
        # it while CPU inference is still running in this thread.
        _lock.release()


@router.post("/assistant/transcribe")
async def transcribe(request: Request):
    if request.headers.get("content-type", "").split(";", 1)[0] not in {
        "audio/webm", "audio/ogg", "audio/mp4", "audio/wav", "audio/x-wav",
    }:
        raise HTTPException(415, "Định dạng âm thanh chưa được hỗ trợ.")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, "Bản ghi vượt quá 5 MB.")
    if not raw:
        raise HTTPException(400, "Bản ghi trống. Hãy thu lại.")
    try:
        text = await asyncio.to_thread(transcribe_audio, bytes(raw))
        return {"text": text}
    except HTTPException:
        raise
    except Exception:
        logging.getLogger(__name__).exception("Local Whisper transcription failed")
        raise HTTPException(503, "Chưa nhận dạng được giọng nói. Bạn thử lại sau nhé.")
