"""Executive ABI — governance enums, value objects, and control ports.

Faithful to Phase 5 (ExL1–ExL30): the executive governs by **policy, allocation,
and exception** (the governance triad), owns the goal *portfolio*, arbitrates
decisions grounded in reasoning's output, resolves conflicts by a fixed ladder,
and coordinates faculties *only through runtime-routed control ports* — never by
importing or calling a sibling engine. This module imports no sibling engine and
no other executive module, so it is the stable ABI and can never take part in a
cycle. Every object here is an immutable value object or a ``Protocol``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


# --------------------------------------------------------------------------- #
# Enumerations — the closed vocabularies of governance
# --------------------------------------------------------------------------- #


class GoalTier(enum.Enum):
    """The governance altitude of a goal (Phase 5 §3.2; Phase 1.5 §3.4)."""

    STRATEGIC = "strategic"      # long-horizon; governed directly by the executive
    TACTICAL = "tactical"        # mid-horizon; governed by the executive
    OPERATIONAL = "operational"  # delegated to local processes
    MICRO = "micro"              # delegated


class GoalState(enum.Enum):
    """The lifecycle of a portfolio goal (Phase 5 §3.1)."""

    PROPOSED = "proposed"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELEGATED = "delegated"
    DORMANT = "dormant"
    ABANDONED = "abandoned"
    COMPLETED = "completed"
    FAILED = "failed"


class DecisionKind(enum.Enum):
    """The executive decision taxonomy (Phase 5 §4.2) — governance verbs, not world-action."""

    CONTINUE = "continue"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    DELEGATE = "delegate"
    ESCALATE = "escalate"
    RETRY = "retry"
    VERIFY = "verify"
    ASK_USER = "ask_user"
    RETRIEVE = "retrieve"
    GENERATE = "generate"
    REFLECT = "reflect"
    LEARN = "learn"
    WAIT = "wait"
    COMPARE = "compare"
    SWITCH_STRATEGY = "switch_strategy"
    # governance rulings over proposals / goals
    APPROVE = "approve"
    REJECT = "reject"
    ALLOCATE = "allocate"
    ABANDON = "abandon"
    COMPLETE = "complete"
    ENACT_POLICY = "enact_policy"


class DecisionOutcome(enum.Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    DEFERRED = "deferred"


class PolicyFamily(enum.Enum):
    """Standing-policy families with a fixed precedence (Phase 5 §7.2/§7.3)."""

    SAFETY = "safety"                # absolute
    IDENTITY = "identity"            # absolute
    CONVERSATION = "conversation"    # privacy/isolation
    REASONING = "reasoning"
    ATTENTION = "attention"
    GENERATION = "generation"
    WORKSPACE = "workspace"
    LEARNING = "learning"
    RESOURCE = "resource"


# Fixed precedence: Safety > Identity > privacy > operational > convenience (ExL22).
POLICY_PRECEDENCE: dict[PolicyFamily, int] = {
    PolicyFamily.SAFETY: 0,
    PolicyFamily.IDENTITY: 1,
    PolicyFamily.CONVERSATION: 2,
    PolicyFamily.REASONING: 3,
    PolicyFamily.ATTENTION: 3,
    PolicyFamily.GENERATION: 3,
    PolicyFamily.WORKSPACE: 3,
    PolicyFamily.LEARNING: 3,
    PolicyFamily.RESOURCE: 4,
}
# Families whose DENY is absolute and non-overridable (ExL7/ExL12).
ABSOLUTE_FAMILIES = frozenset({PolicyFamily.SAFETY, PolicyFamily.IDENTITY})


class PolicyEffect(enum.Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class ConflictType(enum.Enum):
    GOAL = "goal"
    REASONING = "reasoning"
    ATTENTION = "attention"
    PLANNING = "planning"
    IDENTITY = "identity"
    CONVERSATION = "conversation"
    RESOURCE = "resource"
    POLICY = "policy"
    SAFETY = "safety"


class ResolutionBasis(enum.Enum):
    """The fixed conflict-resolution ladder (Phase 5 §6.3; ExL23)."""

    SAFETY = "safety"          # absolute
    IDENTITY = "identity"      # absolute
    PRIORITY = "priority"
    CONFIDENCE = "confidence"
    AUTHORITY = "authority"
    COMPROMISE = "compromise"
    OVERRIDE = "override"
    ESCALATE = "escalate"


class ResourceKind(enum.Enum):
    """Cognitive budgets the executive allocates (Phase 5 §5.1)."""

    ATTENTION = "attention"
    WORKING_MEMORY = "working_memory"
    REASONING = "reasoning"
    PLANNING = "planning"
    REFLECTION = "reflection"
    LEARNING = "learning"
    PREDICTION = "prediction"
    CONVERSATION = "conversation"
    GENERATION = "generation"


class ExecutiveMode(enum.Enum):
    SUSTAINED = "sustained"   # maintaining goals/policy over time
    REACTIVE = "reactive"     # recruited by conflict/error/risk


# --------------------------------------------------------------------------- #
# Value objects (immutable)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ReasoningProposal:
    """A proposal the executive governs — typically a Reasoning product (ReL9).

    The executive *consumes* this through a public contract; it never reasons to
    produce it. ``confidence`` is reasoning's calibrated confidence (the executive
    applies its risk-scaled threshold to it, ExL13).
    """

    proposal_id: str
    statement: str
    confidence: float
    kind: str = "belief"                 # belief | action | plan | strategy | goal
    goal_id: str | None = None
    action: str | None = None            # for action proposals (world-effect intent)
    stakes: float = 0.0                  # 0..1
    reversibility: float = 1.0           # 1 = fully reversible
    safety_relevant: bool = False
    identity_relevant: bool = False
    evidence: tuple[str, ...] = ()       # supporting State handles (references, not copies)
    source: str = "reasoning"


@dataclass(frozen=True, slots=True)
class Goal:
    """A governed portfolio goal (persisted as a GOAL object in R2)."""

    goal_id: str
    title: str
    tier: GoalTier
    state: GoalState
    priority: float
    owner: str                            # the single accountable owner (ExL2)
    parent: str | None = None
    dependencies: tuple[str, ...] = ()
    success_condition: str | None = None
    deadline_seq: int | None = None
    budget: float = 0.0
    provenance: str = ""


@dataclass(frozen=True, slots=True)
class Policy:
    """Standing executive legislation (Phase 5 Ch7). Immutable; versioned by supersession."""

    policy_id: str
    family: PolicyFamily
    name: str
    effect: PolicyEffect
    predicate: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    scope: str = "global"                 # global | context | task
    version: int = 1
    enacted_seq: int = 0


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    effect: PolicyEffect
    dominant_family: PolicyFamily | None
    reason: str
    applied: tuple[str, ...]              # policy ids consulted
    requires_approval: bool = False
    absolute: bool = False               # a non-overridable safety/identity ruling


@dataclass(frozen=True, slots=True)
class Priority:
    goal_id: str
    score: float
    components: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class Allocation:
    resource: ResourceKind
    matter_id: str
    share: float
    reserved: bool = False


@dataclass(frozen=True, slots=True)
class AllocationResult:
    granted: bool
    resource: ResourceKind
    matter_id: str
    share: float
    committed_total: float
    reason: str


@dataclass(frozen=True, slots=True)
class Conflict:
    conflict_id: str
    ctype: ConflictType
    parties: tuple[str, ...]
    basis: ResolutionBasis
    winner: str | None
    resolved: bool
    escalated: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ExecutiveDecision:
    """An immutable governance ruling (persisted as an EXECUTIVE_DECISION in R9; ExL3)."""

    decision_id: str
    kind: DecisionKind
    outcome: DecisionOutcome
    subject: str                          # proposal id / goal id / conflict id
    rationale: str
    confidence: float
    threshold: float
    stakes: float
    reversibility: float
    constraints: tuple[str, ...]          # policy/identity/safety constraints that bounded it
    alternatives: tuple[str, ...]
    authority: str
    seq: int
    handle: str | None = None             # State handle once persisted


@dataclass(frozen=True, slots=True)
class Directive:
    """A governance directive issued to a faculty — routed via the Runtime (ExL8)."""

    target: str                           # engine name: attention | reasoning | working_memory | prediction
    operation: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class GovernanceOutcome:
    """The observable product of one governance pass."""

    decision: ExecutiveDecision
    authorized: bool
    directives: tuple[Directive, ...]
    goal_id: str | None
    seq: int


@dataclass(frozen=True, slots=True)
class ExecutiveConfig:
    autonomy_threshold: float = 0.6        # base confidence to decide autonomously (ExL13)
    escalation_stakes: float = 0.7         # stakes above which low confidence escalates
    max_active_goals: int = 7              # bounded working set (ExL15; Cowan-scale governance)
    total_budget: float = 1.0              # finite total cognitive resource (ExL4)
    safety_reservation: float = 0.1        # guaranteed share for safety monitoring
    aging_rate: float = 0.02               # anti-starvation aging (ExL17)
    admin_scope: str = "state:admin"
    executive_scope: str = "executive:admin"
    # priority composition weights (recomputed ordering, Phase 5 Ch2 §4)
    priority_weights: Mapping[str, float] = field(
        default_factory=lambda: MappingProxyType(
            {"strategic_alignment": 0.30, "urgency": 0.25, "risk": 0.15,
             "confidence": 0.10, "authority": 0.10, "cost": 0.10}
        )
    )


@dataclass(frozen=True, slots=True)
class ExecutiveMetricsSnapshot:
    governance_passes: int
    decisions: int
    approvals: int
    rejections: int
    escalations: int
    goals_created: int
    goals_completed: int
    goals_abandoned: int
    conflicts_resolved: int
    allocations: int
    policy_enactments: int
    interventions: int
    active_goals: int
    committed_budget: float


@dataclass(frozen=True, slots=True)
class ExecutiveHealthReport:
    healthy: bool
    detail: str
    mode: ExecutiveMode
    active_goals: int
    committed_budget: float
    budget_ok: bool


@dataclass(frozen=True, slots=True)
class GovernanceDashboard:
    """A read-only observability snapshot of the whole governance state (item 40)."""

    active_goals: tuple[Goal, ...]
    priority_order: tuple[str, ...]
    allocations: tuple[Allocation, ...]
    policies: tuple[Policy, ...]
    open_conflicts: tuple[Conflict, ...]
    recent_decisions: tuple[str, ...]
    mode: ExecutiveMode
    committed_budget: float
    metrics: ExecutiveMetricsSnapshot


# --------------------------------------------------------------------------- #
# Control ports — coordination through the Runtime only (ExL8; no engine imports)
# --------------------------------------------------------------------------- #


@runtime_checkable
class ReasoningControlPort(Protocol):
    """Directs the reasoning faculty (depth/strategy) and invokes it — via the Runtime.
    The executive *uses* reasoning (ExL10); it never reasons itself."""

    def set_strategy(self, strategy: str, context: Any) -> None: ...
    def set_deliberation(self, context: Any, *, max_steps: int | None = None, depth: int | None = None) -> None: ...
    def reason(self, request: Mapping[str, Any], context: Any) -> Mapping[str, Any] | None: ...


@runtime_checkable
class AttentionControlPort(Protocol):
    """Biases the attention competition strategically — via the Runtime, bounded by
    safety (ExL8; Phase 3 Ch6). The executive does not select consciousness itself."""

    def bias(self, target: str, delta: float, context: Any) -> None: ...


@runtime_checkable
class PredictionRiskPort(Protocol):
    """Requests risk evaluation / forecasts (items 20, 21). The executive never
    predicts; it requests. Null until a Prediction engine is wired."""

    def available(self) -> bool: ...
    def request(self, scenario: Mapping[str, Any], context: Any) -> Mapping[str, Any] | None: ...
