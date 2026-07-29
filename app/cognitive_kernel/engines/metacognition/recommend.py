"""The Intervention Recommendation Engine (item 24; MeL6 — the safe side only).

Maps findings and assessments to **recommendations** — never actions. Every
recommendation is reversible (MeL20), routed to the **Executive** (it cannot bypass
governance — MeL2), and confidence/severity-qualified. Constitutional violations
recruit a circuit-breaker halt plus human escalation (MeL8/MeL31); miscalibration
recommends more prediction; contradiction recommends more reasoning; failures and
drift recommend executive review. Meta proposes; the Executive disposes.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from .contracts import (
    INTERVENTION_ROUTES,
    Assessment,
    Finding,
    FindingKind,
    InterventionKind,
    InterventionRecommendation,
    MetaConfig,
)


def _rec(kind: InterventionKind, subject: str, reason: str, severity: float, seq: int) -> InterventionRecommendation:
    engine, op = INTERVENTION_ROUTES[kind]
    if kind in (InterventionKind.HALT, InterventionKind.RESUME):
        payload = {"matter_id": subject}
    else:
        payload = {"subject": subject, "reason": reason}
    return InterventionRecommendation(
        rec_id="rec-" + uuid.uuid4().hex, kind=kind, target_engine=engine, target_op=op, payload=payload,
        subject=subject, rationale=reason, severity=max(0.0, min(1.0, severity)), reversible=True,
        requested=False, seq=seq,
    )


class InterventionRecommendationEngine:
    def __init__(self, config: MetaConfig) -> None:
        self._config = config

    def recommend(self, findings: Sequence[Finding], assessments: Sequence[Assessment], *, seq: int
                  ) -> list[InterventionRecommendation]:
        recs: list[InterventionRecommendation] = []
        for f in findings:
            if f.kind is FindingKind.CONSTITUTIONAL_VIOLATION:
                recs.append(_rec(InterventionKind.HALT, f.subject,
                                 f"circuit-breaker: {f.detail} (MeL8)", 1.0, seq))
                recs.append(_rec(InterventionKind.ESCALATE, f.subject,
                                 f"constitutional violation escalated to human: {f.detail} (MeL31)", 1.0, seq))
            elif f.kind is FindingKind.FAILURE:
                recs.append(_rec(InterventionKind.EXECUTIVE_REVIEW, f.subject, f.detail, f.severity, seq))
            elif f.kind in (FindingKind.MISCALIBRATION, FindingKind.BIAS):
                recs.append(_rec(InterventionKind.RECOMMEND_PREDICTION, f.subject, f.detail, f.severity, seq))
            elif f.kind is FindingKind.CONTRADICTION:
                recs.append(_rec(InterventionKind.RECOMMEND_REASONING, f.subject, f.detail, f.severity, seq))
            elif f.kind in (FindingKind.FATIGUE, FindingKind.DRIFT, FindingKind.INEFFICIENCY):
                recs.append(_rec(InterventionKind.EXECUTIVE_REVIEW, f.subject, f.detail, f.severity, seq))

        for a in assessments:
            if a.subject == "reasoning" and "low reasoning confidence" in a.findings:
                recs.append(_rec(InterventionKind.RECOMMEND_REASONING, "reasoning",
                                 "low reasoning confidence — recommend deeper deliberation", 0.5, seq))
            if a.subject == "attention" and a.findings:
                recs.append(_rec(InterventionKind.RECOMMEND_REBIAS, "attention",
                                 "; ".join(a.findings), 0.5, seq))

        # De-duplicate by (kind, subject), keep the first (highest-priority) occurrence.
        seen: set[tuple[str, str]] = set()
        unique: list[InterventionRecommendation] = []
        for r in recs:
            key = (r.kind.value, r.subject)
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique
