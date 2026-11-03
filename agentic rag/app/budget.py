from __future__ import annotations

import asyncio
import time
from contextvars import ContextVar
from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    """The current turn has no LLM calls or wall-clock time left."""


@dataclass
class TurnBudget:
    """Per-turn ceiling on generative calls and total model latency.

    Embeddings only consume time, not call slots: they are cheap and required
    for retrieval, while generative calls dominate cost and latency.
    """

    max_calls: int
    deadline: float
    calls: int = 0
    kinds: list[str] = field(default_factory=list)
    exhausted: bool = False

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def acquire(self, kind: str, timeout: float) -> float:
        remaining = self.remaining()
        if remaining <= 0.5:
            self.exhausted = True
            raise BudgetExceeded(f"deadline reached before {kind}")
        if kind != "embed":
            if self.calls >= self.max_calls:
                self.exhausted = True
                raise BudgetExceeded(f"call limit reached before {kind}")
            self.calls += 1
            self.kinds.append(kind)
        return min(timeout, remaining)


_current: ContextVar[TurnBudget | None] = ContextVar("agentic_turn_budget", default=None)


def start_turn(max_calls: int, seconds: float) -> TurnBudget:
    budget = TurnBudget(max_calls=max_calls, deadline=time.monotonic() + seconds)
    _current.set(budget)
    return budget


def current_budget() -> TurnBudget | None:
    return _current.get()


def has_calls_left(reserve: int = 1) -> bool:
    budget = _current.get()
    return budget is None or (
        budget.max_calls - budget.calls >= reserve and budget.remaining() > 1
    )


async def bounded(kind: str, timeout: float, awaitable):
    """Run one model call inside the turn budget and its own timeout."""
    budget = _current.get()
    try:
        limit = budget.acquire(kind, timeout) if budget else timeout
    except BudgetExceeded:
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        raise
    return await asyncio.wait_for(awaitable, timeout=limit)
