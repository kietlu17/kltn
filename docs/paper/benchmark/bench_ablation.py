"""E5: ablation of the confirmation gate against a noisy semantic model.

Five commit policies decide what happens to a pending action given the
buyer's reply and the semantic model's reading of it:

  V0 direct      no confirmation step: the proposed action is committed at once
  V1 model-only  commit whenever the model says "confirm"
  V2 lexical     only the deterministic short-reply classifier (Stage 1)
  V3 proposed    Stage 1, then the model's decision gated by an explicit
                 prefix (the deployed code, imported from app.graph)
  V4 proposed+   V3, and Stage 2 additionally rejects contrastive/deferral
                 markers ("nhưng", "để ... đã", "suy nghĩ") - a refinement
                 suggested by E3, NOT deployed

The noisy model returns the true label with probability 1-p and otherwise
one of the two wrong labels uniformly at random. p = 1 is replaced by the
worst case (always "confirm").

Usage: python bench_ablation.py <path-to-agentic-rag> <out.json>
"""

import json
import random
import re
import sys

ROOT, OUT = sys.argv[1], sys.argv[2]
sys.path[:0] = [ROOT, ROOT + "/tests", __file__.rsplit("/", 1)[0].rsplit("\\", 1)[0]]
sys.argv = [sys.argv[0], ROOT, OUT]  # bench_agent reads argv at import

from app.conversation import _normalized  # noqa: E402
from app.graph import _explicit_pending_answer, _pending_reply  # noqa: E402
from bench_agent import UTTERANCES  # noqa: E402

LABELS = ("confirm", "cancel", "none")
TRIALS = 2000
NOISE = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
# Exactly the three markers named in the paper's E3 failure analysis; the
# list was fixed before this ablation and evaluated in-sample.
_HEDGE = re.compile(r"\b(?:nhung|de\s+\w+(?:\s+\w+){0,4}\s+da|suy nghi)\b")


def truth(label):
    return label if label in {"confirm", "cancel"} else "none"


def v0(_text, _model):
    return "confirm"


def v1(_text, model):
    return model


def v2(text, _model):
    return _pending_reply(text) or "none"


def v3(text, model):
    stage1 = _pending_reply(text)
    if stage1:
        return stage1
    if model in {"confirm", "cancel"} and _explicit_pending_answer(text, model):
        return model
    return "none"


def v4(text, model):
    decided = v3(text, model)
    if decided == "confirm" and not _pending_reply(text) and _HEDGE.search(_normalized(text)):
        return "none"
    return decided


POLICIES = {"V0 direct": v0, "V1 model-only": v1, "V2 lexical": v2, "V3 proposed": v3, "V4 proposed+": v4}


def noisy(label, p, rng):
    true = truth(label)
    if rng.random() >= p:
        return true
    return rng.choice([item for item in LABELS if item != true])


def evaluate(policy, p, rng, worst=False):
    n_conf = n_cancel = n_non = tp = fc = tc = model_calls = 0
    for _ in range(TRIALS if not worst and p > 0 else 1):
        for text, label in UTTERANCES:
            model = "confirm" if worst else noisy(label, p, rng)
            decided = policy(text, model)
            if policy in (v3, v4, v1) and not (_pending_reply(text) and policy is not v1):
                model_calls += 1
            if label == "confirm":
                n_conf += 1
                tp += decided == "confirm"
            else:
                n_non += 1
                fc += decided == "confirm"
            if label == "cancel":
                n_cancel += 1
                tc += decided == "cancel"
    return {
        "confirm_recall": tp / n_conf,
        "false_confirm_rate": fc / n_non,
        "cancel_recall": tc / n_cancel,
        "model_calls_per_reply": model_calls / (n_conf + n_non),
    }


def main():
    rng = random.Random(20261108)
    out = {"trials_per_noise_level": TRIALS, "utterances": len(UTTERANCES), "policies": {}}
    for name, policy in POLICIES.items():
        rows = {f"p={p}": evaluate(policy, p, rng) for p in NOISE}
        rows["worst"] = evaluate(policy, 1.0, rng, worst=True)
        out["policies"][name] = rows
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    for name, rows in out["policies"].items():
        print(name)
        for key, value in rows.items():
            print(f"  {key:6s} recall={value['confirm_recall']:.3f} falseConfirm={value['false_confirm_rate']:.3f} "
                  f"cancel={value['cancel_recall']:.3f} calls={value['model_calls_per_reply']:.2f}")


if __name__ == "__main__":
    main()
