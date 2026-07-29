"""UnityWorks Development System — long-term capability evolution (Phase 9, the final faculty).

Development is the constitutional authority for long-term cognitive evolution. It never
changes cognition directly: it studies long-term evidence, measures per-capability
maturity, detects architectural limitations, generates capability-evolution *proposals*,
produces developmental roadmaps, and supplies future architectural recommendations —
all as immutable, auditable, versioned artifacts requiring constitutional/human approval.
It performs no reasoning, learning, prediction, executive governance, or attention;
modifies no canonical state and no engine; never rewrites the constitution; never
auto-evolves architecture; imports no sibling engine; and is realized by Learning
(DeL1–DeL16). It is bounded and additive — the mind matures within its fixed laws.
"""

from __future__ import annotations

from .contracts import (
    Capability,
    CapabilityAssessment,
    CapabilityGap,
    DevelopmentArtifact,
    DevelopmentConfig,
    DevelopmentHealthReport,
    DevelopmentMetricsSnapshot,
    DevelopmentRoadmap,
    DevelopmentWindow,
    EvolutionProposal,
    Limitation,
    LimitationKind,
    MaturityLevel,
    ProposalKind,
    ProposalState,
    ReviewPort,
    ReviewTier,
    RoadmapItem,
    Trend,
    TrendDirection,
)
from .engine import DevelopmentEngine
from .errors import (
    ConstitutionalEvolutionError,
    DevelopmentError,
    DevelopmentSecurityError,
    ProposalNotFoundError,
    UnknownDevelopmentOperationError,
)
from .ports import NullReviewPort, RuntimeReviewPort

__all__ = [
    "DevelopmentEngine",
    # ports
    "RuntimeReviewPort",
    "NullReviewPort",
    "ReviewPort",
    # value objects
    "Capability",
    "MaturityLevel",
    "CapabilityAssessment",
    "Trend",
    "TrendDirection",
    "Limitation",
    "LimitationKind",
    "CapabilityGap",
    "EvolutionProposal",
    "ProposalKind",
    "ProposalState",
    "ReviewTier",
    "RoadmapItem",
    "DevelopmentRoadmap",
    "DevelopmentArtifact",
    "DevelopmentWindow",
    "DevelopmentConfig",
    "DevelopmentMetricsSnapshot",
    "DevelopmentHealthReport",
    # errors
    "DevelopmentError",
    "DevelopmentSecurityError",
    "ConstitutionalEvolutionError",
    "ProposalNotFoundError",
    "UnknownDevelopmentOperationError",
]
