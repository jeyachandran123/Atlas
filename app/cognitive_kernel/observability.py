"""Observability infrastructure: structured logs, metrics, tracing spans.

Requirement: *nothing should be invisible*. Every kernel operation gets a
structured logger, counters/gauges, and correlation-aware spans. The default
implementation is stdlib-only and distributed-tracing-ready (trace/span ids are
propagated from :class:`ExecutionContext`).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from .contracts import ExecutionContext, Observability, Span, StructuredLogger


class _StructuredLogger(StructuredLogger):
    def __init__(self, base: logging.Logger, correlation_id: str | None = None) -> None:
        self._base = base
        self._cid = correlation_id

    def _emit(self, level: int, message: str, **fields: Any) -> None:
        if self._cid:
            fields.setdefault("correlation_id", self._cid)
        extra = " ".join(f"{k}={v}" for k, v in fields.items())
        self._base.log(level, "%s %s", message, extra)

    def info(self, message: str, **f: Any) -> None:
        self._emit(logging.INFO, message, **f)

    def warning(self, message: str, **f: Any) -> None:
        self._emit(logging.WARNING, message, **f)

    def error(self, message: str, **f: Any) -> None:
        self._emit(logging.ERROR, message, **f)

    def debug(self, message: str, **f: Any) -> None:
        self._emit(logging.DEBUG, message, **f)


class _Span(Span):
    def __init__(self, obs: "KernelObservability", name: str, context: ExecutionContext) -> None:
        self._obs = obs
        self._name = name
        self._trace = context.trace
        self._attrs: dict[str, Any] = {}

    def __enter__(self) -> "_Span":
        self._obs.counter("span.start", name=self._name)
        return self

    def __exit__(self, *exc: Any) -> None:
        self._obs.counter("span.end", name=self._name)

    def set(self, key: str, value: Any) -> None:
        self._attrs[key] = value


class KernelObservability(Observability):
    """Default, thread-safe, in-process observability provider."""

    def __init__(self, root_name: str = "cognitive_kernel") -> None:
        self._root = root_name
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._lock = threading.Lock()

    def logger(self, name: str) -> StructuredLogger:
        return _StructuredLogger(logging.getLogger(f"{self._root}.{name}"))

    def counter(self, name: str, amount: int = 1, **tags: str) -> None:
        key = name if not tags else f"{name}{sorted(tags.items())}"
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + amount

    def gauge(self, name: str, value: float, **tags: str) -> None:
        key = name if not tags else f"{name}{sorted(tags.items())}"
        with self._lock:
            self._gauges[key] = value

    def span(self, name: str, context: ExecutionContext) -> Span:
        return _Span(self, name, context)

    # Introspection for the health monitor / dashboards.
    def snapshot(self) -> dict[str, dict[str, float]]:
        with self._lock:
            return {"counters": dict(self._counters), "gauges": dict(self._gauges)}
