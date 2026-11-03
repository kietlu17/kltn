"""Verified numeric requirements shared by every catalog category."""

import re
import unicodedata


def _normalized(value):
    text = unicodedata.normalize("NFD", str(value or "").casefold()).replace("đ", "d")
    return "".join(char for char in text if not unicodedata.combining(char))


_FIELDS = (
    ("ram", r"ram", ("ram",), "memory"),
    ("storage", r"ssd|o cung|bo nho trong|dung luong luu tru|rom", ("o cung", "bo nho trong", "dung luong luu tru", "rom"), "memory"),
    ("battery", r"pin|dung luong pin", ("dung luong pin", "thong tin pin", "pin"), "mah"),
    ("power", r"cong suat", ("cong suat",), "watt"),
    ("capacity", r"dung tich", ("dung tich",), "volume"),
    ("screen", r"man hinh", ("kich thuoc man hinh", "man hinh"), "inch"),
)
_UNITS = {"memory": r"gb|tb", "mah": r"mah", "watt": r"w", "volume": r"ml|l", "inch": r"inch"}
_QUANTITY = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(tb|gb|mah|ml|inch|w|l)\b")

_INDEX_ALIASES = {
    "ram": ("ram", "bo nho ram"),
    "storage": ("o cung", "ssd", "hdd", "bo nho trong", "dung luong luu tru", "rom"),
    "battery_capacity": ("dung luong pin", "pin", "battery capacity"),
    "battery_energy": ("nang luong pin", "battery energy"),
    "power": ("cong suat", "power"),
    "weight": ("trong luong", "khoi luong", "weight"),
    "screen_size": ("kich thuoc man hinh", "man hinh", "screen size"),
    "refresh_rate": ("tan so quet", "refresh rate"),
}


def _value(number, unit):
    amount = float(number.replace(",", "."))
    return amount * {"tb": 1024, "l": 1000}.get(unit, 1)


def normalized_spec_payload(product):
    """Preserve every specification and add canonical numeric facts for Qdrant."""
    facts = []
    for item in product.get("specifications") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        raw_value = str(item.get("value") or "").strip()
        if not name or not raw_value:
            continue
        normalized_name = _normalized(name)
        key = next((candidate for candidate, aliases in _INDEX_ALIASES.items()
                    if any(alias == normalized_name or alias in normalized_name for alias in aliases)), None)
        if not key:
            key = re.sub(r"[^a-z0-9]+", "_", normalized_name).strip("_")[:100]
        if not key:
            continue
        if key == "battery_capacity" and re.search(r"\bwh\b", _normalized(raw_value)):
            key = "battery_energy"
        fact = {
            "key": key,
            "rawName": name[:200],
            "rawValue": raw_value[:500],
            "normalizedText": _normalized(f"{name}: {raw_value}")[:700],
        }
        match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)", raw_value)
        if match:
            number = float(match.group(1).replace(",", "."))
            combined = _normalized(raw_value)
            unit = ""
            if key in {"ram", "storage"}:
                if re.search(r"\btb\b", combined):
                    number *= 1024
                elif re.search(r"\bmb\b", combined):
                    number /= 1024
                unit = "GB"
            elif key == "battery_capacity":
                if re.search(r"(?<!m)\bah\b", combined):
                    number *= 1000
                unit = "mAh"
            elif key == "battery_energy":
                unit = "Wh"
            elif key == "weight":
                if re.search(r"\bg\b", combined) and not re.search(r"\bkg\b", combined):
                    number /= 1000
                unit = "kg"
            elif key == "screen_size":
                unit = "inch"
            elif key == "refresh_rate":
                unit = "Hz"
            elif key == "power":
                unit = "W"
            if unit:
                fact["numericValue"] = number
                fact["unit"] = unit
        facts.append(fact)
    return facts


def _field_entries(entries, key, names):
    if key == "ram":
        return [(name, value) for name, value in entries
                if _normalized(name).strip() in {"ram", "bo nho ram"}]
    return [(name, value) for name, value in entries
            if "ho tro" not in _normalized(name) and "toi da" not in _normalized(name)
            and any(alias in _normalized(name) for alias in names)]


def parse_spec_requirements(query):
    """Return only explicit, checkable spec limits; ordinary words stay semantic."""
    text = _normalized(query)
    requirements = []
    for key, aliases, _names, unit_kind in _FIELDS:
        units = _UNITS[unit_kind]
        forward = re.search(
            rf"\b(?:{aliases})\b\s*(?P<direction>tu|it nhat|toi thieu|tren|duoi|khong qua|toi da|>=|<=)?\s*"
            rf"(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>{units})\b", text
        )
        reverse = None
        if key in {"ram", "storage"}:
            reverse = re.search(
                rf"\b(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>{units})\s*(?:{aliases})\b", text
            )
        match = forward or reverse
        if not match and key in {"battery", "power", "capacity", "screen"}:
            match = re.search(rf"\b(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>{units})\b", text)
        if not match:
            continue
        direction = match.groupdict().get("direction") or ""
        if not direction:
            prefix = text[max(0, match.start() - 18):match.start()]
            if re.search(r"\b(?:duoi|khong qua|toi da)\s*$", prefix):
                direction = "duoi"
            elif re.search(r"\b(?:khoang|tam|xap xi)\s*$", prefix):
                direction = "near"
        comparison = ("max" if direction in {"duoi", "khong qua", "toi da", "<="}
                      else "near" if direction == "near" or (not direction and key in {"capacity", "screen"})
                      else "min")
        requirements.append((key, comparison,
                             _value(match["number"], match["unit"]), unit_kind))
    return requirements


def matches_spec_requirements(product, requirements, query=""):
    """Unknown or malformed structured specs cannot satisfy a hard requirement."""
    if not requirements:
        return True
    specs = product.get("specifications") or []
    entries = [(item.get("name", ""), item.get("value", "")) for item in specs if isinstance(item, dict)]
    title = str(product.get("name") or "")
    if any(field == "storage" for field, *_ in requirements) and re.search(r"\bssd\b", _normalized(query)):
        if not any("ssd" in _normalized(value) for _name, value in _field_entries(
                   entries, "storage", ("o cung", "bo nho trong", "dung luong luu tru", "rom"))) and "ssd" not in _normalized(title):
            return False
    for key, direction, threshold, unit_kind in requirements:
        names = next(names for field, _aliases, names, _kind in _FIELDS if field == key)
        values = [value for _name, value in _field_entries(entries, key, names)]
        values.append(title)
        measured = None
        for value in values:
            for number, unit in _QUANTITY.findall(_normalized(value)):
                if re.fullmatch(_UNITS[unit_kind], unit):
                    measured = _value(number, unit)
                    break
            if measured is not None:
                break
        if (measured is None or (direction == "min" and measured < threshold)
                or (direction == "max" and measured > threshold)
                or (direction == "near" and abs(measured - threshold) > max(0.1 * threshold, 0.1))):
            return False
    return True


def matching_spec_facts(product, requirements):
    """Return concise structured evidence for the limits the shopper requested."""
    facts = []
    entries = [(item.get("name", ""), item.get("value", ""))
               for item in product.get("specifications") or [] if isinstance(item, dict)]
    for key, _direction, _threshold, unit_kind in requirements:
        names = next(names for field, _aliases, names, _kind in _FIELDS if field == key)
        item = next(((name, value) for name, value in _field_entries(entries, key, names)
                     if any(re.fullmatch(_UNITS[unit_kind], unit)
                            for _number, unit in _QUANTITY.findall(_normalized(value)))), None)
        if item:
            facts.append({"name": str(item[0])[:60], "value": str(item[1])[:100]})
    return facts


def matches_model_reference(product, query):
    """Do not substitute another model for an explicit high-number model name."""
    text = _normalized(query)
    title = _normalized(product.get("name"))
    ignored_heads = {"ram", "ssd", "pin", "gia", "duoi", "tren", "mua", "lay", "size",
                     "co", "lop", "tuoi", "thang", "nam", "cong", "suat", "dung", "luong"}
    ignored_units = {"gb", "tb", "mah", "w", "ml", "l", "inch", "cm", "kg", "hz",
                     "trieu", "nghin", "ngan", "dong", "vnd", "cai", "chiec", "san", "mau"}
    for match in re.finditer(r"\b([a-z][a-z0-9]{2,})\s+(\d{2,4})\b", text):
        head, number = match.groups()
        if head in ignored_heads or int(number) < 50:
            continue
        suffix = re.match(r"\s*([a-z]+)", text[match.end():])
        if suffix and suffix[1] in ignored_units:
            continue
        if not re.search(rf"\b{re.escape(head)}\s+{re.escape(number)}\b", title):
            return False
    return True


def matches_explicit_features(product, query):
    """Reject results that lack a feature the shopper named explicitly."""
    request = _normalized(query)
    title = _normalized(product.get("name"))
    evidence = " ".join(_normalized(value) for value in (
        product.get("name"), product.get("description"),
        *(item.get("value", "") for item in product.get("specifications") or [] if isinstance(item, dict)),
    ))
    if "giu nhiet" in request and "giu nhiet" not in title:
        return False
    alternatives = {
        "chong on": ("chong on", "anc", "active noise cancellation"),
        "chong nuoc": ("chong nuoc", "ipx", "ip67", "ip68"),
        "khong day": ("khong day", "bluetooth", "wireless"),
    }
    for phrase, equivalents in alternatives.items():
        if phrase in request and not any(term in evidence for term in equivalents):
            return False
    return True
