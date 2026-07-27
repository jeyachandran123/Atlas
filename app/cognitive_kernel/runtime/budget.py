"""Execution budgets — enforced by the runtime, not by engines (P3/P5).

A :class:`RuntimeBudget` is multi-dimensional (time, steps, memory, tokens,
tools, simulations). Engines *report* consumption (``consume``); the runtime
*enforces* the limit (``exceeded``). Unset axes are unbounded.
"""

from __future__ import annotations

import threading
import time

from .contracts import BudgetSpec, BudgetUsage

_COUNTED = ("steps", "memory", "tokens", "tools", "simulations")


class RuntimeBudget:
    __slots__ = ("_limits", "_used", "_time_limit", "_start", "_lock")

    def __init__(self, spec: BudgetSpec) -> None:
        self._limits: dict[str, int | None] = {
            "steps": spec.steps,
            "memory": spec.memory,
            "tokens": spec.tokens,
            "tools": spec.tools,
            "simulations": spec.simulations,
        }
        self._used: dict[str, int] = {k: 0 for k in _COUNTED}
        self._time_limit = spec.time_seconds
        self._start = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, kind: str, amount: int = 1) -> None:
        if kind not in self._used:
            raise KeyError(f"Unknown budget dimension: {kind}")
        with self._lock:
            self._used[kind] += amount

    def remaining(self, kind: str) -> int | None:
        with self._lock:
            limit = self._limits.get(kind)
            return None if limit is None else max(0, limit - self._used[kind])

    def elapsed(self) -> float:
        return time.monotonic() - self._start

    def time_remaining(self) -> float | None:
        if self._time_limit is None:
            return None
        return max(0.0, self._time_limit - self.elapsed())

    def time_exceeded(self) -> bool:
        return self._time_limit is not None and self.elapsed() >= self._time_limit

    def exceeded(self) -> bool:
        if self.time_exceeded():
            return True
        with self._lock:
            return any(
                limit is not None and self._used[k] >= limit
                for k, limit in self._limits.items()
            )

    def usage(self) -> BudgetUsage:
        with self._lock:
            return BudgetUsage(
                time_seconds=self.elapsed(),
                steps=self._used["steps"],
                memory=self._used["memory"],
                tokens=self._used["tokens"],
                tools=self._used["tools"],
                simulations=self._used["simulations"],
            )

    def utilization(self) -> float:
        """Max fractional utilization across all bounded dimensions (0..1)."""
        with self._lock:
            fractions = [self._used[k] / lim for k, lim in self._limits.items() if lim]
        if self._time_limit:
            fractions.append(min(1.0, self.elapsed() / self._time_limit))
        return min(1.0, max(fractions)) if fractions else 0.0


class BudgetManager:
    """Creates budgets, applying a default spec when a request omits one."""

    def __init__(self, default_spec: BudgetSpec | None = None) -> None:
        self._default = default_spec or BudgetSpec()

    def create(self, spec: BudgetSpec) -> RuntimeBudget:
        d = self._default
        merged = BudgetSpec(
            time_seconds=spec.time_seconds if spec.time_seconds is not None else d.time_seconds,
            steps=spec.steps if spec.steps is not None else d.steps,
            memory=spec.memory if spec.memory is not None else d.memory,
            tokens=spec.tokens if spec.tokens is not None else d.tokens,
            tools=spec.tools if spec.tools is not None else d.tools,
            simulations=spec.simulations if spec.simulations is not None else d.simulations,
        )
        return RuntimeBudget(merged)
