"""Integration-level benchmark of the conversational checkout path.

Runs the real LangGraph supervisor + OrderAgent code with in-memory doubles
for the LLM (scripted SemanticTurn = oracle understanding) and for the
marketplace services. It therefore measures the orchestration and the
transaction-safety layer, NOT language-understanding accuracy.

Usage: python bench_agent.py <path-to-agentic-rag> <out.json>
"""

import asyncio
import json
import statistics
import sys
import time

ROOT = sys.argv[1]
OUT = sys.argv[2]
sys.path[:0] = [ROOT, ROOT + "/tests"]

from app.graph import (  # noqa: E402
    _drop_unbacked_action_claims,
    _explicit_pending_answer,
    _pending_reply,
)
from app.schemas import SemanticReference, SemanticTask, SemanticTurn  # noqa: E402
from test_graph import ADDRESS_ID, PRODUCT_ID, state  # noqa: E402
from test_graph import FakeMarketplace as _BaseMarketplace  # noqa: E402
from test_production import SemanticModels, build  # noqa: E402


class FakeMarketplace(_BaseMarketplace):
    async def product(self, product_id):
        return await self.product_card(product_id)

N_RUNS = 200


class ScriptedModels(SemanticModels):
    """decide() returns the scripted turn for the current message."""

    def __init__(self, script):
        super().__init__()
        self.script = script

    async def decide(self, message, *_a, **_k):
        self.decide_calls += 1
        turn = self.script.get(message) or SemanticTurn(
            tasks=[SemanticTask(intent="general", query=message)], confidence=0.9
        )
        if isinstance(turn, Exception):
            raise turn
        return turn


class FailingMarketplace(FakeMarketplace):
    def __init__(self):
        super().__init__()
        self.quotes = 0

    async def checkout_quote(self, *args):
        self.quotes += 1
        return await super().checkout_quote(*args)


def turn(intent, **task):
    return SemanticTurn(
        tasks=[SemanticTask(intent=intent, **task)],
        conversation_action="continue",
        confidence=0.95,
    )


ADD = "thêm áo này vào giỏ"
PAY = "thanh toán đơn này giúp mình"
SCRIPT = {
    ADD: turn("cart_add", references=[SemanticReference(kind="active")]),
    PAY: turn("checkout"),
}


def carry(prev, message, request=None):
    nxt = state(message, request=request, pending=prev.get("pending_action"))
    nxt["focused_products"] = [{"id": PRODUCT_ID, "name": "Áo sơ mi trắng"}]
    nxt["active_product_id"] = PRODUCT_ID
    return nxt


async def e1_once(direct: bool):
    """search-context -> add -> confirm -> checkout -> confirm."""
    models = ScriptedModels(SCRIPT)
    market = FakeMarketplace()
    agent = build(models, marketplace=market)
    cfg = {"configurable": {"thread_id": f"e1-{time.perf_counter_ns()}"}}
    timings, calls = [], []
    pay_request = {"addressId": ADDRESS_ID, "paymentMethod": "cod"} if direct else {}

    async def step(cur):
        before = (models.decide_calls, models.answer_calls)
        t0 = time.perf_counter()
        res = await agent.graph.ainvoke(cur, config=cfg)
        timings.append((time.perf_counter() - t0) * 1000)
        calls.append(models.decide_calls - before[0] + models.answer_calls - before[1])
        return res

    r1 = await step(carry({}, ADD))
    writes_before_confirm = len(market.cart_writes)
    r2 = await step(carry(r1, "xác nhận"))
    r3 = await step(carry(r2, PAY, request=pay_request))
    orders_before_confirm = len(market.confirmed_quotes)
    if direct:
        r4 = await step(carry(r3, "xác nhận"))
        completed = len(market.confirmed_quotes) == 1 and r4["tool_result"].get("success") is True
    else:
        completed = r3["tool_result"].get("tool") == "open_checkout"
    return {
        "completed": completed,
        "turns": len(timings),
        "pending_after_add": bool(r1.get("pending_action")),
        "writes_before_confirm": writes_before_confirm,
        "cart_writes": len(market.cart_writes),
        "orders_before_confirm": orders_before_confirm,
        "orders": len(market.confirmed_quotes),
        "ms": timings,
        "llm_calls": calls,
    }


def pct(values, q):
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


async def e1():
    out = {}
    for direct in (True, False):
        runs = [await e1_once(direct) for _ in range(N_RUNS)]
        per_turn = list(zip(*[r["ms"] for r in runs]))
        out["direct" if direct else "handoff"] = {
            "runs": N_RUNS,
            "completion_rate": sum(r["completed"] for r in runs) / N_RUNS,
            "turns": runs[0]["turns"],
            "writes_before_confirm": max(r["writes_before_confirm"] for r in runs),
            "orders_before_confirm": max(r["orders_before_confirm"] for r in runs),
            "cart_writes_per_run": statistics.mean(r["cart_writes"] for r in runs),
            "orders_per_run": statistics.mean(r["orders"] for r in runs),
            "llm_calls_per_turn": runs[0]["llm_calls"],
            "latency_ms_per_turn": [
                {"median": statistics.median(t), "p95": pct(t, 0.95)} for t in per_turn
            ],
        }
    return out


async def e2():
    """Fault injection: every case must end with the expected number of writes."""
    cases = []

    async def run(name, expect_writes, fn):
        market = FakeMarketplace()
        writes = await fn(market)
        observed = len(market.cart_writes) + len(market.confirmed_quotes) if writes is None else writes
        cases.append({"case": name, "expected_writes": expect_writes, "observed_writes": observed,
                      "pass": observed == expect_writes})

    async def prepared(market, message=ADD, request=None, script=SCRIPT):
        models = ScriptedModels(script)
        agent = build(models, marketplace=market)
        cfg = {"configurable": {"thread_id": f"e2-{time.perf_counter_ns()}"}}
        res = await agent.graph.ainvoke(carry({}, message, request), config=cfg)
        return agent, cfg, res

    async def no_confirm(market):
        await prepared(market)
        return None

    async def checkout_no_confirm(market):
        await prepared(market, PAY, {"addressId": ADDRESS_ID, "paymentMethod": "cod"})
        return None

    async def forged(market):
        agent, cfg, res = await prepared(market)
        await agent.graph.ainvoke(carry(res, "ok", {"confirmActionId": "act_forged"}), config=cfg)
        return None

    async def expired(market):
        agent, cfg, res = await prepared(market)
        pending = dict(res["pending_action"], expires_at=time.time() - 1)
        await agent.graph.ainvoke(carry({"pending_action": pending}, "xác nhận"), config=cfg)
        return None

    async def replay(market):
        agent, cfg, res = await prepared(market)
        action_id = res["pending_action"]["id"]
        r2 = await agent.graph.ainvoke(carry(res, "ok", {"confirmActionId": action_id}), config=cfg)
        await agent.graph.ainvoke(carry(r2, "ok", {"confirmActionId": action_id}), config=cfg)
        return None

    async def cancel(market):
        agent, cfg, res = await prepared(market)
        await agent.graph.ainvoke(carry(res, "thôi hủy đi"), config=cfg)
        return None

    async def hedged(market):
        agent, cfg, res = await prepared(market)
        msg = "Có thể, nhưng phải có bảo hành chính hãng. Cho mình xem mẫu khác trước."
        script = {msg: SemanticTurn(tasks=[SemanticTask(intent="general")], confidence=0.9,
                                    pending_decision="confirm")}
        agent.models.script.update(script)
        await agent.graph.ainvoke(carry(res, msg), config=cfg)
        return None

    async def guest(market):
        models = ScriptedModels(SCRIPT)
        agent = build(models, marketplace=market)
        cur = carry({}, ADD)
        cur["role"], cur["user_id"] = "guest", ""
        await agent.graph.ainvoke(cur, config={"configurable": {"thread_id": "guest"}})
        return None

    async def model_down(market):
        script = {ADD: RuntimeError("503 UNAVAILABLE")}
        await prepared(market, ADD, None, script)
        return None

    async def valid(market):
        agent, cfg, res = await prepared(market)
        await agent.graph.ainvoke(carry(res, "xác nhận"), config=cfg)
        return None

    async def valid_checkout(market):
        agent, cfg, res = await prepared(market, PAY, {"addressId": ADDRESS_ID, "paymentMethod": "cod"})
        await agent.graph.ainvoke(carry(res, "xác nhận"), config=cfg)
        return len(market.confirmed_quotes)

    await run("C1 cart_add without confirmation", 0, no_confirm)
    await run("C2 checkout without confirmation", 0, checkout_no_confirm)
    await run("C3 forged confirmActionId", 0, forged)
    await run("C4 expired pending action", 0, expired)
    await run("C5 replayed confirmation (same id twice)", 1, replay)
    await run("C6 typed cancellation", 0, cancel)
    await run("C7 hedged reply misread as confirm by model", 0, hedged)
    await run("C8 unauthenticated user", 0, guest)
    await run("C9 semantic model unavailable (503)", 0, model_down)
    await run("C10 valid cart confirmation (control)", 1, valid)
    await run("C11 valid checkout confirmation (control)", 1, valid_checkout)

    claims = [
        ("Mình đã thêm áo sơ mi trắng size M vào giỏ hàng.", {"found": True}, True),
        ("Em vừa tạo đơn hàng cho bạn rồi nhé.", {}, True),
        ("Mình đã cập nhật giỏ hàng của bạn.", {"found": True}, True),
        ("Tôi đã đặt đơn hàng thành công.", {}, True),
        ("Mình đã thêm áo vào giỏ hàng.", {"success": True}, False),
        ("Nếu bạn đã đặt đơn và muốn hủy, hãy vào mục Đơn hàng.", {}, False),
        ("Áo có 3 màu: trắng, đen, be.", {"found": True}, False),
    ]
    claim_rows = []
    for text, result, should_strip in claims:
        cleaned = _drop_unbacked_action_claims(text, result)
        stripped = cleaned != text
        claim_rows.append({"text": text, "should_strip": should_strip, "stripped": stripped,
                           "pass": stripped == should_strip})
    return {"cases": cases, "unbacked_claims": claim_rows}


# Author-constructed utterances answering a waiting action.
# label: confirm / cancel / other (a question, a hedge, or an unrelated request).
UTTERANCES = [
    ("Xác nhận", "confirm"), ("ok", "confirm"), ("oke", "confirm"), ("okay", "confirm"),
    ("có nhé", "confirm"), ("đồng ý", "confirm"), ("Chốt đơn!", "confirm"), ("đặt luôn", "confirm"),
    ("thêm đi", "confirm"), ("lấy luôn", "confirm"), ("ok bạn", "confirm"), ("xác nhận nha", "confirm"),
    ("có", "confirm"), ("được, thêm vào", "confirm"), ("chốt", "confirm"), ("đặt hàng", "confirm"),
    ("Xác nhận. Mà có được đổi trả không?", "confirm"), ("ok thanh toán luôn", "confirm"),
    ("thôi", "cancel"), ("hủy đi", "cancel"), ("không", "cancel"), ("thôi không", "cancel"),
    ("bỏ qua", "cancel"), ("không đặt nữa", "cancel"), ("dừng lại", "cancel"), ("cancel", "cancel"),
    ("hủy", "cancel"), ("không thêm", "cancel"),
    ("Có thể, nhưng phải có bảo hành chính hãng", "other"),
    ("có màu xanh không", "other"), ("ok nhưng cho mình xem mẫu khác trước đã", "other"),
    ("có size XL không", "other"), ("có ship nhanh không", "other"),
    ("được không bạn", "other"), ("có giảm giá không", "other"),
    ("để mình hỏi vợ đã", "other"), ("có nên mua không nhỉ", "other"),
    ("ok để mình suy nghĩ thêm", "other"), ("cho mình xem lại giỏ hàng", "other"),
    ("bao giờ giao tới", "other"), ("có bảo hành không", "other"),
    ("đổi sang màu đen được không", "other"), ("có thể giảm số lượng không", "other"),
    ("không biết nữa", "other"), ("có lẽ vậy", "other"), ("ừm để xem", "other"),
]


def e3():
    """Two-stage gate. Stage 1: deterministic short-reply classifier.
    Stage 2 (when stage 1 abstains): the model's pending_decision is only
    honoured if the message starts with an explicit confirm/cancel phrase.
    Worst case: an adversarial model that always answers 'confirm'."""
    def gate(text, model_decision):
        # Mirrors AgenticShoppingGraph.understand + plan exactly.
        stage1 = _pending_reply(text)
        if stage1:
            return stage1, stage1
        if model_decision in {"confirm", "cancel"} and _explicit_pending_answer(text, model_decision):
            return None, model_decision
        return None, "none"

    n_other = sum(1 for _, label in UTTERANCES if label == "other")
    n_cancel = sum(1 for _, label in UTTERANCES if label == "cancel")
    n_confirm = sum(1 for _, label in UTTERANCES if label == "confirm")
    models = {
        "worst_case_always_confirm": lambda label: "confirm",
        "oracle": lambda label: label if label in {"confirm", "cancel"} else "none",
    }
    out = {"n": len(UTTERANCES), "n_confirm": n_confirm, "n_cancel": n_cancel, "n_other": n_other}
    for name, model in models.items():
        rows, confusion = [], {}
        for text, label in UTTERANCES:
            stage1, decided = gate(text, model(label))
            rows.append({"text": text, "label": label, "stage1": stage1, "decided": decided})
            key = f"{label}->{decided}"
            confusion[key] = confusion.get(key, 0) + 1
        false_confirm = sum(1 for r in rows if r["decided"] == "confirm" and r["label"] != "confirm")
        false_cancel = sum(1 for r in rows if r["decided"] == "cancel" and r["label"] != "cancel")
        out[name] = {
            "confirm_recall": sum(1 for r in rows if r["decided"] == "confirm" and r["label"] == "confirm") / n_confirm,
            "cancel_recall": sum(1 for r in rows if r["decided"] == "cancel" and r["label"] == "cancel") / n_cancel,
            "false_confirm": false_confirm,
            "false_confirm_rate_non_confirm": false_confirm / (n_other + n_cancel),
            "false_cancel": false_cancel,
            "stage1_decided": sum(1 for r in rows if r["stage1"]),
            "confusion": confusion,
            "rows": rows,
        }
    return out


async def main():
    result = {"e1": await e1(), "e2": await e2(), "e3": e3(),
              "python": sys.version.split()[0]}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in result["e1"].items()}, ensure_ascii=False, indent=1))
    print("E2", [(c["case"], c["observed_writes"], c["pass"]) for c in result["e2"]["cases"]])
    print("claims", [(r["text"][:30], r["pass"]) for r in result["e2"]["unbacked_claims"]])
    for name in ("worst_case_always_confirm", "oracle"):
        e3r = {k: v for k, v in result["e3"][name].items() if k != "rows"}
        print("E3", name, json.dumps(e3r, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
