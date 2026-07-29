"""Reflection trace, summary, and report builders (items 22/23/41; MeL21).

Meta-cognition's own process is traced and explainable (MeL21). These pure builders
assemble the reflection trace, a human-readable summary, the governance report, and
an integrity digest — the transparent record of *how* the mind judged itself.
"""

from __future__ import annotations

import hashlib
import json
from typing import Sequence

from .contracts import (
    Assessment,
    ConstitutionalAuditReport,
    Finding,
    GovernanceReport,
    InterventionRecommendation,
    ObservationWindow,
)


def build_trace(
    window: ObservationWindow,
    assessments: Sequence[Assessment],
    findings: Sequence[Finding],
    recommendations: Sequence[InterventionRecommendation],
    audit: ConstitutionalAuditReport,
) -> tuple[str, ...]:
    lines = [f"observed {window.total_events} events over [{window.since_seq}, {window.until_seq}]"]
    for a in assessments:
        note = f" {list(a.findings)}" if a.findings else ""
        lines.append(f"[{a.kind.value}] {a.subject}: {a.grade.value} "
                     f"(score {a.score:.3f}, conf {a.confidence:.3f}){note}")
    for f in findings:
        lines.append(f"FINDING {f.kind.value}/{f.subject} sev={f.severity:.2f} conf={f.confidence:.2f}: {f.detail}")
    lines.append("constitutional: " + ("COMPLIANT" if audit.compliant
                                        else f"{len(audit.violations)} VIOLATION(S)"))
    for r in recommendations:
        dest = f"{r.target_engine}.{r.target_op}" if r.target_engine else "record-only"
        lines.append(f"RECOMMEND {r.kind.value} -> {dest} (reversible={r.reversible}): {r.rationale}")
    return tuple(lines)


def summarize(assessments: Sequence[Assessment], findings: Sequence[Finding],
              audit: ConstitutionalAuditReport) -> str:
    worst = min((a.score for a in assessments), default=1.0)
    return (f"{len(assessments)} assessments, {len(findings)} finding(s), "
            f"lowest score {worst:.2f}, "
            f"{'constitutionally compliant' if audit.compliant else 'CONSTITUTIONAL VIOLATIONS'}")


def overall_confidence(assessments: Sequence[Assessment]) -> float:
    if not assessments:
        return 0.0
    return round(sum(a.confidence for a in assessments) / len(assessments), 6)


def digest(trace: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps(list(trace), sort_keys=True).encode("utf-8")).hexdigest()


def build_governance_report(executive: Assessment, findings: Sequence[Finding],
                            recommendations: Sequence[InterventionRecommendation], *, seq: int) -> GovernanceReport:
    import uuid
    gov_findings = tuple(f for f in findings if f.subject in ("executive", "runtime"))
    gov_recs = tuple(r for r in recommendations if r.target_engine == "executive")
    return GovernanceReport(report_id="gov-" + uuid.uuid4().hex, executive=executive,
                            findings=gov_findings, recommendations=gov_recs, seq=seq)
