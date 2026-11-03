"""Deterministic BM25 sparse vectors for Vietnamese catalog text.

Shared by app.indexer and the retriever: both sides must hash tokens the
same way, so changing tokenisation requires a new collection. Qdrant applies
IDF at query time through ``Modifier.IDF``, so documents carry only the
length-normalised term frequency and queries carry unit weights.
"""

from __future__ import annotations

import re
import unicodedata
import zlib

SPARSE_VECTOR_NAME = "bm25"
_K1 = 1.2
_B = 0.75
_AVERAGE_TOKENS = 120.0


def sparse_tokens(text: str) -> list[str]:
    """Diacritic-folded syllables plus adjacent-syllable bigrams.

    Vietnamese words are usually two syllables ("điện thoại"), so bigrams
    keep compound words distinguishable without a word segmenter. No stop
    words are removed: folded syllables such as "do" (đỏ) carry meaning.
    """
    folded = unicodedata.normalize("NFD", str(text or "").casefold()).replace("đ", "d")
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    syllables = re.findall(r"[a-z0-9]+", folded)
    bigrams = [f"{left}_{right}" for left, right in zip(syllables, syllables[1:])]
    return [*syllables, *bigrams]


def _index(token: str) -> int:
    return zlib.crc32(token.encode("utf-8")) & 0x7FFFFFFF


def _vector(weights: dict[int, float]) -> dict[str, list]:
    indices = sorted(weights)
    return {"indices": indices, "values": [weights[index] for index in indices]}


def document_sparse_vector(text: str) -> dict[str, list]:
    tokens = sparse_tokens(text)
    if not tokens:
        return {"indices": [], "values": []}
    counts: dict[int, int] = {}
    for token in tokens:
        index = _index(token)
        counts[index] = counts.get(index, 0) + 1
    length_norm = 1 - _B + _B * len(tokens) / _AVERAGE_TOKENS
    return _vector(
        {
            index: count * (_K1 + 1) / (count + _K1 * length_norm)
            for index, count in counts.items()
        }
    )


def query_sparse_vector(text: str) -> dict[str, list]:
    return _vector({_index(token): 1.0 for token in sparse_tokens(text)})
