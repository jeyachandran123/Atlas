"""The Constitutional Compliance Monitor (item 14; MeL29 — always-on, non-suppressible).

Checks concrete, structural constitutional invariants against observed telemetry and
produces a :class:`ConstitutionalAuditReport` (item 40). It cites grounded evidence
(MeL14/MeL15) and never corrects — a violation is flagged and escalated, never
silently fixed (MeL31). This monitor runs on every reflection and cannot be disabled.
"""

from __future__ import annotations

import uuid

from .contracts import (
    ConstitutionalAuditReport,
    Finding,
    FindingKind,
    MetaConfig,
    ObservationWindow,
)


class ConstitutionalComplianceMonitor:
    def __init__(self, config: MetaConfig) -> None:
        self._config = config

    def audit(self, w: ObservationWindow, *, seq: int) -> ConstitutionalAuditReport:
        # (law, subject, holds?, detail-on-violation)
        checks = [
            ("PrL8: prediction writes no canonical state", "prediction",
             w.metric("prediction.canonical_writes", 0.0) == 0.0,
             f"canonical_writes={w.metric('prediction.canonical_writes', 0.0)}"),
            ("PrL9: predictions are tagged hypothetical", "prediction",
             len(w.samples.get("prediction.nonhypothetical", ())) == 0,
             f"{len(w.samples.get('prediction.nonhypothetical', ()))} non-hypothetical forecasts"),
            ("ReL3/ReL5: reasoning conclusions carry confidence", "reasoning",
             len(w.samples.get("reasoning.missing_confidence", ())) == 0,
             f"{len(w.samples.get('reasoning.missing_confidence', ()))} conclusions without confidence"),
            ("MeL9/MeL13: meta writes no canonical state", "metacognition",
             w.metric("metacognition.canonical_writes", 0.0) == 0.0,
             f"canonical_writes={w.metric('metacognition.canonical_writes', 0.0)}"),
            ("ExL4: executive resource allocation is bounded", "executive",
             w.metric("executive.committed_budget", 0.0) <= 1.0 + 1e-9,
             f"committed_budget={w.metric('executive.committed_budget', 0.0)}"),
        ]
        violations = []
        checked = []
        for law, subject, holds, detail in checks:
            checked.append(law)
            if not holds:
                violations.append(Finding(
                    finding_id="viol-" + uuid.uuid4().hex, kind=FindingKind.CONSTITUTIONAL_VIOLATION,
                    subject=subject, severity=1.0, confidence=0.95, detail=f"{law} — {detail}", evidence=(law,),
                ))
        return ConstitutionalAuditReport(
            report_id="audit-" + uuid.uuid4().hex, compliant=not violations, checked=tuple(checked),
            violations=tuple(violations), confidence=0.95, seq=seq,
        )
