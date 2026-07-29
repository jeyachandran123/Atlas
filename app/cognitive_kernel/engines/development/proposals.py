"""Evolution Proposal Generator (item 9) + Growth Planner + Roadmap (items 8/12).

Turns limitations and gaps into **evidence-backed, versioned evolution proposals**
and assembles a developmental roadmap. Every proposal is a *recommendation only* —
it improves the *use* of faculties (realized by Learning) or recommends a future
architectural evolution for human review; it is never applied (DeL10/DeL13). Proposals
touching the constitution or identity Core are blocked by policy (DeL1/DeL16).
"""

from __future__ import annotations

import uuid
from typing import Sequence

from .contracts import (
    Capability,
    CapabilityGap,
    DevelopmentConfig,
    DevelopmentRoadmap,
    EvolutionProposal,
    Limitation,
    LimitationKind,
    ProposalKind,
    ProposalState,
    ReviewTier,
    RoadmapItem,
)
from .policy import DevelopmentPolicyManager

_LIMITATION_PROPOSAL = {
    LimitationKind.CAPACITY: (ProposalKind.RESOURCE_SCALING, "scale capacity"),
    LimitationKind.COVERAGE: (ProposalKind.CAPABILITY_ENHANCEMENT, "enhance capability use via targeted learning"),
    LimitationKind.CALIBRATION: (ProposalKind.CALIBRATION_STRATEGY, "strengthen calibration strategy"),
    LimitationKind.INTEGRATION: (ProposalKind.INTEGRATION_IMPROVEMENT, "improve faculty integration"),
    LimitationKind.SCALABILITY: (ProposalKind.RESOURCE_SCALING, "scale for load"),
    LimitationKind.ROBUSTNESS: (ProposalKind.CAPABILITY_ENHANCEMENT, "stabilize capability"),
}
_LONG = {ProposalKind.ARCHITECTURAL_EVOLUTION, ProposalKind.NEW_FACULTY, ProposalKind.RESOURCE_SCALING}
_SHORT = {ProposalKind.CALIBRATION_STRATEGY}


class EvolutionProposalGenerator:
    def __init__(self, config: DevelopmentConfig, policy: DevelopmentPolicyManager) -> None:
        self._config = config
        self._policy = policy

    def generate(self, limitations: Sequence[Limitation], gaps: Sequence[CapabilityGap], *,
                 versions: dict, seq: int) -> list[EvolutionProposal]:
        proposals: list[EvolutionProposal] = []
        seen: set[tuple] = set()

        for lim in sorted(limitations, key=lambda l: (-l.severity, l.capability.value)):
            kind, verb = _LIMITATION_PROPOSAL[lim.kind]
            title = f"{verb} for {lim.capability.value}"
            tier = self._policy.review_tier(kind, title)
            if tier is ReviewTier.FORBIDDEN:  # constitutional protection (DeL1/DeL16)
                continue
            key = (kind, lim.capability)
            if key in seen:
                continue
            seen.add(key)
            proposals.append(self._mk(kind, lim.capability, title, lim.detail, lim.evidence, lim.severity,
                                      tier, (lim.limitation_id,), versions, seq))

        for gap in sorted(gaps, key=lambda g: (-g.gap, g.capability.value)):
            if gap.gap < 2:
                continue
            kind = ProposalKind.CAPABILITY_ENHANCEMENT
            title = f"advance {gap.capability.value} maturity"
            key = (kind, gap.capability)
            if key in seen:
                continue
            seen.add(key)
            tier = self._policy.review_tier(kind, title)
            proposals.append(self._mk(kind, gap.capability, title, gap.detail, (gap.gap_id,), 0.4,
                                      tier, (gap.gap_id,), versions, seq))
        return proposals

    def _mk(self, kind, cap, title, rationale, evidence, risk, tier, provenance, versions, seq) -> EvolutionProposal:
        return EvolutionProposal(
            proposal_id="prop-" + uuid.uuid4().hex, kind=kind, capability=cap, title=title, rationale=rationale,
            evidence=tuple(evidence), expected_benefit=f"raise {cap.value} maturity toward target",
            risk=round(max(0.0, min(1.0, risk)), 4), review_tier=tier, state=ProposalState.EVIDENCE_BACKED,
            version=versions.get(cap, 0) + 1, provenance=tuple(provenance), seq=seq,
        )


class RoadmapGenerator:
    def __init__(self, config: DevelopmentConfig) -> None:
        self._config = config

    def build(self, gaps: Sequence[CapabilityGap], proposals: Sequence[EvolutionProposal], *,
              version: int, seq: int) -> DevelopmentRoadmap:
        by_cap: dict[Capability, list[EvolutionProposal]] = {}
        for p in proposals:
            by_cap.setdefault(p.capability, []).append(p)
        items: list[RoadmapItem] = []
        for gap in sorted(gaps, key=lambda g: (-g.gap, g.capability.value)):
            cap_props = by_cap.get(gap.capability, [])
            kinds = {p.kind for p in cap_props}
            horizon = "long" if kinds & _LONG else ("short" if kinds & _SHORT else "medium")
            items.append(RoadmapItem(
                capability=gap.capability, from_level=gap.current, to_level=gap.target, horizon=horizon,
                proposals=tuple(p.proposal_id for p in cap_props), detail=gap.detail,
            ))
        return DevelopmentRoadmap(roadmap_id="road-" + uuid.uuid4().hex, version=version, items=tuple(items), seq=seq)
