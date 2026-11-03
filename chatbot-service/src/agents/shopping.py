"""Update explicit shopping requirements without deriving them from assistant replies."""
import re

from ..product.catalog import infer_product_type, normalized_text
from .state import explicit_price_limits


MEASUREMENTS = ("foot_length_cm", "height_cm", "weight_kg", "bust_cm")
PRODUCT_LABELS = {
    "tat": "tất", "ao_so_mi": "áo sơ mi", "ao_thun": "áo thun", "ao_khoac": "áo khoác",
    "quan": "quần", "giay": "giày/dép", "balo": "balo", "tai_nghe": "tai nghe",
}
SIZE_QUESTION = re.compile(
    r"\b(?:size|kich thuoc|so do|vua|mac duoc|mang duoc|sock size)\b"
    r"|\bco (?:nao|bao nhieu|vua)\b"
)
FOLLOWUP = re.compile(
    r"\b(?:mau|size|gia|duoi|tren|khong qua|toi da|toi thieu|nam|nu|unisex|"
    r"phu hop|hop voi|van phong|di lam|di hoc|du lich|the thao|chong nuoc|"
    r"uu tien|kieu|phong cach|thuong hieu|re hon|dat hon|nho hon|lon hon|"
    r"nhung|dang hoi|mau nay|mau do|con hang)\b"
)


def shopping_description(plan: dict) -> str:
    product = PRODUCT_LABELS.get(plan.get("product_type"), "sản phẩm")
    audience = {"nam": "nam", "nu": "nữ", "tre_em": "trẻ em", "unisex": "unisex"}.get(plan.get("audience"), "")
    terms = ", ".join(plan.get("variant_terms") or [])
    return " ".join(part for part in (product, audience, terms) if part)


def sizing_clarification(plan: dict) -> str | None:
    """Never invent a garment-size conversion from body measurements."""
    if plan.get("dialogue_act") != "size_advice":
        return None
    description = shopping_description(plan)
    if plan.get("product_type") in {"tat", "giay"} and plan.get("foot_length_cm") is None:
        return f"Bạn cho mình biết chiều dài bàn chân tính bằng cm để kiểm tra size {description} phù hợp nhé."
    body = [("height_cm", "chiều cao", "cm"), ("weight_kg", "cân nặng", "kg"), ("bust_cm", "vòng ngực", "cm")]
    recorded = [f"{label} {plan[key]:g}{unit}" for key, label, unit in body if plan.get(key) is not None]
    if recorded and plan.get("product_type") not in {"tat", "giay"}:
        return (f"Mình đã ghi nhận {', '.join(recorded)} để chọn {description}. "
                "Mình chưa thể xác nhận size S/M/L chỉ từ các số đo này; cần đối chiếu bảng size riêng của mẫu bạn chọn. "
                "Bạn muốn kiểm tra mẫu nào?")
    return None


def explicit_audience(message: str) -> str | None:
    text = normalized_text(message)
    # Corrections such as 'không phải nữ, tôi là nam' use the positive clause.
    text = re.sub(r"\b(?:khong(?: phai)?|not)\s+(?:nam|nu|men|women|male|female)\b", "", text)
    matches = list(re.finditer(r"\b(tre em|kids?|unisex|nu|women|female|nam|men|male)\b", text))
    if not matches:
        return None
    token = matches[-1].group(1)
    if token in {"nu", "women", "female"}:
        return "nu"
    if token in {"nam", "men", "male"}:
        return "nam"
    return "unisex" if token == "unisex" else "tre_em"


def explicit_measurements(message: str, product_type: str | None) -> dict:
    text = normalized_text(message).replace(",", ".")
    values = {}
    patterns = {
        "weight_kg": (r"\b(\d{1,3}(?:\.\d+)?)\s*kg\b", 2, 400),
        "bust_cm": (r"\b(?:vong nguc|nguc|bust)\s*(?:la\s*)?(\d{2,3}(?:\.\d+)?)\s*(?:cm)?\b", 30, 250),
        "height_cm": (r"\b(?:cao|height)\s*(?:la\s*)?(\d{2,3}(?:\.\d+)?)\s*cm\b", 40, 250),
    }
    for key, (pattern, low, high) in patterns.items():
        match = re.search(pattern, text)
        if match and low <= float(match[1]) <= high:
            values[key] = float(match[1])
    if "height_cm" not in values and not re.search(r"\b(?:nguc|bust|eo|waist|mong|hip)\b", text):
        bare_height = re.search(r"\b(\d{3}(?:\.\d+)?)\s*cm\b", text)
        if bare_height and 40 <= float(bare_height[1]) <= 250:
            values["height_cm"] = float(bare_height[1])
    height = re.search(r"\b([12])m(\d{1,2})\b|\b([12]\.\d{1,2})\s*m\b", text)
    if height:
        value = (int(height[1]) * 100 + int(height[2].ljust(2, "0"))
                 if height[1] else float(height[3]) * 100)
        if 40 <= value <= 250:
            values["height_cm"] = value
    foot = re.search(r"\b(\d{1,2}(?:\.\d+)?)\s*cm\b", text)
    if foot and (product_type in {"tat", "giay"} or re.search(r"\b(?:chan|foot|feet)\b", text)):
        if not re.search(r"\b(?:cao|height|nguc|bust)\b", text) and 5 <= float(foot[1]) <= 50:
            values["foot_length_cm"] = float(foot[1])
    return values


def update_shopping_plan(message: str, previous: dict, current: dict, terms: list[str], colors: set[str]) -> dict:
    """Merge refinements, replace explicit slots, and reset on an explicit new topic."""
    text = normalized_text(message)
    old_query = previous.get("query", "")
    old_type = previous.get("product_type") or infer_product_type(old_query)
    new_type = infer_product_type(message)
    product_type = new_type if new_type != "khac" else old_type
    measurements = explicit_measurements(message, product_type)
    audience = explicit_audience(message)
    sizing = bool(measurements or SIZE_QUESTION.search(text))
    different_type = new_type != "khac" and new_type != old_type
    new_search = bool(re.search(r"\b(?:tim|mua|chuyen sang|doi sang|find|buy)\b", text))
    followup = bool(old_query and not different_type and (
        new_type != "khac" or sizing or audience or terms or FOLLOWUP.search(text)
    ))
    # Unknown explicit product searches must not inherit the old category.
    if new_search and new_type == "khac" and not (terms or measurements) and not re.search(r"\b(?:mau nay|tuong tu)\b", text):
        followup = False
    if current.get("intent") == "clarify" or current.get("reference_product_id"):
        followup = False
    merged = dict(current)
    if followup:
        for key in ("product_type", "audience", "dialogue_act", "sizing_product_id", *MEASUREMENTS, "min_price", "max_price"):
            merged[key] = previous.get(key, merged.get(key))
        merged["product_type"] = old_type if old_type != "khac" else None
        merged["audience"] = previous.get("audience") or explicit_audience(old_query)
        prior_terms = list(previous.get("variant_terms") or [])
        if any(term in colors for term in terms):
            prior_terms = [term for term in prior_terms if term not in colors]
        if any(term not in colors for term in terms):
            prior_terms = [term for term in prior_terms if term in colors]
        merged["variant_terms"] = list(dict.fromkeys([*prior_terms, *terms]))[:8]
        # Body measurements stay in typed fields, not in semantic search text.
        query = old_query
        if audience and audience != merged.get("audience"):
            query = " ".join(word for word in query.split() if normalized_text(word).strip(";,.")
                             not in {"nam", "nu", "men", "women", "male", "female", "unisex"})
        if any(term in colors for term in terms):
            removed = {normalized_text(term) for term in previous.get("variant_terms", []) if term in colors and term not in terms}
            query = " ".join(word for word in query.split() if normalized_text(word).strip(";,.") not in removed)
        if not sizing and normalized_text(message) not in normalized_text(query):
            query = f"{query}; {message}"
        merged["query"] = query[:1500]
        if previous.get("intent") == "similar":
            merged.update(intent="similar", reference_product_id=previous.get("reference_product_id"))
    else:
        merged["product_type"] = new_type if new_type != "khac" else None
        merged["audience"] = None
        merged["dialogue_act"] = "search"
    if audience:
        merged["audience"] = audience
    merged.update(measurements)
    merged.update(explicit_price_limits(message))
    if sizing:
        merged["dialogue_act"] = "size_advice"
    # Old checkpoints predate these optional fields.
    merged["dialogue_act"] = merged.get("dialogue_act") or "search"
    return merged
