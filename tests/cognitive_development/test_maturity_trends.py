"""Unit tests: maturity assessment, trends, gaps, limitations, policy."""

from __future__ import annotations

from app.cognitive_kernel.engines.development.contracts import (
    Capability,
    DevelopmentConfig,
    LimitationKind,
    MaturityLevel,
    ProposalKind,
    ReviewTier,
    TrendDirection,
)
from app.cognitive_kernel.engines.development.limitations import ArchitecturalLimitationDetector, GapAnalyzer
from app.cognitive_kernel.engines.development.maturity import CapabilityMaturityModel
from app.cognitive_kernel.engines.development.policy import DevelopmentPolicyManager
from app.cognitive_kernel.engines.development.trends import LongTermTrendAnalyzer

from ._dv import window

CFG = DevelopmentConfig()


# --- maturity --------------------------------------------------------------- #


def test_maturity_rises_with_success_and_volume() -> None:
    cmm = CapabilityMaturityModel(CFG)
    strong = cmm.assess(Capability.REASONING, window(rates={"reasoning.volume": 40, "reasoning.success": 1.0}),
                        version=1)
    weak = cmm.assess(Capability.REASONING, window(rates={"reasoning.volume": 40, "reasoning.success": 0.2}),
                      version=1)
    assert strong.maturity > weak.maturity and strong.maturity is MaturityLevel.OPTIMIZING


def test_maturity_is_evidence_gated() -> None:
    cmm = CapabilityMaturityModel(CFG)
    # High score but tiny evidence -> cannot certify above DEVELOPING (DeL2/DeL15).
    a = cmm.assess(Capability.REASONING, window(rates={"reasoning.volume": 2, "reasoning.success": 1.0}), version=1)
    assert a.maturity <= MaturityLevel.DEVELOPING and a.confidence < 1.0


def test_maturity_is_deterministic() -> None:
    cmm = CapabilityMaturityModel(CFG)
    w = window(rates={"reasoning.volume": 30, "reasoning.success": 0.8})
    assert cmm.assess(Capability.REASONING, w, version=1) == cmm.assess(Capability.REASONING, w, version=1)


# --- trends ----------------------------------------------------------------- #


def test_trend_detects_improvement_and_decline() -> None:
    ta = LongTermTrendAnalyzer(CFG)
    up = ta.analyze([{"scores": {"reasoning": 0.3}}, {"scores": {"reasoning": 0.6}}, {"scores": {"reasoning": 0.9}}])
    assert up[0].direction is TrendDirection.IMPROVING
    down = ta.analyze([{"scores": {"reasoning": 0.9}}, {"scores": {"reasoning": 0.6}}, {"scores": {"reasoning": 0.3}}])
    assert down[0].direction is TrendDirection.DECLINING and ta.regressing(down)


def test_trend_needs_data() -> None:
    ta = LongTermTrendAnalyzer(CFG)
    assert ta.analyze([{"scores": {"reasoning": 0.5}}])[0].direction is TrendDirection.INSUFFICIENT_DATA


# --- gaps & limitations ----------------------------------------------------- #


def test_gap_analysis_targets_mature() -> None:
    cmm = CapabilityMaturityModel(CFG)
    low = cmm.assess(Capability.PREDICTION, window(rates={"prediction.volume": 2}), version=1)
    gaps = GapAnalyzer(CFG).analyze([low])
    assert gaps and gaps[0].target is MaturityLevel.MATURE and gaps[0].gap >= 1


def test_capacity_limitation_from_wm_churn() -> None:
    w = window(rates={"wm.loads": 20, "wm.evictions": 40})
    lims = ArchitecturalLimitationDetector(CFG).detect(w, [], [])
    assert any(l.kind is LimitationKind.CAPACITY and l.capability is Capability.WORKING_MEMORY for l in lims)


# --- policy & constitutional protection ------------------------------------- #


def test_review_tiers() -> None:
    pm = DevelopmentPolicyManager(CFG)
    assert pm.review_tier(ProposalKind.CAPABILITY_ENHANCEMENT, "enhance reasoning") is ReviewTier.EXECUTIVE
    assert pm.review_tier(ProposalKind.ARCHITECTURAL_EVOLUTION, "evolve architecture") is ReviewTier.HUMAN


def test_constitution_touching_proposals_are_forbidden() -> None:
    pm = DevelopmentPolicyManager(CFG)
    assert pm.review_tier(ProposalKind.CAPABILITY_ENHANCEMENT, "amend the constitution") is ReviewTier.FORBIDDEN
    assert pm.review_tier(ProposalKind.NEW_FACULTY, "rewrite identity_core") is ReviewTier.FORBIDDEN  # DeL1/DeL16
