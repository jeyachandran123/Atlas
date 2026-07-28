"""UnityWorks Executive Engine — the governance authority (Phase 5, Tier 2).

The Executive Mind governs the object level: what should happen, when, why, with
which resources, under which policy. It governs by **standing policy, bounded
resource allocation, and exception-handling** (subsidiarity) — engaging its own
scarce attention only for the non-routine, cross-cutting, high-stakes, and
strategic, while the local governors handle the routine. It owns the goal
*portfolio*, allocates cognition as a *central bank*, resolves conflicts by a
fixed *auditable ladder*, legislates by *evolving policy*, and coordinates every
faculty **only through runtime-routed hooks** — never by reasoning, attending,
predicting, or learning itself. It is a decomposed, bounded, safety-subordinate,
human-escalating *mechanism*, not a homunculus (ExL1–ExL30).
"""

from __future__ import annotations

from .contracts import (
    Allocation,
    AllocationResult,
    AttentionControlPort,
    Conflict,
    ConflictType,
    DecisionKind,
    DecisionOutcome,
    Directive,
    ExecutiveConfig,
    ExecutiveHealthReport,
    ExecutiveMetricsSnapshot,
    ExecutiveMode,
    Goal,
    GoalState,
    GoalTier,
    GovernanceDashboard,
    GovernanceOutcome,
    Policy,
    PolicyDecision,
    PolicyEffect,
    PolicyFamily,
    PredictionRiskPort,
    Priority,
    ReasoningControlPort,
    ReasoningProposal,
    ResolutionBasis,
    ResourceKind,
)
from .engine import ExecutiveEngine
from .errors import (
    BudgetExceededError,
    ConstitutionalViolation,
    ExecutiveError,
    ExecutiveSecurityError,
    GoalNotFoundError,
    OwnershipError,
    UnknownExecutiveOperationError,
)
from .ports import (
    NullPredictionRiskPort,
    RuntimeAttentionPort,
    RuntimeReasoningPort,
)

__all__ = [
    "ExecutiveEngine",
    # ports
    "RuntimeReasoningPort",
    "RuntimeAttentionPort",
    "NullPredictionRiskPort",
    "ReasoningControlPort",
    "AttentionControlPort",
    "PredictionRiskPort",
    # value objects
    "ReasoningProposal",
    "Goal",
    "GoalTier",
    "GoalState",
    "Policy",
    "PolicyFamily",
    "PolicyEffect",
    "PolicyDecision",
    "Priority",
    "Allocation",
    "AllocationResult",
    "ResourceKind",
    "Conflict",
    "ConflictType",
    "ResolutionBasis",
    "DecisionKind",
    "DecisionOutcome",
    "Directive",
    "GovernanceOutcome",
    "GovernanceDashboard",
    "ExecutiveConfig",
    "ExecutiveMode",
    "ExecutiveMetricsSnapshot",
    "ExecutiveHealthReport",
    # errors
    "ExecutiveError",
    "ExecutiveSecurityError",
    "ConstitutionalViolation",
    "GoalNotFoundError",
    "OwnershipError",
    "BudgetExceededError",
    "UnknownExecutiveOperationError",
]
