"""The Priority Manager (Phase 5 Ch2 §4) — the global, recomputed priority ordering.

Composes priority from strategic alignment, urgency, risk, confidence, owner
authority, and cost (Phase 1.5 §2.8) at the portfolio level. It *orders*; it does
not schedule or allocate (its consumers do). Recomputed and inspectable so the
mind can always answer *why* something is prioritized. Aging boosts (anti-starvation,
ExL17) are applied on top by the portfolio review.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .contracts import ExecutiveConfig, Goal, Priority


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


class PriorityManager:
    def __init__(self, config: ExecutiveConfig) -> None:
        self._config = config

    def _alignment(self, goal: Goal) -> float:
        return {"strategic": 1.0, "tactical": 0.6, "operational": 0.35, "micro": 0.2}[goal.tier.value]

    def score(self, goal: Goal, *, signals: Mapping[str, float] | None = None, aging: float = 0.0) -> Priority:
        s = dict(signals or {})
        components = {
            "strategic_alignment": s.get("strategic_alignment", self._alignment(goal)),
            "urgency": _clamp(s.get("urgency", 0.0)),
            "risk": _clamp(s.get("risk", 0.0)),
            "confidence": _clamp(s.get("confidence", 1.0)),
            "authority": _clamp(s.get("authority", 0.5)),
            "cost": _clamp(s.get("cost", 0.0)),
        }
        w = self._config.priority_weights
        score = (
            w["strategic_alignment"] * components["strategic_alignment"]
            + w["urgency"] * components["urgency"]
            + w["risk"] * components["risk"]
            + w["confidence"] * components["confidence"]
            + w["authority"] * components["authority"]
            - w["cost"] * components["cost"]
            + aging  # anti-starvation boost (ExL17)
        )
        return Priority(goal.goal_id, round(_clamp(score), 6), components)

    def order(self, priorities: Sequence[Priority]) -> tuple[str, ...]:
        return tuple(p.goal_id for p in sorted(priorities, key=lambda p: (-p.score, p.goal_id)))
