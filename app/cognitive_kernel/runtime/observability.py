"""Runtime observability — execution tree, timeline, spans, correlation (P4).

Builds on the kernel's :class:`Observability`. Maintains the parent/child
execution tree and a per-execution timeline of state transitions so every
execution exposes a full, correlated trace (OpenTelemetry-shaped: trace ids come
from the kernel execution context).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from ..contracts import Observability
from .contracts import ExecutionState


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    execution_id: str
    state: ExecutionState
    at_wall: float
    at_logical: int


@dataclass(slots=True)
class ExecutionTrace:
    execution_id: str
    correlation_id: str
    trace_id: str
    parent_id: str | None
    engine: str
    children: list[str] = field(default_factory=list)
    timeline: list[TimelineEvent] = field(default_factory=list)


class RuntimeObservability:
    def __init__(self, kernel_obs: Observability) -> None:
        self._obs = kernel_obs
        self._traces: dict[str, ExecutionTrace] = {}
        self._lock = threading.Lock()

    def open(self, execution_id: str, correlation_id: str, trace_id: str, parent_id: str | None, engine: str) -> None:
        with self._lock:
            self._traces[execution_id] = ExecutionTrace(
                execution_id=execution_id,
                correlation_id=correlation_id,
                trace_id=trace_id,
                parent_id=parent_id,
                engine=engine,
            )
            if parent_id and parent_id in self._traces:
                self._traces[parent_id].children.append(execution_id)

    def record(self, execution_id: str, state: ExecutionState, logical: int) -> None:
        self._obs.counter("runtime.execution.transition", state=state.value)
        with self._lock:
            trace = self._traces.get(execution_id)
            if trace is not None:
                trace.timeline.append(
                    TimelineEvent(execution_id, state, time.monotonic(), logical)
                )

    def timeline(self, execution_id: str) -> list[TimelineEvent]:
        with self._lock:
            trace = self._traces.get(execution_id)
            return list(trace.timeline) if trace else []

    def tree(self, root_id: str) -> dict:
        """Return the execution tree rooted at ``root_id`` (parent-child)."""
        with self._lock:
            def build(eid: str) -> dict:
                trace = self._traces.get(eid)
                if trace is None:
                    return {"id": eid, "children": []}
                return {
                    "id": eid,
                    "engine": trace.engine,
                    "state": trace.timeline[-1].state.value if trace.timeline else None,
                    "children": [build(c) for c in trace.children],
                }

            return build(root_id)
