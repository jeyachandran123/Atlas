"""Prediction ABI — scenarios, forecasts, isolated branches, and read ports.

Faithful to Phase 6 (PrL1–PrL22): predictions are *hypotheses, never truth*
(PrL1), carry typed uncertainty and horizon-decayed calibrated confidence
(PrL3/PrL12), coexist as multiple futures (PrL4), estimate risk and opportunity
*asymmetrically* (PrL17), and run on **isolated, in-memory, reference-only
simulation branches** that never mutate reality (PrL8) and never become belief
(PrL9). Every object here is an immutable value object or a ``Protocol``; this
module imports no sibling module, so it is the stable ABI and never cycles.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class ScenarioKind(enum.Enum):
    """The kinds of future the mind imagines (Phase 6 §3.2). Bounded, not exhaustive."""

    SINGLE = "single"              # the one most-likely outcome (System-1)
    EXPECTED = "expected"          # the median future
    OPTIMISTIC = "optimistic"      # a favourable tail
    PESSIMISTIC = "pessimistic"    # an unfavourable tail
    TAIL_RISK = "tail_risk"        # the worst-case (over-weighted, PrL17)
    CREATIVE = "creative"          # a non-obvious combination
    COUNTERFACTUAL = "counterfactual"  # a contrary-to-fact world (PrL10/PrL16)
    SAMPLED = "sampled"


class BranchKind(enum.Enum):
    """A branch is distinguished by its branch point (PrL16)."""

    PREDICTION = "prediction"          # branches from the actual present
    COUNTERFACTUAL = "counterfactual"  # branches from a modified premise


class BranchState(enum.Enum):
    OPEN = "open"
    EVALUATED = "evaluated"
    DESTROYED = "destroyed"       # cleaned up (default, PrL13/item 36)
    ARCHIVED = "archived"         # retained for audit (hypothetical-tagged, PrL15)


class UncertaintyKind(enum.Enum):
    NONE = "none"
    EPISTEMIC = "epistemic"   # reducible — more evidence/simulation would help
    ALEATORIC = "aleatoric"   # irreducible randomness in the world


# --------------------------------------------------------------------------- #
# Value objects (immutable)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Driver:
    """A causal factor of a future — parsed read-only from conscious/canonical
    content (a cause->effect link). ``impact`` is signed: positive = opportunity,
    negative = risk (the asymmetry the mind must preserve, PrL17)."""

    name: str
    probability: float
    impact: float
    source: str = ""            # source object handle (reference, not a copy)
    note: str = ""


@dataclass(frozen=True, slots=True)
class PredictionRequest:
    """An Executive request to imagine a future (the only sanctioned trigger, PrL20)."""

    request_id: str
    target: str = "outcome"           # the statement/outcome being forecast
    horizon: int = 1                  # steps into the future (PrL5 expiry / PrL12 decay)
    baseline: float = 0.0             # prior tendency of the outcome
    drivers: tuple[Driver, ...] = ()  # explicit drivers (augment conscious ones)
    num_scenarios: int = 5
    num_samples: int = 0              # 0 -> config default
    interventions: Mapping[str, bool] = field(default_factory=lambda: MappingProxyType({}))  # counterfactual forcing
    seed: int | None = None           # deterministic sampling seed
    stakes: float = 0.0               # scales scenario breadth (PrL19)
    threshold: float = 0.5            # outcome-occurrence threshold on the aggregate value
    retain: bool = False              # keep for audit (else destroyed — item 36/PrL13)
    use_working_memory: bool = False  # load conscious context via WM (read-only)
    context_handles: tuple[str, ...] = ()  # canonical handles to read drivers from (read-only)
    kind: BranchKind = BranchKind.PREDICTION
    source: str = "executive"


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    kind: ScenarioKind
    fired: tuple[str, ...]         # which drivers fired in this future
    outcome: bool                  # did the target outcome occur
    value: float
    probability: float
    rank_score: float
    note: str = ""


@dataclass(frozen=True, slots=True)
class Consequence:
    """One link in a multi-step consequence cascade (PrL18)."""

    step: int
    cause: str
    effect: str
    strength: float


@dataclass(frozen=True, slots=True)
class Forecast:
    """A confidence-calibrated, hypothetical forecast (PrL1: never truth)."""

    request_id: str
    target: str
    horizon: int
    branch_kind: BranchKind
    outcome_probability: float
    expected_value: float
    risk: float
    opportunity: float
    uncertainty: float
    uncertainty_kind: UncertaintyKind
    confidence: float
    scenarios: tuple[Scenario, ...]     # ranked, top-k (PrL4 coexisting futures)
    drivers: tuple[Driver, ...]
    assumptions: tuple[str, ...]        # recorded assumptions (item 21)
    cascade: tuple[Consequence, ...]    # multi-step consequences (PrL18)
    trace_digest: str
    hypothetical: bool = True           # QUARANTINE tag — never a belief (PrL9)
    grounded: bool = True               # PrL11 — ungrounded predictions are flagged
    seq: int = 0
    branch_id: str = ""


@dataclass(frozen=True, slots=True)
class RiskForecast:
    """The Executive Risk API product (item 31) — asymmetric, tail-weighted (PrL17)."""

    request_id: str
    risk: float
    severity: float
    probability: float
    top_drivers: tuple[str, ...]
    confidence: float
    uncertainty: float
    hypothetical: bool = True


@dataclass(frozen=True, slots=True)
class SimulationBranch:
    """An isolated, immutable, reference-only simulation sandbox (PrL8/PrL9).

    It holds *references* to canonical handles (never copies) and drivers; it can
    never write to the real cognitive line — isolation is guaranteed by there
    being no write path at all."""

    branch_id: str
    request_id: str
    kind: BranchKind
    base_context: str
    created_seq: int
    references: tuple[str, ...]     # canonical handles read into the sandbox (read-only)
    drivers: tuple[Driver, ...]
    state: BranchState = BranchState.OPEN
    hypothetical: bool = True


@dataclass(frozen=True, slots=True)
class PredictionConfig:
    default_samples: int = 256
    default_scenarios: int = 5
    max_horizon: int = 32               # PrL5
    max_open_branches: int = 16         # simulation budget (PrL13)
    max_samples: int = 4096             # anytime bound (PrL13)
    default_seed: int = 1729            # deterministic default
    horizon_decay: float = 0.05         # confidence decays with horizon (PrL12)
    calibration: float = 0.9            # engine calibration (PrL7 — confidence != correctness)
    tail_risk_weight: float = 1.5       # over-weight tail risk (PrL17)
    ungrounded_confidence: float = 0.2  # cap for evidence-free predictions (PrL11)
    retain_default: bool = False        # destroy after completion unless retained (item 36)
    history_limit: int = 256
    admin_scope: str = "state:admin"


@dataclass(frozen=True, slots=True)
class PredictionMetricsSnapshot:
    forecasts: int
    risk_assessments: int
    counterfactuals: int
    branches_created: int
    branches_destroyed: int
    branches_archived: int
    scenarios_generated: int
    samples_run: int
    canonical_writes: int          # MUST remain 0 (PrL8 — proven by construction)
    open_branches: int


@dataclass(frozen=True, slots=True)
class PredictionHealthReport:
    healthy: bool
    detail: str
    open_branches: int
    budget_ok: bool
    canonical_writes: int


# --------------------------------------------------------------------------- #
# Read ports — read-only, runtime-routed (no sibling-engine imports)
# --------------------------------------------------------------------------- #


@runtime_checkable
class WorkingMemoryReadPort(Protocol):
    """Reads the conscious focus (read-only). Prediction consumes conscious content
    only through Working Memory (integration requirement); it never mutates WM."""

    def conscious_refs(self, context: Any) -> Sequence[str]: ...


@runtime_checkable
class ReasoningFeedbackPort(Protocol):
    """Inbound feedback from reasoning for reconciliation/calibration (PrL22). Prediction
    consumes reasoning outputs through public contracts; it never reasons."""

    def note_outcome(self, request_id: str, observed: float, context: Any) -> None: ...
