"""Which products a reply names, so each of them gets its card."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .brands import brand_in_text
from .conversation import _normalized

# Cards one reply may bring.
MAX_NAMED_CARDS = 10

# "... 55P9 - NX.D7USV.001 (i5 13500H, 16GB, 512GB)": a reply usually leaves
# out the configuration, and often the SKU (a single word with a digit).
_CONFIGURATION = re.compile(r"\s*\([^()]*\)\s*$")
_SKU = re.compile(r"\s+[-–—|]\s+(?=\S*\d)\S+\s*$")


def _words(value: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", _normalized(value)).split())


def _spellings(name: str) -> list[str]:
    """Ways a reply writes this name. Shortened ones need a known brand, so
    "Áo thun nam (form rộng)" is not named by every "áo thun nam"."""
    brand = _words(brand_in_text(name))
    forms = [name]
    if brand:
        for pattern in (_CONFIGURATION, _SKU):
            shorter = pattern.sub("", forms[-1])
            if shorter != forms[-1] and len(_words(shorter).split()) >= 3 and brand_in_text(shorter):
                forms.append(shorter)
    result: list[str] = []
    for form in forms:
        words = _words(form).split()
        result.append(" ".join(words))
        if brand:
            first = brand.split()[0]
            tail = words[words.index(first):] if first in words else []
            if len(tail) >= 2:
                result.append(" ".join(tail))
        elif len(words) > 3:
            result.append(" ".join(words[-3:]))
    return [item for item in dict.fromkeys(result) if item]


def named_products(answer: str, products: Iterable[dict]) -> list[str]:
    """Ids of the products the reply names, in its order. A mention inside a
    longer one belongs to the longer name only: naming one configuration by
    its SKU does not name its siblings."""
    text = f" {_words(answer)} "
    names = {str(item["id"]): str(item.get("name") or "") for item in products if item.get("id")}
    spans: list[tuple[int, int, str]] = []
    for product_id, name in names.items():
        for spelling in _spellings(name):
            spans.extend(
                (match.start(), match.end(), product_id)
                for match in re.finditer(rf"(?<= ){re.escape(spelling)}(?= )", text)
            )
    spans.sort(key=lambda item: item[0])
    return list(dict.fromkeys(
        product_id
        for start, end, product_id in spans
        if not any(s <= start and end <= e and e - s > end - start for s, e, _ in spans)
    ))
