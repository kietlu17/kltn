"""Compare product embedding layouts on the same catalog snapshot and queries.

Read-only for the live catalog and Qdrant. Embeddings and results go to /data.
Run with: python -m src.scripts.benchmark_chunking
"""

import asyncio
import hashlib
import json
import logging
import math
import os
import random
import re
import sqlite3
from pathlib import Path

import numpy as np

from ..core.settings import Settings
from ..infrastructure.clients import CatalogAPI
from ..infrastructure.models import ModelClients
from ..product.catalog import (
    VectorCatalog, image_records, normalized_text, plain_text, point_id, product_document,
    product_metadata, query_metadata,
)


QUERIES = (
    ("áo thun nam màu đen", "ao_thun", "nam", "den"),
    ("áo thun nam màu trắng", "ao_thun", "nam", "trang"),
    ("áo thun nữ màu đen", "ao_thun", "nu", "den"),
    ("áo thun nữ màu trắng", "ao_thun", "nu", "trang"),
    ("áo khoác nam màu đen", "ao_khoac", "nam", "den"),
    ("áo khoác nữ màu đen", "ao_khoac", "nu", "den"),
    ("quần nam màu đen", "quan", "nam", "den"),
    ("quần nữ màu đen", "quan", "nu", "den"),
    ("áo sơ mi nam màu trắng", "ao_so_mi", "nam", "trang"),
)


def _unit(vector):
    values = np.asarray(vector, dtype=np.float32)
    norm = np.linalg.norm(values)
    return values / norm if norm else values


def _relevant(product, product_type, gender, color):
    name = normalized_text(product.get("name", ""))
    inferred_type = product_metadata(product)["productType"]
    if inferred_type != product_type and not (
        product_type == "ao_thun" and re.search(r"\b(?:ao thun|ao phong|tshirt|t shirt|polo)\b", name)
    ):
        return False
    if "tre em" in name or "be trai" in name or "be gai" in name:
        return False
    opposite = "nu" if gender == "nam" else "nam"
    if re.search(rf"\b{opposite}\b", name) and not re.search(rf"\b{gender}\b|\bunisex\b", name):
        return False
    if not re.search(rf"\b{gender}\b|\bunisex\b", name):
        return False
    variants = product.get("variants") or []
    color_terms = {"den": ("den", "black"), "trang": ("trang", "white")}.get(color, (color,))
    color_pattern = r"\b(?:" + "|".join(map(re.escape, color_terms)) + r")\b"
    sources = [variant.get("name", "") for variant in variants] if variants else [product.get("name", "")]
    return any(re.search(color_pattern, normalized_text(source)) for source in sources)


def _metrics(ordered, relevant):
    top6, top10 = ordered[:6], ordered[:10]
    dcg = sum(1 / math.log2(index + 2) for index, pid in enumerate(top10) if pid in relevant)
    ideal = sum(1 / math.log2(index + 2) for index in range(min(10, len(relevant))))
    return {
        "precisionAt6": sum(pid in relevant for pid in top6) / 6,
        "recallAt10": sum(pid in relevant for pid in top10) / len(relevant),
        "ndcgAt10": dcg / ideal if ideal else 0,
    }


def _matches(payload, metadata):
    if metadata["product_type"] and payload.get("productType") != metadata["product_type"]:
        return False
    if metadata["audiences"] and not set(payload.get("audience") or []) & set(metadata["audiences"]):
        return False
    if metadata["colors"] and not set(payload.get("colors") or []) & set(metadata["colors"]):
        return False
    return True


def _rank(candidates, query_vector, metadata=None):
    scored = []
    for pid, entries in candidates.items():
        matched = [vector for vector, payload in entries if metadata is None or _matches(payload, metadata)]
        if matched:
            scored.append((max(float(np.dot(query_vector, vector)) for vector in matched), pid))
    scored.sort(reverse=True)
    return [pid for _, pid in scored]


async def _cached_vectors(cache, model, inputs, document, batch_size=10):
    prefix = "document" if document else "query"
    result = {}
    pending = []
    for key, value in inputs.items():
        digest = hashlib.sha256(f"{prefix}:{model.settings.embedding_model}:{model.settings.embedding_dimensions}:{value}".encode()).hexdigest()
        row = cache.execute("SELECT vector FROM embeddings WHERE id=?", (digest,)).fetchone()
        if row:
            result[key] = json.loads(row[0])
        else:
            pending.append((key, value, digest))
    if pending and os.getenv("BENCHMARK_OFFLINE", "true").lower() == "true":
        raise RuntimeError(f"Offline benchmark has {len(pending)} uncached {prefix} embeddings")
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        texts = [value for _, value, _ in batch]
        vectors = await (model.embed_documents(texts) if document else model.embed_queries(texts))
        if len(vectors) != len(batch):
            raise RuntimeError("Embedding response length mismatch")
        for (key, _, digest), vector in zip(batch, vectors):
            result[key] = vector
            cache.execute("INSERT OR REPLACE INTO embeddings VALUES (?,?)", (digest, json.dumps(vector)))
        cache.commit()
        print(f"{prefix} embeddings: {min(start + batch_size, len(pending))}/{len(pending)}", flush=True)
        if document and start + batch_size < len(pending):
            await asyncio.sleep(4)
    return result


async def main():
    logging.disable(logging.CRITICAL)
    settings = Settings()
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    cache = sqlite3.connect(data_dir / "chunk-benchmark.sqlite")
    cache.execute("CREATE TABLE IF NOT EXISTS embeddings (id TEXT PRIMARY KEY, vector TEXT)")
    api, model, catalog = CatalogAPI(settings), ModelClients(settings), VectorCatalog(settings)
    try:
        products = {str(product["_id"]): product for product in await api.all_products()}
        points = {}
        offset = None
        while True:
            page, offset = await catalog.client.scroll(
                catalog.collection, limit=256, offset=offset, with_payload=True, with_vectors=True,
            )
            points.update((str(point.id), point) for point in page)
            if offset is None:
                break

        complete = {}
        for pid, product in products.items():
            # This benchmark compares the legacy layout already in Qdrant. The
            # production chunk schema has since changed, but workers are paused.
            keys = ["title"]
            if plain_text(product.get("description"), 2500) or plain_text(product.get("detail"), 6000):
                keys.append("description")
            keys.extend(f"variant:{str(variant.get('_id') or index)}"
                        for index, variant in enumerate(product.get("variants", [])))
            expected = [point_id(pid, key) for key in keys]
            legacy_data = {"document": product_document(product).page_content,
                           "images": image_records(product, settings.max_images)}
            fingerprint = hashlib.sha256(json.dumps(
                legacy_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if all(point in points and points[point].payload.get("contentHash") == fingerprint for point in expected):
                complete[pid] = (product, expected)
        sample_size = min(180, len(complete))
        rng = random.Random(20261026)
        sampled_ids = sorted(rng.sample(list(complete), sample_size))
        sampled = {pid: complete[pid] for pid in sampled_ids}
        print(f"Comparable products: {len(complete)}; benchmark sample: {len(sampled)}", flush=True)

        queries = {}
        labels = {}
        query_colors = {}
        for query, product_type, gender, color in QUERIES:
            relevant = {pid for pid, (product, _) in sampled.items() if _relevant(product, product_type, gender, color)}
            if len(relevant) >= 3:
                queries[query] = query
                labels[query] = relevant
                query_colors[query] = color
        if not queries:
            raise RuntimeError("No query has at least three relevant products in the comparable sample")

        query_vectors = await _cached_vectors(cache, model, queries, False, batch_size=1)
        embed_full = os.getenv("BENCHMARK_EMBED_FULL", "false").lower() == "true"
        full_vectors = {}
        if embed_full:
            full_text = {pid: product_document(product).page_content for pid, (product, _) in sampled.items()}
            full_vectors = await _cached_vectors(cache, model, full_text, True)

        strategies = {name: {} for name in (
            "onePooled", "titleOnly", "titleAndDescription", "baseAndColorGroups", "allChunks",
        )}
        if embed_full:
            strategies["oneFullDocument"] = {}
        for pid, (_, expected) in sampled.items():
            entries = [(_unit(points[point].vector), points[point].payload) for point in expected]
            by_type = {payload.get("chunkType"): (vector, payload) for vector, payload in entries[:2]}
            strategies["onePooled"][pid] = [(_unit(np.mean([vector for vector, _ in entries], axis=0)), by_type["title"][1])]
            if embed_full:
                strategies["oneFullDocument"][pid] = [(_unit(full_vectors[pid]), by_type["title"][1])]
            strategies["titleOnly"][pid] = [by_type["title"]]
            strategies["titleAndDescription"][pid] = [entry for kind, entry in by_type.items() if kind in ("title", "description")]
            groups = {}
            for vector, payload in entries:
                if payload.get("chunkType") != "variant":
                    continue
                key = tuple(sorted(payload.get("colors") or []))
                groups.setdefault(key, []).append((vector, payload))
            grouped_variants = [
                (_unit(np.mean([vector for vector, _ in group], axis=0)), group[0][1])
                for group in groups.values()
            ]
            base = _unit(np.mean([by_type["title"][0], by_type["description"][0]], axis=0))
            strategies["baseAndColorGroups"][pid] = [(base, by_type["title"][1]), *grouped_variants]
            strategies["allChunks"][pid] = entries

        cases = []
        for query in queries:
            vector = _unit(query_vectors[query])
            case = {"query": query, "relevantProducts": len(labels[query]), "strategies": {}, "filteredStrategies": {}}
            filters = query_metadata({"query": query, "variant_terms": [query_colors[query]]})
            for name, candidates in strategies.items():
                for scenario, metadata in (("strategies", None), ("filteredStrategies", filters)):
                    ordered = _rank(candidates, vector, metadata)
                    case[scenario][name] = {
                        **_metrics(ordered, labels[query]),
                        "candidateProducts": len(ordered),
                        "top6": [{"id": pid, "name": sampled[pid][0].get("name", ""), "relevant": pid in labels[query]} for pid in ordered[:6]],
                    }
            cases.append(case)

        summary = {}
        filtered_summary = {}
        for name in strategies:
            summary[name] = {
                metric: round(sum(case["strategies"][name][metric] for case in cases) / len(cases), 4)
                for metric in ("precisionAt6", "recallAt10", "ndcgAt10")
            }
            summary[name]["vectorsPerProduct"] = round(sum(len(v) for v in strategies[name].values()) / len(sampled), 2)
            filtered_summary[name] = {
                metric: round(sum(case["filteredStrategies"][name][metric] for case in cases) / len(cases), 4)
                for metric in ("precisionAt6", "recallAt10", "ndcgAt10")
            }
        output = {
            "model": settings.embedding_model,
            "dimensions": settings.embedding_dimensions,
            "sampledProducts": len(sampled),
            "comparableProducts": len(complete),
            "approvedProducts": len(products),
            "queryCount": len(cases),
            "labelMethod": "Heuristic product name type/gender and actual variant name color; not human judgments",
            "limitation": "Current text index is incomplete. Scores compare only products whose existing chunks match current catalog content. Filtered scores use product type, audience, and color payload filters but omit live stock checks.",
            "onePooledDefinition": "Unit-normalized arithmetic mean of existing chunk vectors; not an embedding of the full product text",
            "baseAndColorGroupsDefinition": "One pooled title/description vector plus one pooled vector per distinct variant color set; size-only variants share a color group",
            "summary": summary,
            "filteredSummary": filtered_summary,
            "cases": cases,
        }
        path = data_dir / "chunk-benchmark-results.json"
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"resultPath": str(path), "queryCount": len(cases), "summary": summary}, ensure_ascii=False), flush=True)
    finally:
        cache.close()
        await api.close()
        await model.close()
        await catalog.close()


if __name__ == "__main__":
    asyncio.run(main())
