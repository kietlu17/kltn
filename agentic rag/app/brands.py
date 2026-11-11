"""Brand recognition shared by the indexer and the query side.

Listings in this catalog carry no brand field: the brand sits in the name
("Loa Bluetooth JBL Clip 5"), sometimes only as a product line ("iPhone 15",
"Galaxy A35", "Redmi 13"). The same canonical names are used when indexing
the payload and when resolving the brand a customer typed, so "iphone",
"apple" and "Apple" all filter on "Apple".

Entries were taken from the brands that occur in the catalog's names; add a
line when a new brand arrives. Aliases are matched as whole words on text
without diacritics.
"""

from __future__ import annotations

import re
import unicodedata

# canonical name -> aliases (lower case, no diacritics); the canonical name
# itself is always an alias.
BRANDS: dict[str, tuple[str, ...]] = {
    "Apple": ("iphone", "ipad", "macbook", "airpods", "earpods", "apple watch", "imac"),
    "Samsung": ("galaxy",),
    "Xiaomi": ("redmi", "poco", "mi band"),
    "JBL": (),
    "Sony": (),
    "Dell": ("inspiron", "vostro", "latitude", "alienware"),
    "Asus": ("vivobook", "zenbook", "rog", "tuf gaming"),
    "OPPO": (),
    "HP": ("omnibook", "pavilion", "victus", "elitebook", "probook"),
    "Acer": ("aspire", "nitro", "predator"),
    "Lenovo": ("ideapad", "thinkpad", "thinkbook", "legion"),
    "Havit": (),
    "MUJI": (),
    "Alpha Works": (),
    "AVA+": (),
    "Baseus": (),
    "Marshall": (),
    "realme": (),
    "Motorola": (),
    "Rezo": (),
    "Harman Kardon": (),
    "vivo": (),
    "Monster": (),
    "Honor": (),
    "LG": (),
    "GIGABYTE": (),
    "MSI": (),
    "Dalton": (),
    "Nothing": ("nothing phone", "nothing ear", "cmf"),
    "Hoco": (),
    "Anker": ("soundcore",),
    "Logitech": (),
    "Razer": (),
    "Wooting": (),
    "New4all": (),
    "Huawei": (),
    "Nokia": (),
    "Tecno": (),
    "Infinix": (),
    "Bose": (),
    "Sennheiser": (),
    "Edifier": (),
    "Philips": (),
    "Sharp": (),
    "Toshiba": (),
    "Panasonic": (),
    "Sunhouse": (),
    "Yody": (),
    "Yoguu": (),
    "MRM Manlywear": ("manlywear",),
    "Novelty": (),
    "May 10": (),
    "Davie": (),
    "Kito": (),
    "Uniqlo": (),
    "Nike": (),
    "Adidas": (),
    "Biti's": ("bitis",),
    "Hyundai": (),
    "AKKO": (),
    "Rockspace": (),
    "WIWU": (),
    "EDRA": (),
    "RiBi": (),
    "Thonet & Vander": (),
    "SingPC": (),
}

# Brands whose own name is an ordinary word: only their aliases count.
_ALIAS_ONLY = {"Nothing"}

# Values a listing uses for "no brand".
_NO_BRAND = {"oem", "no brand", "khong thuong hieu", "khac", "other", "dang cap nhat"}


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value).casefold()).replace("đ", "d")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[’`]", "'", text)


def _pattern(alias: str) -> re.Pattern:
    return re.compile(rf"(?<![\w+]){re.escape(alias)}(?![\w+])")


_PATTERNS: list[tuple[str, re.Pattern, bool]] = [
    (canonical, _pattern(alias), alias != _fold(canonical))
    for canonical, aliases in BRANDS.items()
    for alias in (
        aliases if canonical in _ALIAS_ONLY else (_fold(canonical), *aliases)
    )
]
# "Ốp lưng cho iPhone", "túi đựng laptop, macbook": a product line named as
# what an accessory fits is not the accessory's brand.
_FITS = re.compile(r"(?:cho|for|tuong thich|phu hop|dung|kieu|loai|,)\s*$")
_BY_KEY = {
    re.sub(r"[^a-z0-9+]", "", alias): canonical
    for canonical, aliases in BRANDS.items()
    for alias in (_fold(canonical), *aliases)
}


def brand_in_text(text: str) -> str:
    """The known brand named earliest in the text (a product name), or ""."""
    folded = _fold(text)
    best: tuple[int, int, str] | None = None
    for canonical, pattern, is_alias in _PATTERNS:
        match = pattern.search(folded)
        if match and is_alias:
            before = folded[: match.start()]
            # A product line ("iPhone 17", "Galaxy A35") leads the name; deep
            # in the name, or after "cho", it is what an accessory fits.
            if len(before.split()) > 4 or _FITS.search(before):
                continue
        if match:
            # Earliest wins; on a tie the longer alias ("harman kardon").
            rank = (match.start(), -len(match.group(0)), canonical)
            if best is None or rank < best:
                best = rank
    return best[2] if best else ""


def canonical_brand(value: str) -> str:
    """A brand as the customer or a listing wrote it, in canonical form:
    "iphone" -> "Apple", "jbl" -> "JBL". Unknown brands come back trimmed,
    "OEM" and the like come back empty."""
    text = str(value or "").strip()
    if not text or _fold(text) in _NO_BRAND:
        return ""
    key = re.sub(r"[^a-z0-9+]", "", _fold(text))
    return _BY_KEY.get(key) or brand_in_text(text) or text


_STATED = re.compile(
    r"(?<!xuat xu )(?<!xuat xu cua )thuong hieu\s*[:\-]\s*(.{1,60})",
)
# Labels that follow the brand in scraped specification text.
_NEXT_LABEL = re.compile(
    r"\s*(?:xuat xu|goi y|model|chat lieu|kieu dang|san pham|ten don vi|dia chi|loai |\*|\||;|\.|,)"
)


def stated_brand(text: str) -> str:
    """The brand a description states ("Thương hiệu: Caliven Keni Gợi ý...")
    cut before the next label; "" for OEM or when none is stated. The
    original casing is kept by mapping the folded span back."""
    folded = _fold(text)
    for match in _STATED.finditer(folded):
        span = match.group(1)
        end = _NEXT_LABEL.search(span)
        value_folded = (span[: end.start()] if end else span).strip()
        words = value_folded.split()
        if not words or len(words) > 4:
            continue
        start = match.start(1)
        original = str(text)[start: start + len(value_folded)].strip()
        brand = canonical_brand(original if _fold(original) == value_folded else value_folded)
        if brand:
            return brand
    return ""
