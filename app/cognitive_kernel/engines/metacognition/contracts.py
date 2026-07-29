"""Meta-Cognition ABI — assessments, findings, reflection artifacts, interventions.

Faithful to Phase 7 (MeL1–MeL35): meta-cognition *evaluates the quality of
cognition* and never performs it (MeL1/MeL4); it grounds its self-model in observed
**traces** (the Ledger), not introspection (MeL16); every judgment is a
**confidence-qualified hypothesis** (MeL17/MeL18); every intervention is on the safe
side (HALT/SLOW/SHAPE/FLAG — MeL6), reversible (MeL20), routed to the **Executive**
(it cannot bypass governance — MeL2), and audited (MeL19). Immutable value objects
and ``Protocol``s only; this module imports no sibling module (never cycles).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class AssessmentKind(enum.Enum):
    HEALTH = "health"
    PERFORMANCE = "performance"
    EXECUTIVE = "executive"
    REASONING = "reasoning"
    PREDICTION = "prediction"
    ATTENTION = "attention"
    WORKING_MEMORY = "working_memory"
    RUNTIME = "runtime"
    CONSTITUTIONAL = "constitutional"


class Grade(enum.Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    CRITICAL = "critical"


class HealthLevel(enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class FindingKind(enum.Enum):
    """Each pathology has a dedicated detector (MeL26)."""

    FAILURE = "failure"
    DRIFT = "drift"
    BIAS = "bias"
    CONTRADICTION = "contradiction"
    FATIGUE = "fatigue"
    MISCALIBRATION = "miscalibration"
    INEFFICIENCY = "inefficiency"
    CONSTITUTIONAL_VIOLATION = "constitutional_violation"


class InterventionKind(enum.Enum):
    """The safe side only (MeL6): halt/flag/recommend — never start/commit/authorize.
    Every intervention is routed to the Executive (MeL2) and is reversible (MeL20)."""

    HALT = "halt"                    # circuit-breaker pause (recoverable, MeL7/MeL8)
    RESUME = "resume"                # release a halt
    ESCALATE = "escalate"            # to human (MeL28/P10)
    RECOMMEND_REASONING = "recommend_reasoning"
    RECOMMEND_PREDICTION = "recommend_prediction"
    RECOMMEND_REBIAS = "recommend_rebias"
    EXECUTIVE_REVIEW = "executive_review"
    FLAG = "flag"                    # record only; no runtime request


class ReflectionState(enum.Enum):
    OPEN = "open"
    EVALUATED = "evaluated"
    RECORDED = "recorded"
    CLOSED = "closed"


# --------------------------------------------------------------------------- #
# Value objects (immutable)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ObservationWindow:
    """An immutable snapshot of observed cognitive activity (grounded in the Ledger,
    the health monitor, and runtime telemetry — never introspection, MeL16)."""

    window_id: str
    since_seq: int
    until_seq: int
    event_counts: Mapping[str, int]         # event type -> count
    by_source: Mapping[str, int]            # engine -> event count
    samples: Mapping[str, tuple[float, ...]]  # e.g. "reasoning.confidence" -> values
    health_status: Mapping[str, str]        # component -> status
    health_metrics: Mapping[str, float]     # "component.metric" -> value
    runtime_metrics: Mapping[str, float]

    def count(self, event_type: str) -> int:
        return int(self.event_counts.get(event_type, 0))

    def metric(self, key: str, default: float = 0.0) -> float:
        return float(self.health_metrics.get(key, self.runtime_metrics.get(key, default)))

    def mean(self, sample_key: str, default: float = 0.0) -> float:
        vals = self.samples.get(sample_key, ())
        return round(sum(vals) / len(vals), 6) if vals else default

    @property
    def total_events(self) -> int:
        return sum(self.event_counts.values())


@dataclass(frozen=True, slots=True)
class Assessment:
    """A confidence-qualified evaluation of one faculty (MeL17/MeL18)."""

    kind: AssessmentKind
    subject: str
    score: float                 # 0..1 (higher = better)
    grade: Grade
    level: HealthLevel
    confidence: float            # reliability of *this* judgment (MeL17)
    findings: tuple[str, ...]
    metrics: Mapping[str, float]
    rationale: str


@dataclass(frozen=True, slots=True)
class Finding:
    """A detected pattern (each kind has a dedicated detector — MeL26)."""

    finding_id: str
    kind: FindingKind
    subject: str
    severity: float              # 0..1
    confidence: float
    detail: str
    evidence: tuple[str, ...]    # cited grounded evidence (MeL14/MeL15)


@dataclass(frozen=True, slots=True)
class InterventionRecommendation:
    """A recommended intervention — explicit, reversible, Executive-authorized (MeL2/MeL6/MeL20)."""

    rec_id: str
    kind: InterventionKind
    target_engine: str           # always the Executive (MeL2), except FLAG
    target_op: str
    payload: Mapping[str, Any]
    subject: str
    rationale: str
    severity: float
    reversible: bool
    requested: bool = False      # whether it has been submitted through the Runtime
    seq: int = 0


@dataclass(frozen=True, slots=True)
class ConstitutionalAuditReport:
    """The Constitutional Compliance Monitor's product (item 40; always-on, MeL29)."""

    report_id: str
    compliant: bool
    checked: tuple[str, ...]
    violations: tuple[Finding, ...]
    confidence: float
    seq: int


@dataclass(frozen=True, slots=True)
class GovernanceReport:
    """A cognitive-governance oversight report (item 41)."""

    report_id: str
    executive: Assessment
    findings: tuple[Finding, ...]
    recommendations: tuple[InterventionRecommendation, ...]
    seq: int


@dataclass(frozen=True, slots=True)
class ReflectionArtifact:
    """The immutable reflection artifact (items 22/23/42; MeL21 — traced, MeL19 — auditable)."""

    artifact_id: str
    session_id: str
    window_id: str
    seq: int
    assessments: tuple[Assessment, ...]
    findings: tuple[Finding, ...]
    recommendations: tuple[InterventionRecommendation, ...]
    audit: ConstitutionalAuditReport
    trace: tuple[str, ...]
    summary: str
    confidence: float            # overall confidence in this reflection (MeL18)
    digest: str


@dataclass(frozen=True, slots=True)
class MetaConfig:
    low_confidence: float = 0.4              # reasoning/prediction confidence floor
    escalation_rate_max: float = 0.4         # healthy escalation ceiling
    contradiction_rate_max: float = 0.3
    miscalibration_max: float = 0.3          # mean prediction surprise ceiling
    fatigue_max: float = 0.9
    failure_rate_max: float = 0.2            # runtime failure-rate ceiling
    drift_delta: float = 0.15                # window-over-window change that signals drift
    min_evidence: int = 8                    # events for a fully-confident judgment (MeL17)
    history_limit: int = 256
    artifact_limit: int = 256
    auto_request: bool = False               # submit intervention requests automatically (default off)
    admin_scope: str = "state:admin"


@dataclass(frozen=True, slots=True)
class MetaMetricsSnapshot:
    reflections: int
    assessments: int
    findings: int
    recommendations: int
    interventions_requested: int
    audits: int
    violations_found: int
    artifacts: int
    events_observed: int
    canonical_writes: int                    # MUST remain 0 (MeL9/MeL13)


@dataclass(frozen=True, slots=True)
class MetaHealthReport:
    healthy: bool
    detail: str
    reflections: int
    last_compliant: bool
    canonical_writes: int


# --------------------------------------------------------------------------- #
# Ports — runtime-routed intervention (no sibling-engine imports)
# --------------------------------------------------------------------------- #


@runtime_checkable
class InterventionPort(Protocol):
    """Submits an intervention *request* through the Runtime to the Executive (MeL2).
    Meta recommends; it never performs the action itself (MeL6)."""

    def submit(self, recommendation: InterventionRecommendation, context: Any) -> bool: ...


# Intervention routing — every request goes to the Executive (MeL2). FLAG is record-only.
INTERVENTION_ROUTES: Mapping[InterventionKind, tuple[str, str]] = MappingProxyType({
    InterventionKind.HALT: ("executive", "pause"),
    InterventionKind.RESUME: ("executive", "resume"),
    InterventionKind.ESCALATE: ("executive", "escalate"),
    InterventionKind.RECOMMEND_REASONING: ("executive", "escalate"),
    InterventionKind.RECOMMEND_PREDICTION: ("executive", "escalate"),
    InterventionKind.RECOMMEND_REBIAS: ("executive", "escalate"),
    InterventionKind.EXECUTIVE_REVIEW: ("executive", "escalate"),
    InterventionKind.FLAG: ("", ""),
})
