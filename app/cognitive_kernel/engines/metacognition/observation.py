"""The Cognitive Observation Manager (Phase 7) — evidence grounded in traces (MeL16).

Builds an immutable :class:`ObservationWindow` from *public infrastructure only*:
the append-only **Ledger** (the recorded traces of every faculty), the kernel
**Health Monitor** (each engine's registered health probe), and **Runtime**
telemetry. It never calls an engine's introspection and imports no engine — the
mind's self-model is grounded in observed traces, not confabulated introspection.
Read-only throughout.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from ...contracts import KernelServices
from ...state import CognitiveStateManager
from .contracts import ObservationWindow


class ObservationManager:
    def __init__(self, services: KernelServices, state: CognitiveStateManager) -> None:
        self._services = services
        self._state = state
        self._runtime: Any | None = None

    def bind_runtime(self, runtime: Any) -> None:
        self._runtime = runtime  # infrastructure telemetry only (runtime.metrics)

    def observe(self, since: int) -> ObservationWindow:
        until = self._services.ledger.head()
        counts: dict[str, int] = defaultdict(int)
        by_source: dict[str, int] = defaultdict(int)
        samples: dict[str, list[float]] = defaultdict(list)

        for entry in self._services.ledger.read(since=since):
            ev = entry.event
            if ev.sequence > until:
                continue
            counts[ev.type] += 1
            by_source[ev.source] += 1
            self._extract(ev.type, ev.payload, samples)

        health_status: dict[str, str] = {}
        health_metrics: dict[str, float] = {}
        for name, report in self._services.health.report().items():
            health_status[name] = report.status.value
            for k, v in report.metrics.items():
                try:
                    health_metrics[f"{name}.{k}"] = float(v)
                except (TypeError, ValueError):
                    continue

        runtime_metrics: dict[str, float] = {}
        if self._runtime is not None:
            try:
                m = self._runtime.metrics()
                runtime_metrics = {
                    "failure_rate": float(m.failure_rate), "throughput": float(m.throughput),
                    "completed": float(m.completed), "failed": float(m.failed), "active": float(m.active),
                }
            except Exception:  # telemetry is best-effort; observation never crashes (MeL5)
                runtime_metrics = {}

        return ObservationWindow(
            window_id="obs-" + uuid.uuid4().hex, since_seq=since, until_seq=until,
            event_counts=dict(counts), by_source=dict(by_source),
            samples={k: tuple(v) for k, v in samples.items()},
            health_status=health_status, health_metrics=health_metrics, runtime_metrics=runtime_metrics,
        )

    @staticmethod
    def _extract(event_type: str, payload: Any, samples: dict[str, list[float]]) -> None:
        if event_type == "reasoning.concluded":
            samples["reasoning.confidence"].append(float(payload.get("confidence", 0.0)))
            if "confidence" not in payload:
                samples["reasoning.missing_confidence"].append(1.0)
        elif event_type == "prediction.forecast":
            samples["prediction.confidence"].append(float(payload.get("confidence", 0.0)))
            if not payload.get("hypothetical", True):
                samples["prediction.nonhypothetical"].append(1.0)  # constitutional red flag (PrL9)
        elif event_type == "prediction.reconciled":
            samples["prediction.surprise"].append(float(payload.get("surprise", 0.0)))
        elif event_type == "executive.decision":
            if payload.get("outcome") == "escalated":
                samples["executive.escalated"].append(1.0)
            elif payload.get("outcome") == "approved":
                samples["executive.approved"].append(1.0)
