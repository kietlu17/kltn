"""Deterministic prompt-injection controls for the Product Agent boundary."""

from __future__ import annotations

import re
import unicodedata


PROMPT_INJECTION_RESPONSE = (
    "Tôi chỉ có thể hỗ trợ tìm hiểu, so sánh và mua sản phẩm bằng các thao tác "
    "được hệ thống cho phép. Bạn hãy cho tôi biết sản phẩm hoặc nhu cầu mua sắm cần hỗ trợ nhé."
)

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)


def normalized_security_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).translate(_ZERO_WIDTH).casefold()
    text = unicodedata.normalize("NFD", text).replace("đ", "d")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip()


_INJECTION_PATTERNS = (
    re.compile(
        r"\b(?:ignore|disregard|forget|override|bypass|bo qua|phot lo|quen|ghi de|vuot qua)\b"
        r".{0,100}\b(?:instruction|instructions|prompt|rules?|policy|system|developer|"
        r"chi dan|huong dan|quy tac|chinh sach|he thong)\b"
    ),
    re.compile(
        r"\b(?:show|reveal|print|repeat|display|dump|expose|cho xem|tiet lo|in ra|doc ra)\b"
        r".{0,100}\b(?:system prompt|developer message|hidden (?:prompt|instruction)|"
        r"prompt he thong|chi dan an|noi dung he thong|api key|secret|password|\.env)\b"
    ),
    re.compile(
        r"\b(?:act as|pretend|roleplay|you are now|dong vai|gia vo|tu bay gio la)\b"
        r".{0,80}\b(?:system|developer|admin|root|unrestricted|khong gioi han|quan tri)\b"
    ),
    re.compile(
        r"\b(?:call|execute|invoke|run|force|goi|thuc thi|chay|ep)\b"
        r".{0,80}\b(?:tool|function|api|shell|command|checkout tool|payment tool|cong cu|lenh)\b"
    ),
    re.compile(r"(?:^|\s)(?:system|developer|assistant)\s*:\s*(?:ignore|override|execute|run|bo qua|thuc thi)\b"),
    re.compile(r"(?:<|\[|\{)\s*(?:system|developer|tool)(?:>|\]|\})"),
    re.compile(r"\b(?:jailbreak|dan mode|developer mode|prompt injection)\b"),
)


def prompt_injection_reasons(value: str) -> list[str]:
    """Return opaque rule identifiers for clear prompt-control attacks."""
    text = normalized_security_text(value)
    return [f"rule_{index}" for index, pattern in enumerate(_INJECTION_PATTERNS, 1) if pattern.search(text)]


def is_prompt_injection(value: str) -> bool:
    return bool(prompt_injection_reasons(value))


def clean_untrusted_text(value: str, limit: int = 1500) -> str:
    """Remove invisible/control characters and bound text stored in model context."""
    text = unicodedata.normalize("NFKC", str(value or "")).translate(_ZERO_WIDTH)
    text = "".join(char for char in text if char in "\n\t" or unicodedata.category(char) != "Cc")
    return re.sub(r"[ \t]+", " ", text).strip()[:limit]


def safe_history(history: list[dict], limit: int = 8) -> list[dict]:
    result = []
    for item in (history or [])[-limit:]:
        role = item.get("role")
        content = clean_untrusted_text(item.get("content", ""), 1000)
        if role not in {"user", "assistant"} or not content or is_prompt_injection(content):
            continue
        result.append({"role": role, "content": content})
    return result


def safe_catalog_candidates(candidates: list[dict]) -> list[dict]:
    """Expose bounded catalog fields and remove instructions embedded in catalog text."""
    safe = []
    limits = {"name": 240, "description": 800, "detail": 1200}
    for candidate in candidates or []:
        item = {
            key: candidate.get(key)
            for key in ("id", "price", "shopId", "sold", "averageRating", "reviewCount")
            if key in candidate
        }
        variants = []
        for variant in (candidate.get("variants") or [])[:20]:
            name = clean_untrusted_text(variant.get("name", ""), 160)
            variants.append({
                key: variant.get(key)
                for key in ("id", "price", "availableStock")
                if key in variant
            } | {
                "name": "[Tên biến thể không đáng tin đã được loại bỏ]" if is_prompt_injection(name) else name
            })
        item["variants"] = variants
        for key, limit in limits.items():
            value = clean_untrusted_text(candidate.get(key, ""), limit)
            item[key] = "[Nội dung catalog không đáng tin đã được loại bỏ]" if is_prompt_injection(value) else value
        safe.append(item)
    return safe


def safe_model_text(value: str, fallback: str, limit: int = 2000) -> str:
    text = clean_untrusted_text(value, limit)
    return fallback if not text or is_prompt_injection(text) else text
