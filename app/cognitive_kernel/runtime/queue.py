"""Deterministic execution queue.

Ordering is strictly deterministic: ready executions are ordered by
``(priority, enqueue-sequence)``. Deferred/periodic executions become ready only
at/after their due time. There is no wall-clock tie-breaking, so replay and
tests are reproducible (RL4/RL8). This is the runtime's *pending-execution*
structure — distinct from the kernel scheduler (which runs generic callables);
the runtime uses the kernel scheduler only to wake deferred executions.
"""

from __future__ import annotations

import itertools
import threading
import time

from .contracts import QueueKind
from .execution import Execution


class ExecutionQueue:
    def __init__(self) -> None:
        self._items: dict[str, Execution] = {}
        self._seq = itertools.count()
        self._lock = threading.Lock()

    def enqueue(self, execution: Execution) -> None:
        with self._lock:
            execution.enqueue_seq = next(self._seq)
            if execution.kind is QueueKind.BACKGROUND:
                # Background work sorts after everything else regardless of prio.
                pass
            self._items[execution.id] = execution

    def _sort_key(self, ex: Execution) -> tuple[int, int, int]:
        # BACKGROUND kind is demoted below all priorities.
        bg = 1 if ex.kind is QueueKind.BACKGROUND else 0
        return (bg, int(ex.priority), ex.enqueue_seq)

    def pop_ready(self, now: float | None = None) -> Execution | None:
        now = time.monotonic() if now is None else now
        with self._lock:
            ready = [ex for ex in self._items.values() if ex.due <= now]
            if not ready:
                return None
            ready.sort(key=self._sort_key)
            chosen = ready[0]
            del self._items[chosen.id]
            return chosen

    def remove(self, execution_id: str) -> Execution | None:
        with self._lock:
            return self._items.pop(execution_id, None)

    def peek_order(self) -> list[str]:
        with self._lock:
            return [ex.id for ex in sorted(self._items.values(), key=self._sort_key)]

    def depth(self) -> int:
        with self._lock:
            return len(self._items)

    def has_ready(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            return any(ex.due <= now for ex in self._items.values())
