"""UnityWorks Meta-Cognition Engine — the independent oversight faculty (Phase 7, Tier 3).

Meta-Cognition evaluates the *quality* of cognition; its purpose is not cognition
but evaluating cognition. It continuously observes cognitive processes (through the
Ledger, Health Monitor, and Runtime telemetry — grounded in traces, not
introspection), assesses every faculty, detects failures/drift/bias/contradiction/
fatigue/miscalibration, monitors constitutional compliance, generates transparent,
immutable reflection artifacts, and **recommends** interventions routed to the
Executive through the Runtime — while never performing reasoning, prediction,
attention, executive governance, or learning, never modifying canonical state, and
never bypassing the Runtime or importing a sibling engine. It is additive and
non-load-bearing for authority (MeL1–MeL35): remove it and reliability degrades,
authority does not.
"""

from __future__ import annotations

from .contracts import (
    Assessment,
    AssessmentKind,
    ConstitutionalAuditReport,
    Finding,
    FindingKind,
    Grade,
    GovernanceReport,
    HealthLevel,
    InterventionKind,
    InterventionPort,
    InterventionRecommendation,
    MetaConfig,
    MetaHealthReport,
    MetaMetricsSnapshot,
    ObservationWindow,
    ReflectionArtifact,
    ReflectionState,
)
from .engine import MetaCognitionEngine
from .errors import (
    MetaError,
    MetaSecurityError,
    ReflectionNotFoundError,
    UnknownMetaOperationError,
)
from .ports import NullInterventionPort, RuntimeInterventionPort

__all__ = [
    "MetaCognitionEngine",
    # ports
    "RuntimeInterventionPort",
    "NullInterventionPort",
    "InterventionPort",
    # value objects
    "ObservationWindow",
    "Assessment",
    "AssessmentKind",
    "Grade",
    "HealthLevel",
    "Finding",
    "FindingKind",
    "InterventionKind",
    "InterventionRecommendation",
    "ConstitutionalAuditReport",
    "GovernanceReport",
    "ReflectionArtifact",
    "ReflectionState",
    "MetaConfig",
    "MetaMetricsSnapshot",
    "MetaHealthReport",
    # errors
    "MetaError",
    "MetaSecurityError",
    "ReflectionNotFoundError",
    "UnknownMetaOperationError",
]
