"""Development ABI — maturity, trends, limitations, proposals, and roadmaps.

Faithful to Phase 9 (DeL1–DeL16): Development produces *proposals only* — it
studies **aggregate, long-term** evidence (DeL12), measures **per-capability**
maturity (DeL9), is **bounded** (improves the *use* of faculties within fixed
limits — DeL13), is **realized by Learning** (DeL10), keeps every maturity change
**versioned/reversible/auditable** (DeL11), and **never alters the constitution or
identity Core** (DeL1/DeL16). Immutable value objects and ``Protocol``s only; this
module imports no sibling module (never cycles).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class Capability(enum.Enum):
    """The capabilities Development certifies — per-capability, never a global scalar (DeL9)."""

    ATTENTION = "attention"
    WORKING_MEMORY = "working_memory"
    REASONING = "reasoning"
    EXECUTIVE = "executive"
    PREDICTION = "prediction"
    METACOGNITION = "metacognition"
    LEARNING = "learning"
    CALIBRATION = "calibration"          # cross-cutting
    SELF_IMPROVEMENT = "self_improvement"  # cross-cutting


class MaturityLevel(enum.IntEnum):
    """Certified maturity (DeL2). Ordered so progression is comparable."""

    NASCENT = 1
    DEVELOPING = 2
    PROFICIENT = 3
    MATURE = 4
    OPTIMIZING = 5


class TrendDirection(enum.Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"
    INSUFFICIENT_DATA = "insufficient_data"


class LimitationKind(enum.Enum):
    CAPACITY = "capacity"            # e.g. working-memory saturation
    COVERAGE = "coverage"            # a capability stuck low
    CALIBRATION = "calibration"      # miscalibration persists
    INTEGRATION = "integration"      # faculties not composing well
    SCALABILITY = "scalability"
    ROBUSTNESS = "robustness"        # regression / instability


class ProposalKind(enum.Enum):
    CAPABILITY_ENHANCEMENT = "capability_enhancement"   # improve the *use* (Learning realizes it) — DeL10/DeL13
    CALIBRATION_STRATEGY = "calibration_strategy"
    INTEGRATION_IMPROVEMENT = "integration_improvement"
    RESOURCE_SCALING = "resource_scaling"
    ARCHITECTURAL_EVOLUTION = "architectural_evolution"  # recommendation for a future version (human review)
    NEW_FACULTY = "new_faculty"


class ReviewTier(enum.Enum):
    """Development governance — approval strength rises with impact (DeL3/DeL8)."""

    EXECUTIVE = "executive"       # capability-use enhancements
    HUMAN = "human"               # architectural / new-faculty / autonomy (DeL3)
    FORBIDDEN = "forbidden"       # constitution / identity Core — never proposed (DeL1/DeL16)


class ProposalState(enum.Enum):
    DRAFTED = "drafted"
    EVIDENCE_BACKED = "evidence_backed"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    ARCHIVED = "archived"


# --------------------------------------------------------------------------- #
# Value objects (immutable)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class DevelopmentWindow:
    """An immutable, long-horizon aggregate of cognitive activity (DeL12)."""

    window_id: str
    horizon: int                       # events observed
    event_counts: Mapping[str, int]
    by_source: Mapping[str, int]
    rates: Mapping[str, float]         # derived long-term rates
    state_facts: Mapping[str, float]   # read-only State-derived facts (e.g., learned-belief count)

    def count(self, event_type: str) -> int:
        return int(self.event_counts.get(event_type, 0))

    def rate(self, key: str, default: float = 0.0) -> float:
        return float(self.rates.get(key, default))


@dataclass(frozen=True, slots=True)
class CapabilityAssessment:
    """A per-capability maturity certification (DeL2/DeL9)."""

    capability: Capability
    maturity: MaturityLevel
    score: float
    confidence: float               # grounded in evidence volume (DeL2/DeL15)
    evidence_count: int
    version: int                    # certification version (DeL11)
    metrics: Mapping[str, float]
    rationale: str


@dataclass(frozen=True, slots=True)
class Trend:
    metric: str
    direction: TrendDirection
    first: float
    last: float
    slope: float
    samples: int


@dataclass(frozen=True, slots=True)
class Limitation:
    limitation_id: str
    kind: LimitationKind
    capability: Capability
    severity: float
    detail: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CapabilityGap:
    gap_id: str
    capability: Capability
    current: MaturityLevel
    target: MaturityLevel
    gap: int
    detail: str


@dataclass(frozen=True, slots=True)
class EvolutionProposal:
    """An immutable, evidence-backed, versioned capability-evolution proposal (proposals only)."""

    proposal_id: str
    kind: ProposalKind
    capability: Capability
    title: str
    rationale: str
    evidence: tuple[str, ...]
    expected_benefit: str
    risk: float
    review_tier: ReviewTier
    state: ProposalState
    version: int
    provenance: tuple[str, ...]
    seq: int


@dataclass(frozen=True, slots=True)
class RoadmapItem:
    capability: Capability
    from_level: MaturityLevel
    to_level: MaturityLevel
    horizon: str                    # "short" | "medium" | "long"
    proposals: tuple[str, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class DevelopmentRoadmap:
    roadmap_id: str
    version: int
    items: tuple[RoadmapItem, ...]
    seq: int


@dataclass(frozen=True, slots=True)
class DevelopmentArtifact:
    """The immutable development artifact (items 18/36; auditable — DeL11)."""

    artifact_id: str
    session_id: str
    window_id: str
    seq: int
    assessments: tuple[CapabilityAssessment, ...]
    trends: tuple[Trend, ...]
    limitations: tuple[Limitation, ...]
    gaps: tuple[CapabilityGap, ...]
    proposals: tuple[EvolutionProposal, ...]
    roadmap: DevelopmentRoadmap
    summary: str
    confidence: float
    digest: str


@dataclass(frozen=True, slots=True)
class DevelopmentConfig:
    min_horizon: int = 20                 # events for a confident long-term judgment (DeL12/DeL15)
    min_evidence: int = 12
    trend_window: int = 6                 # development cycles forming a trend
    trend_epsilon: float = 0.05
    target_maturity: MaturityLevel = MaturityLevel.MATURE
    history_limit: int = 512
    artifact_limit: int = 128
    admin_scope: str = "state:admin"
    # keywords that force FORBIDDEN review (constitution / identity Core — DeL1/DeL16)
    forbidden_markers: tuple[str, ...] = ("constitution", "identity_core", "core_law")
    # maturity score thresholds
    maturity_thresholds: Mapping[str, float] = field(
        default_factory=lambda: MappingProxyType(
            {"optimizing": 0.9, "mature": 0.75, "proficient": 0.55, "developing": 0.3}
        )
    )


@dataclass(frozen=True, slots=True)
class DevelopmentMetricsSnapshot:
    cycles: int
    assessments: int
    trends_detected: int
    limitations_detected: int
    gaps_detected: int
    proposals_generated: int
    proposals_submitted: int
    roadmaps: int
    artifacts: int
    events_observed: int
    canonical_writes: int                 # MUST remain 0 (DeL13)


@dataclass(frozen=True, slots=True)
class DevelopmentHealthReport:
    healthy: bool
    detail: str
    cycles: int
    canonical_writes: int
    regressing: bool


# --------------------------------------------------------------------------- #
# Ports — proposal review routed through the Runtime (no sibling-engine imports)
# --------------------------------------------------------------------------- #


@runtime_checkable
class ReviewPort(Protocol):
    """Submits an evolution proposal for review through the Runtime (DeL3/DeL8).
    Development proposes; the Executive/human reviews. It never applies anything."""

    def submit(self, proposal: EvolutionProposal, context: Any) -> bool: ...
