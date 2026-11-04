"""Deterministic parser for plain product searches.

Most marketplace turns are searches such as "tai nghe bluetooth dưới 500k" or
"áo thun nam màu đen size L". Price ranges, colors and sizes in those phrases
are regular enough to parse without a model, so a search can start at once
instead of waiting for the semantic model. Anything that may be a follow-up,
a policy/order/cart request or a reference to listed products returns None
and is left to the model.
"""

from __future__ import annotations

import re
import unicodedata

from .indexer.documents import PRODUCT_TYPES
from .schemas import SemanticConstraint, SemanticTask, SemanticTurn

STRICT_CONFIDENCE = 0.9
# Below the 0.75 execution threshold: the turn runs as an assumed search and
# the answer states the assumption.
LOOSE_CONFIDENCE = 0.55


def _fold_char(char: str) -> str:
    if char == "đ":
        return "d"
    return unicodedata.normalize("NFD", char)[0]


def _fold(value: str) -> str:
    """Accent-free text with the same length as its NFC input, so match
    positions found in the folded text apply to the original."""
    return "".join(_fold_char(char) for char in value)


# Matched on folded text: intents a search parse must never swallow.
_NOT_A_SEARCH = re.compile(
    r"\b(?:"
    r"doi tra|tra hang|hoan tien|bao hanh|chinh sach|van chuyen|giao hang|phi ship|ship"
    r"|thanh toan|voucher|ma giam gia|khuyen mai|don hang|gio hang|dat hang|dat mua"
    r"|mua ngay|them vao|huy don|chot|checkout|so sanh|tai khoan|dia chi"
    r"|xin chao|cam on|tam biet"
    # Requests outside shopping must not turn into a product search when the
    # model is down ("bút viết" stays a search: only "viết cho/một/bài").
    r"|viet cho|viet mot|viet bai|bai tho|lam tho|ke chuyen|dich sang|giai bai|giai giup"
    r"|thoi tiet|tin tuc|lap trinh|cong thuc nau"
    r")\b"
)
# References to products already shown need the conversation, i.e. the model.
_REFERENCE = re.compile(
    r"\b(?:cai|mau|chiec|san pham|con)\s+(?:dau|cuoi|thu\s+\w+|nay|do|kia|tren|vua roi)\b"
    r"|\b(?:no|thu hai|thu ba|so \d)\b"
)
_SEARCH_VERB = re.compile(
    r"\b(?:tim|kiem|can mua|muon xem|goi y|co ban|shop co|ban co|xem)\b"
)

_AMOUNT = r"(\d+(?:[.,]\d+)*)\s*(trieu|nghin|ngan|dong|vnd|tr|cu|k|d)?"
_UNITS = {
    "k": 1_000, "nghin": 1_000, "ngan": 1_000,
    "tr": 1_000_000, "trieu": 1_000_000, "cu": 1_000_000,
    "d": 1, "dong": 1, "vnd": 1,
}
_RANGE = re.compile(rf"(?:\btu\s+)?{_AMOUNT}\s*(?:-|~|den|toi)\s*{_AMOUNT}")
_MAX = re.compile(rf"\b(?:duoi|nho hon|it hon|khong qua|toi da|re hon)\s+{_AMOUNT}")
_MIN = re.compile(rf"\b(?:tren|lon hon|hon|tu|toi thieu)\s+{_AMOUNT}")
_AROUND = re.compile(rf"\b(?:khoang|tam|tam gia|gia)\s+{_AMOUNT}")
# A bare amount with a currency unit ("nồi chiên 1.5 triệu") reads as a budget.
_BARE = re.compile(r"\b(\d+(?:[.,]\d+)*)\s*(k|nghin|ngan|tr|trieu|cu|d|dong|vnd)\b")

# Original (accented) colour words. Ambiguous ones count only after "màu".
_COLORS = (
    "xanh dương", "xanh lá", "xanh navy", "đen", "trắng", "đỏ", "vàng", "hồng",
    "tím", "nâu", "xám", "xanh", "kem",
)
_COLORS_AFTER_MAU = ("cam", "be", "ghi", "bạc", "rêu", "navy")
_SIZE = re.compile(r"\b(?:size|co)\s*(xxxl|4xl|3xl|2xl|xxl|xl|xs|s|m|l|\d{2})\b")
_TRAILING_QUESTION = re.compile(r"\b(?:khong|ko|k|chu|vay)\s*\??\s*$")

# Words without product meaning. Accented forms are unambiguous; an
# unaccented word is dropped only if no product word folds to it the same
# way ("ban" may be "bàn", "gia" may be "gia dụng", "co" may be "cơ").
_FILLER_ACCENTED = {
    "tìm", "kiếm", "cho", "tôi", "mình", "em", "cần", "muốn", "mua", "xem", "gợi",
    "ý", "giúp", "với", "ạ", "à", "nhé", "nha", "shop", "có", "bán", "nào",
    "những", "các", "loại", "cái", "chiếc", "một", "vài", "sản", "phẩm", "hàng",
    "mẫu", "màu", "size", "cỡ", "ơi", "bạn",
    # Function words: a phrase made only of these ("cái gì cũng được") is
    # not a product.
    "gì", "cũng", "được", "đi", "thôi", "là", "thì", "mà", "này", "kia", "đó",
    "ấy", "vậy", "sao", "hả", "nhỉ", "rồi", "đâu", "nữa", "luôn", "hết", "hay",
    "và", "hoặc", "của", "về", "ở", "trong", "nhất", "đẹp", "tốt", "rẻ", "ok",
}
_FILLER_PLAIN = {
    "tim", "kiem", "cho", "toi", "minh", "em", "muon", "mua", "xem", "goi", "y",
    "giup", "voi", "a", "nhe", "nha", "shop", "nao", "nhung", "cac", "loai",
    "chiec", "mot", "vai", "san", "pham", "mau", "size", "oi",
    "gi", "cung", "duoc", "thoi", "thi", "vay", "sao", "nhi", "roi", "dau", "nua",
    "luon", "hoac", "cua", "trong", "nhat", "ok",
}

# Shop-chat abbreviations, expanded before the phrase and query are built so
# keyword search and category resolution see the full word.
_ALIASES = {
    "ip": "iphone", "ss": "samsung", "dt": "điện thoại", "đt": "điện thoại",
    "ko": "không", "k": "không", "tn": "tai nghe", "lap": "laptop",
}


def _expand_aliases(text: str) -> str:
    return re.sub(
        r"(?<!\w)(" + "|".join(re.escape(key) for key in _ALIASES) + r")(?!\w)",
        lambda match: _ALIASES[match.group(1)],
        text,
    )


_POLICY = re.compile(
    r"\b(?:doi tra|tra hang|hoan tien|bao hanh|chinh sach|van chuyen|giao hang|phi ship"
    r"|phi van chuyen|thanh toan|bao lau|kiem hang|dong kiem)\b"
)
_PERSONAL = re.compile(r"\b(?:don hang|don cua|gio hang|ma don|huy don|dat hang)\b")


def parse_policy_turn(message: str) -> SemanticTurn | None:
    """A policy question ("chính sách đổi trả thế nào") answered from the
    policy documents; questions about the customer's own order or cart are
    left to the model."""
    folded = _fold(unicodedata.normalize("NFC", message.casefold()))
    if not _POLICY.search(folded) or _PERSONAL.search(folded) or _REFERENCE.search(folded):
        return None
    if _SEARCH_VERB.search(folded):
        # "tìm balo và hỏi chính sách bảo hành" has two tasks: the model splits them.
        return None
    return SemanticTurn(
        tasks=[SemanticTask(intent="policy", query=message.strip())],
        conversation_action="new",
        focus_update="keep",
        confidence=STRICT_CONFIDENCE,
    )


def _money(number: str, unit: str | None) -> float | None:
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", number):
        value = float(re.sub(r"[.,]", "", number))
    else:
        value = float(number.replace(",", "."))
    value *= _UNITS.get(unit or "", 1)
    # A bare small number ("áo 2 lớp", "iphone 13") is not a price.
    return value if value >= 1_000 else None


def _price(folded: str) -> tuple[float | None, float | None, list[tuple[int, int]]]:
    """(min, max, matched spans) for the first price expression found."""
    match = _RANGE.search(folded)
    if match:
        low = _money(match.group(1), match.group(2) or match.group(4))
        high = _money(match.group(3), match.group(4))
        if low is not None and high is not None and low <= high:
            return low, high, [match.span()]
    match = _MAX.search(folded)
    if match and (value := _money(match.group(1), match.group(2))) is not None:
        return None, value, [match.span()]
    match = _AROUND.search(folded)
    if match and (value := _money(match.group(1), match.group(2))) is not None:
        return round(value * 0.8), round(value * 1.2), [match.span()]
    match = _MIN.search(folded)
    if match and (value := _money(match.group(1), match.group(2))) is not None:
        return value, None, [match.span()]
    match = _BARE.search(folded)
    if match and (value := _money(match.group(1), match.group(2))) is not None:
        return round(value * 0.8), round(value * 1.2), [match.span()]
    return None, None, []


_NEGATION_BEFORE = re.compile(
    r"(?:không phải|không lấy|không muốn|không thích|không chọn|ngoại trừ|trừ|tránh)\s+(?:là\s+)?$"
)


def _color_matches(original: str) -> list[tuple[str, tuple[int, int], bool]]:
    """(color, span, negated) for each colour mentioned; "không phải màu đen"
    is a negated mention whose span covers the negation words too."""
    found: list[tuple[str, tuple[int, int], bool]] = []
    candidates = [(color, rf"(?:màu\s+)?{re.escape(color)}") for color in _COLORS]
    candidates += [(color, rf"màu\s+{re.escape(color)}") for color in _COLORS_AFTER_MAU]
    for color, pattern in candidates:
        match = re.search(rf"(?<!\w){pattern}(?!\w)", original)
        if not match or any(start < match.end() and match.start() < end for _c, (start, end), _n in found):
            continue
        negation = _NEGATION_BEFORE.search(original[:match.start()])
        start = negation.start() if negation else match.start()
        found.append((color, (start, match.end()), bool(negation)))
    return found


def _colors(original: str) -> tuple[list[str], list[tuple[int, int]]]:
    matches = _color_matches(original)
    return [color for color, _span, negated in matches if not negated], [span for _c, span, _n in matches]


# The catalog's brand field is mostly empty or scraped description text, so
# brands are recognised from the message and matched against product names.
_BRANDS = (
    "sony", "apple", "iphone", "ipad", "macbook", "airpods", "samsung", "xiaomi", "redmi",
    "oppo", "vivo", "realme", "nokia", "huawei", "honor", "jbl", "marshall", "anker",
    "baseus", "ugreen", "logitech", "razer", "akko", "dareu", "rapoo", "asus", "dell",
    "hp", "lenovo", "acer", "msi", "havit", "soundpeats", "edifier", "philips",
    "panasonic", "sharp", "toshiba", "lg", "canon", "sunhouse", "tefal", "casio",
    "nike", "adidas", "puma", "converse", "vans", "muji", "yody", "uniqlo", "zara",
)


def _brand(folded: str) -> str:
    return next(
        (brand for brand in _BRANDS if re.search(rf"(?<!\w){re.escape(brand)}(?!\w)", folded)),
        "",
    )


def _normalize_message(message: str) -> tuple[str, str]:
    original = re.sub(r"\s+", " ", unicodedata.normalize("NFC", message.casefold())).strip()
    # A trailing "ko"/"k" is the question particle, not "không" in a name.
    original = _expand_aliases(re.sub(r"\s+(?:ko|k)\s*\??\s*$", " không", original)).strip()
    return original, _fold(original)


def mentions_other_product(message: str) -> bool:
    """True when a short reply names a product kind or negates something,
    so it cannot be a plain variant pick ("màu đen", "size L")."""
    original, folded = _normalize_message(message)
    return _known_product_type(folded) or bool(
        re.search(r"(?:khong phai|khong lay|khong muon|ngoai tru|tru)", folded)
    )


def reconcile_turn(turn: SemanticTurn, message: str) -> SemanticTurn:
    """Correct the model's search constraints with what the text states
    unambiguously: prices ("dưới 20 triệu" read as 20), negated colours
    ("không phải màu đen" read as đen) and brand names it left in the query."""
    original, folded = _normalize_message(message)
    min_price, max_price, _spans = _price(folded)
    negated = {_fold(color) for color, _span, is_negated in _color_matches(original) if is_negated}
    brand = _brand(folded)
    if min_price is None and max_price is None and not negated and not brand:
        return turn
    turn = turn.model_copy(deep=True)
    for task in turn.tasks:
        if task.intent != "product_search":
            continue
        constraints = []
        for constraint in task.constraints:
            key = constraint.key.casefold()
            if key in {"price", "min_price", "max_price"} and (min_price is not None or max_price is not None):
                continue
            if negated and key in {"color", "colors", "variant.color"}:
                values = constraint.value if isinstance(constraint.value, list) else [constraint.value]
                kept = [value for value in values if _fold(str(value).casefold()) not in negated]
                if not kept:
                    continue
                constraint = constraint.model_copy(update={"value": kept})
            constraints.append(constraint)
        if max_price is not None:
            constraints.append(SemanticConstraint(key="price", operator="lte", value=max_price, unit="VND"))
        if min_price is not None:
            constraints.append(SemanticConstraint(key="price", operator="gte", value=min_price, unit="VND"))
        if brand and not any(item.key.casefold() == "brand" for item in constraints):
            constraints.append(SemanticConstraint(key="brand", operator="eq", value=brand))
        task.constraints = constraints
    return turn


def _known_product_type(folded: str) -> bool:
    return any(
        re.search(r"(?<!\w)" + re.escape(term.strip()) + r"(?!\w)", folded)
        for _product_type, terms in PRODUCT_TYPES
        for term in terms
    )


def parse_search_turn(
    message: str, *, active_product_id: str = "", strict: bool = True
) -> SemanticTurn | None:
    """A product_search turn for a plain search phrase, or None.

    strict=True only accepts phrases with a clear search signal and is safe
    to act on before the model answers. strict=False is the fallback when the
    model is unavailable: any short noun phrase becomes an assumed search.
    """
    original, folded = _normalize_message(message)
    if not folded or len(folded) > 200:
        return None
    if _NOT_A_SEARCH.search(folded) or _REFERENCE.search(folded):
        return None
    explicit_verb = bool(_SEARCH_VERB.search(folded))
    if active_product_id and not explicit_verb:
        # With a product in focus, "màu đen size L" is a variant pick.
        return None

    min_price, max_price, removed = _price(folded)
    colors, color_spans = _colors(original)
    removed += color_spans
    sizes = []
    for match in _SIZE.finditer(folded):
        sizes.append(match.group(1).upper())
        removed.append(match.span())
    trailing = _TRAILING_QUESTION.search(folded)
    if trailing:
        removed.append(trailing.span())

    kept = list(original)
    for start, end in removed:
        kept[start:end] = " " * (end - start)
    words = [
        word for word in re.findall(r"\w+", "".join(kept))
        if word not in _FILLER_ACCENTED
        and not (word == _fold(word) and word in _FILLER_PLAIN)
    ]
    core_tokens = [_fold(word) for word in words]
    if not words or len(words) > 8 or not any(len(token) >= 2 for token in core_tokens):
        return None
    has_constraint = bool(min_price or max_price or colors or sizes)
    if strict and not (explicit_verb or has_constraint or _known_product_type(" ".join(core_tokens))):
        return None

    constraints = [SemanticConstraint(key="product_type", operator="eq", value=" ".join(words))]
    if max_price is not None:
        constraints.append(SemanticConstraint(key="price", operator="lte", value=max_price, unit="VND"))
    if min_price is not None:
        constraints.append(SemanticConstraint(key="price", operator="gte", value=min_price, unit="VND"))
    if colors:
        constraints.append(SemanticConstraint(key="color", operator="any", value=colors))
    if sizes:
        constraints.append(SemanticConstraint(key="size", operator="any", value=list(dict.fromkeys(sizes))))
    if brand := _brand(folded):
        constraints.append(SemanticConstraint(key="brand", operator="eq", value=brand))
    return SemanticTurn(
        tasks=[SemanticTask(intent="product_search", query=original, constraints=constraints)],
        conversation_action="new",
        focus_update="replace",
        confidence=STRICT_CONFIDENCE if strict else LOOSE_CONFIDENCE,
    )
