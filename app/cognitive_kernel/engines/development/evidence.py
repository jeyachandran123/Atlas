"""The Development Evidence Aggregator (item 5) — long-term, aggregate, read-only (DeL12).

Development is trend-based and aggregate, never per-event. This aggregator builds a
long-horizon :class:`DevelopmentWindow` from the *cumulative* Ledger (every faculty's
recorded traces) plus read-only State facts (e.g. the count of consolidated beliefs —
Learning's realized output, DeL10). It imports no engine and writes nothing.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from ...contracts import KernelServices
from ...state import CognitiveStateManager, ObjectStatus, ObjectType, Region
from .contracts import DevelopmentWindow


class DevelopmentEvidenceAggregator:
    def __init__(self, services: KernelServices, state: CognitiveStateManager) -> None:
        self._services = services
        self._state = state

    def aggregate(self) -> DevelopmentWindow:
        counts: dict[str, int] = defaultdict(int)
        by_source: dict[str, int] = defaultdict(int)
        meta_audits = meta_compliant = 0
        for entry in self._services.ledger.read(since=0):  # cumulative long-term view
            ev = entry.event
            counts[ev.type] += 1
            by_source[ev.source] += 1
            if ev.type == "metacognition.audit":
                meta_audits += 1
                if ev.payload.get("compliant"):
                    meta_compliant += 1

        reasoning_total = counts["reasoning.concluded"] + counts["reasoning.escalated"]
        attention_total = counts["attention.ignition"] + counts["attention.rest"]
        rates = {
            "reasoning.volume": float(reasoning_total),
            "reasoning.success": counts["reasoning.concluded"] / max(1, reasoning_total),
            "reasoning.escalation": counts["reasoning.escalated"] / max(1, reasoning_total),
            "prediction.volume": float(counts["prediction.forecast"]),
            "prediction.reconciled": float(counts["prediction.reconciled"]),
            "attention.volume": float(attention_total),
            "attention.ignition_rate": counts["attention.ignition"] / max(1, attention_total),
            "wm.loads": float(counts["working_memory.loaded"]),
            "wm.evictions": float(counts["working_memory.evicted"]),
            "executive.decisions": float(counts["executive.decision"]),
            "executive.escalations": float(counts["executive.escalation"]),
            "meta.reflections": float(counts["metacognition.reflection"]),
            "meta.compliance": (meta_compliant / meta_audits) if meta_audits else 1.0,
            "learning.cycles": float(counts["learning.cycle"]),
            "learning.committed": float(counts["learning.committed"]),
        }
        return DevelopmentWindow(
            window_id="dev-" + uuid.uuid4().hex, horizon=sum(counts.values()),
            event_counts=dict(counts), by_source=dict(by_source), rates=rates,
            state_facts=self._state_facts(),
        )

    def _state_facts(self) -> dict[str, float]:
        beliefs = self._state.query(region=Region.R5_BELIEF, type=ObjectType.BELIEF, status=ObjectStatus.ACTIVE)
        learned = sum(1 for b in beliefs if b.payload.get("consolidated"))
        return {"learned_beliefs": float(learned), "active_beliefs": float(len(beliefs))}
