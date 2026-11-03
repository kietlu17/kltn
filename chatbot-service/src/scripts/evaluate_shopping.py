"""API-level shopping regression with deterministic assertions and latency samples.

python -m src.scripts.evaluate_shopping --url http://localhost:3000 \
    --cases ../docs/evaluation/shopping-acceptance.json --output shopping-report.json
"""

import argparse
import asyncio
import json
import math
import time
from pathlib import Path

import httpx


def check_turn(data: dict, expected: dict) -> list[str]:
    failures = []
    products = data.get("products") or []
    ids = [str(item.get("id") or "") for item in products]
    if len(ids) != len(set(ids)):
        failures.append("duplicate_product_ids")
    if any(not item for item in ids):
        failures.append("missing_product_id")
    for item in products:
        if "max_price" in expected and float(item.get("price") or 0) > expected["max_price"]:
            failures.append("price_above_limit")
        if "min_price" in expected and float(item.get("price") or 0) < expected["min_price"]:
            failures.append("price_below_limit")
        if any(float(variant.get("availableStock") or 0) <= 0
               for variant in item.get("variants") or []):
            failures.append("unverified_or_empty_variant")
    if len(products) < expected.get("min_products", 0):
        failures.append("too_few_products")
    if "max_products" in expected and len(products) > expected["max_products"]:
        failures.append("too_many_products")
    if "answer_contains" in expected and expected["answer_contains"].casefold() not in data.get("answer", "").casefold():
        failures.append("answer_missing_text")
    if "route" in expected and data.get("route") != expected["route"]:
        failures.append("wrong_route")
    return list(dict.fromkeys(failures))


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(fraction * len(ordered)) - 1)], 1)


async def run(url: str, cases_path: Path, output_path: Path, timeout: float) -> dict:
    scenarios = json.loads(cases_path.read_text(encoding="utf-8"))
    if not isinstance(scenarios, list):
        raise ValueError("Cases must be a JSON array")
    rows = []
    async with httpx.AsyncClient(base_url=url.rstrip("/"), timeout=timeout) as client:
        for scenario in scenarios:
            session_id = None
            for number, turn in enumerate(scenario["turns"], 1):
                started = time.monotonic()
                try:
                    response = await client.post("/assistant/chat", json={
                        "message": turn["message"], "sessionId": session_id,
                    })
                    elapsed = round((time.monotonic() - started) * 1000, 1)
                    response.raise_for_status()
                    data = response.json()
                    session_id = data.get("sessionId")
                    failures = check_turn(data, turn.get("expect", {}))
                    rows.append({"scenario": scenario["name"], "turn": number,
                                 "latency_ms": elapsed, "product_ids": [p.get("id") for p in data.get("products", [])],
                                 "route": data.get("route"), "failures": failures})
                except (httpx.HTTPError, ValueError) as error:
                    rows.append({"scenario": scenario["name"], "turn": number,
                                 "latency_ms": round((time.monotonic() - started) * 1000, 1),
                                 "failures": [type(error).__name__]})
                    break
    latencies = [row["latency_ms"] for row in rows]
    summary = {"turns": len(rows), "passed": sum(not row["failures"] for row in rows),
               "p50_ms": _percentile(latencies, 0.5), "p95_ms": _percentile(latencies, 0.95)}
    report = {"summary": summary, "cases": rows}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:3000")
    parser.add_argument("--cases", type=Path, default=Path("../docs/evaluation/shopping-acceptance.json"))
    parser.add_argument("--output", type=Path, default=Path("shopping-report.json"))
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    report = asyncio.run(run(args.url, args.cases, args.output, args.timeout))
    print(json.dumps(report["summary"], ensure_ascii=False))
