# Checkout-safety benchmark (paper Section V)

Reproduces Tables IV–VII and Figs. 6–7 of `../main.tex`. The scripts load the
**real** project code and replace only the LLM and the downstream services with
in-memory doubles. They measure the orchestration and commit path, not language
understanding or live latency.

| Paper | Script | What it runs |
|---|---|---|
| E1 end-to-end (Table IV) | `bench_agent.py` | 200 direct + 200 handoff dialogues through the real LangGraph supervisor and OrderAgent |
| E2 fault injection (Table V) | `bench_agent.py` (C1–C11, claim filter) and `bench_quote.js` (Q1–Q10) | one injected fault per case |
| E3 confirmation policies (Fig. 6, Table VI) | `bench_ablation.py` | policies V0–V4 on 46 labelled replies, model error p = 0…0.5 (2,000 trials each) and a worst-case always-confirm model |
| E4 guard ablation (Fig. 7) | `bench_quote.js` (`ablation` block) | full protocol vs. without atomic claim / idempotency key / both / re-pricing |

Run from the repository root:

```
python docs/paper/benchmark/bench_agent.py    "agentic rag" docs/paper/benchmark/agent_results.json
python docs/paper/benchmark/bench_ablation.py "agentic rag" docs/paper/benchmark/ablation_results.json
node   docs/paper/benchmark/bench_quote.js    order-service docs/paper/benchmark/quote_results.json
```

Recorded environment (2026-11-08): Windows 11, Python 3.10.0, Node v24.5.0,
LangGraph `MemorySaver` checkpointer. The `agentic rag` test suite passed
191/191 on the same commit. `bench_ablation.py` uses a fixed random seed.

Notes
- E1/E2 use a scripted `SemanticTurn` per message (an oracle for turn
  understanding). Typed confirmations bypass the model by design.
- E3 imports `_pending_reply` and `_explicit_pending_answer` from `app.graph`,
  so V3 is the deployed gate. V4 adds three markers (nhưng, để … đã, suy nghĩ)
  taken from the E3 failure analysis; it is not deployed and was evaluated
  in-sample. The 46 replies and labels were written by the authors
  (`UTTERANCES` in `bench_agent.py`).
- The noise model assumes independent errors, uniform over the two wrong labels.
- E4's model double applies the conditional `UPDATE ... WHERE status IN
  ('open','failed')` atomically; real-database isolation was not exercised.
  The ablation switches exist only in the double, not in the service.
