"""Learning ABI — experiences, candidates, revisions, and immutable records.

Faithful to Phase 8 (LeL1–LeL41): Learning is the **only** faculty that commits
durable change (LeL1); it learns **only from validated, multi-episode experience**
(LeL7), **defaults to no change** (LeL9), makes every revision **reversible and
versioned** (LeL13/LeL21) with **provenance and confidence** (LeL24), and passes a
**hard constitutional gate** (LeL16) with **impact-scaled governance** (LeL33).
Immutable value objects and ``Protocol``s only; this module imports no sibling
module (never cycles).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class LearningKind(enum.Enum):
    BELIEF_CONSOLIDATION = "belief_consolidation"     # promote a corroborated belief
    PATTERN_GENERALIZATION = "pattern_generalization"  # a rule from recurring instances
    RULE_INDUCTION = "rule_induction"
    CALIBRATION = "calibration"                        # confidence recalibration (realized outcomes)
    PREDICTION_RECONCILIATION = "prediction_reconciliation"


class CandidateState(enum.Enum):
    PROPOSED = "proposed"
    AGGREGATING = "aggregating"       # accumulating multi-episode evidence
    VALIDATED = "validated"
    AUTHORIZED = "authorized"
    COMMITTED = "committed"
    REJECTED = "rejected"             # default (LeL9)
    DEFERRED = "deferred"             # awaiting human/executive review (LeL3/LeL17)
    ROLLED_BACK = "rolled_back"


class Verdict(enum.Enum):
    PASS = "pass"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"    # LeL7/LeL8
    INCONSISTENT = "inconsistent"                      # LeL23
    DISCONFIRMED = "disconfirmed"                      # LeL10 — opposing evidence dominates
    LOW_CONFIDENCE = "low_confidence"
    NEEDS_AUTHORIZATION = "needs_authorization"        # LeL3/LeL33


class Impact(enum.Enum):
    """Impact-scaled governance (LeL33): automatic → executive → human."""

    LOW = "low"           # automatic tier (validated, sandboxed, reversible — LeL34)
    MODERATE = "moderate"  # automatic tier, monitored
    HIGH = "high"          # gated — executive approval, escalating to human (LeL6/LeL17/LeL18)


# --------------------------------------------------------------------------- #
# Value objects (immutable)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Experience:
    """A single validated observation — *never* learned from alone (LeL7)."""

    exp_id: str
    kind: LearningKind
    statement: str
    negated: bool
    confidence: float
    evidence_handle: str      # provenance anchor (a State object) — reference, not a copy
    episode: str              # the episode that produced it (multi-episode accumulation)
    source: str
    seq: int


@dataclass(frozen=True, slots=True)
class LearningCandidate:
    """An aggregated, multi-episode candidate for durable change."""

    candidate_id: str
    kind: LearningKind
    statement: str
    negated: bool
    target_handle: str | None       # existing belief to revise (else create new)
    evidence: tuple[str, ...]        # provenance evidence handles (LeL24)
    episodes: tuple[str, ...]        # distinct episodes (>= min — LeL7)
    source_handles: tuple[str, ...]  # the R9 candidate objects being consumed
    support: float
    oppose: float
    aggregate_confidence: float
    impact: Impact
    state: CandidateState
    created_seq: int


@dataclass(frozen=True, slots=True)
class ValidationResult:
    verdict: Verdict
    confidence: float
    consistency_ok: bool
    evidence_count: int
    episode_count: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeRevision:
    """An immutable record of a durable, versioned, reversible knowledge change (LeL13/LeL21)."""

    revision_id: str
    target_handle: str
    from_version: int
    to_version: int
    kind: LearningKind
    statement: str
    confidence: float
    evidence: tuple[str, ...]
    provenance: tuple[str, ...]      # LeL24
    reversible: bool
    seq: int


@dataclass(frozen=True, slots=True)
class LearningRecord:
    """The immutable learning artifact (LeL19/LeL20/LeL31) — records commits *and* rejections."""

    record_id: str
    candidate_id: str
    kind: LearningKind
    verdict: Verdict
    committed: bool
    revision: KnowledgeRevision | None
    confidence: float
    impact: Impact
    evidence: tuple[str, ...]
    episodes: tuple[str, ...]
    authorized_by: str               # "automatic" | "executive" | "human" | ""
    provenance: tuple[str, ...]
    reversible: bool
    trace: tuple[str, ...]
    digest: str
    seq: int


@dataclass(frozen=True, slots=True)
class LearningReport:
    report_id: str
    examined: int
    committed: int
    deferred: int
    rejected: int
    records: tuple[LearningRecord, ...]
    seq: int


@dataclass(frozen=True, slots=True)
class LearningConfig:
    min_episodes: int = 3            # never learn from one event (LeL7)
    min_evidence: int = 3
    min_confidence: float = 0.6      # LeL9 burden of proof
    disconfirm_margin: float = 0.15  # support must exceed opposition by this (LeL10)
    revision_margin: float = 0.1     # to overwrite verified knowledge (LeL12)
    consistency_margin: float = 0.1  # LeL23
    commit_budget: int = 16          # bounded per cycle (LeL37)
    calibration_min: int = 5         # reconciled outcomes before recalibrating (LeL26)
    history_limit: int = 512
    admin_scope: str = "state:admin"
    high_impact_stakes: float = 0.85
    # keywords that force HIGH impact (safety/identity/policy — LeL6/LeL17/LeL18)
    high_impact_markers: tuple[str, ...] = ("identity", "safety", "policy", "core", "constitution")


@dataclass(frozen=True, slots=True)
class LearningMetricsSnapshot:
    cycles: int
    examined: int
    committed: int
    deferred: int
    rejected: int
    rolled_back: int
    revisions: int
    calibrations: int
    experiences_collected: int
    false_learning_rate: float       # rejections / examined (LeL39)


@dataclass(frozen=True, slots=True)
class LearningHealthReport:
    healthy: bool
    detail: str
    committed: int
    rejected: int
    false_learning_rate: float
    integrity_ok: bool


@dataclass(frozen=True, slots=True)
class AuthorizationOutcome:
    approved: bool
    escalated: bool          # -> human review gate (deferred)
    authority: str
    reason: str


# --------------------------------------------------------------------------- #
# Ports — authorization routed through the Runtime (no sibling-engine imports)
# --------------------------------------------------------------------------- #


@runtime_checkable
class AuthorizationPort(Protocol):
    """Requests Executive authorization for above-automatic-tier changes (LeL3),
    routed through the Runtime. Learning never governs; the Executive authorizes."""

    def authorize(self, candidate: LearningCandidate, context: Any) -> AuthorizationOutcome: ...
