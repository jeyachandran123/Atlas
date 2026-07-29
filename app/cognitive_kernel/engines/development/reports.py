"""Development trace, summary, and report builders (items 18/34).

Development's process is explainable and auditable. These pure builders assemble the
development trace, a human-readable summary, and an integrity digest — the transparent
record of *how* the mind assessed and planned its own long-term growth.
"""

from __future__ import annotations

import hashlib
import json
from typing import Sequence

from .contracts import (
    CapabilityAssessment,
    CapabilityGap,
    DevelopmentRoadmap,
    EvolutionProposal,
    Limitation,
    Trend,
)


def build_trace(window, assessments: Sequence[CapabilityAssessment], trends: Sequence[Trend],
                limitations: Sequence[Limitation], gaps: Sequence[CapabilityGap],
                proposals: Sequence[EvolutionProposal], roadmap: DevelopmentRoadmap) -> tuple[str, ...]:
    lines = [f"long-term evidence: {window.horizon} events"]
    for a in assessments:
        lines.append(f"[{a.capability.value}] {a.maturity.name} (score {a.score:.3f}, conf {a.confidence:.3f}) v{a.version}")
    for t in trends:
        lines.append(f"TREND {t.metric}: {t.direction.value} ({t.first:.3f} -> {t.last:.3f})")
    for l in limitations:
        lines.append(f"LIMITATION {l.kind.value}/{l.capability.value} sev={l.severity:.2f}: {l.detail}")
    for g in gaps:
        lines.append(f"GAP {g.capability.value}: {g.current.name} -> {g.target.name} (gap {g.gap})")
    for p in proposals:
        lines.append(f"PROPOSAL [{p.review_tier.value}] {p.kind.value}/{p.capability.value}: {p.title}")
    lines.append(f"ROADMAP v{roadmap.version}: {len(roadmap.items)} item(s)")
    return tuple(lines)


def summarize(assessments: Sequence[CapabilityAssessment], limitations: Sequence[Limitation],
              proposals: Sequence[EvolutionProposal]) -> str:
    mature = sum(1 for a in assessments if int(a.maturity) >= 4)
    return (f"{len(assessments)} capabilities assessed ({mature} mature+), "
            f"{len(limitations)} limitation(s), {len(proposals)} evolution proposal(s)")


def overall_confidence(assessments: Sequence[CapabilityAssessment]) -> float:
    if not assessments:
        return 0.0
    return round(sum(a.confidence for a in assessments) / len(assessments), 6)


def digest(trace: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps(list(trace), sort_keys=True).encode("utf-8")).hexdigest()
