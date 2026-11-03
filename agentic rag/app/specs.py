from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .schemas import SemanticConstraint


def _normalized(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or "").casefold()).replace("đ", "d")
    return "".join(char for char in text if not unicodedata.combining(char))


_KEY_ALIASES = {
    "ram": ("ram", "bo nho ram"),
    "storage": ("o cung", "ssd", "hdd", "bo nho trong", "dung luong luu tru", "rom"),
    "battery_capacity": ("dung luong pin", "pin", "battery capacity"),
    "battery_energy": ("nang luong pin", "battery energy"),
    "power": ("cong suat", "power"),
    "weight": ("trong luong", "khoi luong", "weight"),
    "screen_size": ("kich thuoc man hinh", "man hinh", "screen size"),
    "refresh_rate": ("tan so quet", "refresh rate"),
}


def canonical_spec_key(value: str) -> str | None:
    normalized = _normalized(value)
    for key, aliases in _KEY_ALIASES.items():
        if any(alias == normalized or alias in normalized for alias in aliases):
            return key
    candidate = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return candidate[:100] or None


def _first_number(value: str) -> float | None:
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def canonical_numeric(key: str, value: str | float, unit: str = "") -> tuple[float | None, str]:
    number = float(value) if isinstance(value, (int, float)) else _first_number(value)
    if number is None:
        return None, ""
    combined = _normalized(f"{value} {unit}")
    if key in {"ram", "storage"}:
        if re.search(r"\btb\b", combined):
            number *= 1024
        elif re.search(r"\bmb\b", combined):
            number /= 1024
        return number, "GB"
    if key == "battery_capacity":
        if re.search(r"(?<!m)\bah\b", combined):
            number *= 1000
        return number, "mAh"
    if key == "battery_energy":
        return number, "Wh"
    if key == "weight":
        if re.search(r"\bg\b", combined) and not re.search(r"\bkg\b", combined):
            number /= 1000
        return number, "kg"
    if key == "screen_size":
        return number, "inch"
    if key == "refresh_rate":
        return number, "Hz"
    if key == "power":
        return number, "W"
    return number, unit.strip()


def normalize_specifications(specifications: list[dict]) -> list[dict]:
    facts: list[dict] = []
    for item in specifications or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        raw_value = str(item.get("value") or "").strip()
        if not name or not raw_value:
            continue
        key = canonical_spec_key(name)
        if not key:
            continue
        if key == "battery_capacity" and re.search(r"\bwh\b", _normalized(raw_value)):
            key = "battery_energy"
        numeric, unit = canonical_numeric(key, raw_value)
        fact = {
            "key": key,
            "rawName": name,
            "rawValue": raw_value,
            "normalizedText": _normalized(f"{name}: {raw_value}"),
        }
        if numeric is not None:
            fact["numericValue"] = numeric
            fact["unit"] = unit
        facts.append(fact)
    return facts


def normalize_constraint(constraint: SemanticConstraint) -> SemanticConstraint:
    key = canonical_spec_key(constraint.key) or constraint.key
    if key == "battery_capacity" and re.search(
        r"\bwh\b", _normalized(f"{constraint.value} {constraint.unit}")
    ):
        key = "battery_energy"
    payload = constraint.model_dump()
    payload["key"] = key
    if not isinstance(constraint.value, list):
        numeric, unit = canonical_numeric(key, constraint.value, constraint.unit)
        if numeric is not None and key in _KEY_ALIASES:
            payload["value"] = numeric
            payload["unit"] = unit
    return SemanticConstraint.model_validate(payload)


def _compare(actual: float, expected: float, operator: str) -> bool:
    return {
        "eq": abs(actual - expected) <= max(abs(expected) * 0.01, 1e-9),
        "lt": actual < expected,
        "lte": actual <= expected,
        "gt": actual > expected,
        "gte": actual >= expected,
    }.get(operator, False)


@dataclass(frozen=True)
class ConstraintVerdict:
    verdict: str
    evidence: tuple[str, ...] = ()
    reason: str = ""


def verify_spec_constraints(product: dict, constraints: list[SemanticConstraint]) -> ConstraintVerdict:
    if not constraints:
        return ConstraintVerdict("match")
    facts = normalize_specifications(product.get("specifications") or [])
    evidence: list[str] = []
    unknown_soft = False
    for raw_constraint in constraints:
        constraint = normalize_constraint(raw_constraint)
        matching = [fact for fact in facts if fact["key"] == constraint.key]
        if not matching:
            if constraint.strength == "hard":
                return ConstraintVerdict("unknown", tuple(evidence), f"Thiếu dữ liệu {constraint.key}")
            unknown_soft = True
            continue
        satisfied = False
        for fact in matching:
            if isinstance(constraint.value, (int, float)) and "numericValue" in fact:
                satisfied = _compare(float(fact["numericValue"]), float(constraint.value), constraint.operator)
            else:
                expected_values = constraint.value if isinstance(constraint.value, list) else [constraint.value]
                haystack = _normalized(fact["rawValue"])
                if constraint.operator == "contains":
                    satisfied = all(_normalized(str(value)) in haystack for value in expected_values)
                else:
                    satisfied = any(_normalized(str(value)) in haystack for value in expected_values)
            if satisfied:
                evidence.append(f"{fact['rawName']}: {fact['rawValue']}")
                break
        if not satisfied and constraint.strength == "hard":
            return ConstraintVerdict("no_match", tuple(evidence), f"Không thỏa {constraint.key}")
        if not satisfied:
            unknown_soft = True
    return ConstraintVerdict("unknown" if unknown_soft else "match", tuple(evidence))


def requires_semantic_verifier(constraints: list[SemanticConstraint]) -> bool:
    for constraint in constraints:
        key = canonical_spec_key(constraint.key)
        if key not in _KEY_ALIASES or constraint.operator == "contains":
            return True
    return False
