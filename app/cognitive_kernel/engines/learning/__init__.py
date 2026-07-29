"""UnityWorks Learning Engine — the exclusive authority for durable change (Phase 8).

Learning transforms *validated experience* into durable cognitive improvement. It
never learns from a single event, a hallucination, or a hypothetical prediction; it
accumulates multi-episode evidence, validates it (defaulting to no change), measures
confidence, verifies consistency, requires constitutional authorization where
appropriate, and then performs **safe, versioned, reversible, provenance-bearing
updates through the Cognitive State Manager** — producing immutable learning records
and supporting rollback. It performs no reasoning, prediction, attention, executive
governance, or meta-governance, modifies no engine directly, bypasses neither the
Runtime nor the State Manager, and imports no sibling engine (LeL1–LeL41).
"""

from __future__ import annotations

from .contracts import (
    AuthorizationOutcome,
    AuthorizationPort,
    CandidateState,
    Experience,
    Impact,
    KnowledgeRevision,
    LearningCandidate,
    LearningConfig,
    LearningHealthReport,
    LearningKind,
    LearningMetricsSnapshot,
    LearningRecord,
    LearningReport,
    ValidationResult,
    Verdict,
)
from .engine import LearningEngine
from .errors import (
    ConsistencyViolationError,
    InsufficientEvidenceError,
    LearningError,
    LearningSecurityError,
    RollbackError,
    UnauthorizedLearningError,
    UnknownLearningOperationError,
)
from .ports import NullAuthorizationPort, RuntimeAuthorizationPort

__all__ = [
    "LearningEngine",
    # ports
    "RuntimeAuthorizationPort",
    "NullAuthorizationPort",
    "AuthorizationPort",
    "AuthorizationOutcome",
    # value objects
    "Experience",
    "LearningCandidate",
    "LearningKind",
    "CandidateState",
    "Impact",
    "Verdict",
    "ValidationResult",
    "KnowledgeRevision",
    "LearningRecord",
    "LearningReport",
    "LearningConfig",
    "LearningMetricsSnapshot",
    "LearningHealthReport",
    # errors
    "LearningError",
    "InsufficientEvidenceError",
    "ConsistencyViolationError",
    "UnauthorizedLearningError",
    "LearningSecurityError",
    "RollbackError",
    "UnknownLearningOperationError",
]
