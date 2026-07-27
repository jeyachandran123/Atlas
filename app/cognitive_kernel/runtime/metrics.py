"""Runtime metrics — owned by the runtime, not by engines (P4).

Thread-safe counters and rolling aggregates over execution lifecycle events.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict

from .contracts import ExecutionState, RuntimeMetricsSnapshot


class RuntimeMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._submitted = 0
        self._completed = 0
        self._failed = 0
        self._cancelled = 0
        self._timed_out = 0
        self._recovered = 0
        self._retries = 0
        self._active = 0
        self._queued = 0
        self._durations: list[float] = []
        self._queue_waits: list[float] = []
        self._budget_utils: list[float] = []
        self._engine_util: dict[str, int] = defaultdict(int)
        self._started_at = time.monotonic()

    # --- lifecycle hooks -------------------------------------------------- #

    def on_submitted(self) -> None:
        with self._lock:
            self._submitted += 1
            self._queued += 1

    def on_dequeued(self, queue_seconds: float) -> None:
        with self._lock:
            self._queued = max(0, self._queued - 1)
            self._active += 1
            self._queue_waits.append(queue_seconds)

    def on_retry(self) -> None:
        with self._lock:
            self._retries += 1

    def on_finished(self, state: ExecutionState, engine: str, duration: float, budget_util: float) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
            self._durations.append(duration)
            self._budget_utils.append(budget_util)
            self._engine_util[engine] += 1
            if state is ExecutionState.COMPLETED:
                self._completed += 1
            elif state is ExecutionState.FAILED:
                self._failed += 1
            elif state is ExecutionState.CANCELLED:
                self._cancelled += 1
            elif state is ExecutionState.TIMED_OUT:
                self._timed_out += 1

    def on_recovered(self) -> None:
        with self._lock:
            self._recovered += 1

    # --- snapshot --------------------------------------------------------- #

    def snapshot(self) -> RuntimeMetricsSnapshot:
        with self._lock:
            n = max(1, self._completed + self._failed + self._cancelled + self._timed_out)
            elapsed = max(1e-9, time.monotonic() - self._started_at)
            avg_dur = sum(self._durations) / len(self._durations) if self._durations else 0.0
            avg_q = sum(self._queue_waits) / len(self._queue_waits) if self._queue_waits else 0.0
            util = sum(self._budget_utils) / len(self._budget_utils) if self._budget_utils else 0.0
            return RuntimeMetricsSnapshot(
                submitted=self._submitted,
                completed=self._completed,
                failed=self._failed,
                cancelled=self._cancelled,
                timed_out=self._timed_out,
                recovered=self._recovered,
                retries=self._retries,
                active=self._active,
                queued=self._queued,
                throughput=self._completed / elapsed,
                avg_duration_seconds=avg_dur,
                avg_queue_seconds=avg_q,
                failure_rate=self._failed / n,
                cancellation_rate=self._cancelled / n,
                recovery_rate=self._recovered / n,
                budget_utilization=util,
                engine_utilization=dict(self._engine_util),
            )
