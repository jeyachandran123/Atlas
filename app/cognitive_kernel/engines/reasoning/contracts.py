"""Reasoning ABI — types, strategies, episode value objects, and ports.

Faithful to Phase 4 (the Reasoning Faculty and ReL1–ReL14): a closed vocabulary
of reasoning *types* (Ch3) executed by selectable *strategies* (Ch5) over
*substitutable engines behind a port* (Ch2 §12, ReL1). Every object here is an
immutable value object or a ``Protocol`` — this module imports no sibling module,
so it can never take part in a cycle and is the stable ABI other layers depend on.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


# --------------------------------------------------------------------------- #
# Enumerations — the closed vocabularies (ReL6: type & strategy are explicit)
# --------------------------------------------------------------------------- #


class ReasoningType(enum.Enum):
    """The closed taxonomy of inference kinds (Phase 4, Ch3)."""

    DEDUCTIVE = "deductive"        # necessary consequences from firm premises
    INDUCTIVE = "inductive"        # generalise a rule from instances
    ABDUCTIVE = "abductive"        # infer the best explanation (default under uncertainty)
    ANALOGICAL = "analogical"      # transfer relational structure from a known case
    CAUSAL = "causal"              # reason about cause / effect
    PROBABILISTIC = "probabilistic"  # weigh uncertain evidence
    CONSTRAINT = "constraint"      # constraint satisfaction / consistency
    DIAGNOSTIC = "diagnostic"      # localise a fault (abduction + causal)
    COUNTERFACTUAL = "counterfactual"  # reason about alternatives (needs prediction)
    RECURSIVE = "recursive"        # a problem contains sub-problems of the same kind
    STRATEGIC = "strategic"        # long-horizon goals & trade-offs
    SCIENTIFIC = "scientific"      # hypothesise -> predict -> test -> revise


class ReasoningStrategy(enum.Enum):
    """The method repertoire (Phase 4, Ch5) — *how* a type is carried out."""

    LINEAR = "linear"                    # one deliberate chain (System-2 default)
    SEARCH = "search"                    # explore & evaluate many branches
    SELF_DEBATE = "self_debate"          # argue for and against
    DECOMPOSITION = "decomposition"      # split, solve, recombine
    ANALOGICAL_TRANSFER = "analogical_transfer"
    SIMULATION = "simulation"            # build a model and run it forward
    VERIFY_THEN_TRUST = "verify_then_trust"  # generate, then verify with another engine
    ENSEMBLE = "ensemble"                # run multiple engines; reconcile
    FAST_HEURISTIC = "fast_heuristic"    # one calibrated System-1 shortcut


class EpisodeState(enum.Enum):
    """Lifecycle of a reasoning episode (Phase 4, Ch4)."""

    INITIATED = "initiated"
    CONTINUING = "continuing"
    DIVERGING = "diverging"
    CONVERGING = "converging"
    INTERRUPTED = "interrupted"
    RESUMED = "resumed"
    TERMINATED_SUCCESS = "terminated_success"
    TERMINATED_BUDGET = "terminated_budget"
    TERMINATED_ESCALATE = "terminated_escalate"
    DECAYED = "decayed"


class TerminationReason(enum.Enum):
    """The principled stops (Phase 4, §9.3; ReL7)."""

    CONVERGED = "converged"                 # converged + sufficiently confident
    GOOD_ENOUGH = "good_enough"             # satisficing for the stakes
    DIMINISHING_RETURNS = "diminishing_returns"  # value-of-computation < cost
    BUDGET_EXHAUSTED = "budget_exhausted"
    IMPASSE = "impasse"                     # no progress -> escalate
    INTERRUPTED = "interrupted"             # preempted; resumable


class UncertaintyKind(enum.Enum):
    """Typed uncertainty (Phase 4, §7.3) determines the response to low confidence."""

    NONE = "none"
    EPISTEMIC = "epistemic"   # reducible -> reason more / seek information
    ALEATORIC = "aleatoric"   # irreducible -> hedge / present options


# --------------------------------------------------------------------------- #
# Parsed conscious content (references, never copies — OL7)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Evidence:
    """An asserted proposition drawn from a conscious State object (ReL12).

    ``handle`` is the *source* object handle — the anchor of evidence
    traceability (item 24). Reasoning copies nothing; it references.
    """

    handle: str
    statement: str
    negated: bool = False
    reliability: float = 1.0
    confidence: float = 1.0
    kind: str = "evidence"       # evidence | belief | percept | assumption
    weight: float = 0.0          # computed by the evaluator (reliability x confidence x relevance)


@dataclass(frozen=True, slots=True)
class Rule:
    """A conscious implication (for deduction / constraint derivation)."""

    handle: str
    antecedents: tuple[str, ...]
    consequent: str
    consequent_negated: bool = False
    reliability: float = 1.0


@dataclass(frozen=True, slots=True)
class CausalLink:
    """A conscious cause->effect edge (for causal / abductive reasoning)."""

    handle: str
    cause: str
    effect: str
    strength: float = 1.0


@dataclass(frozen=True, slots=True)
class Analogy:
    """A conscious source case whose relational structure may transfer."""

    handle: str
    relation: str
    conclusion: str
    conclusion_negated: bool = False
    strength: float = 1.0


@dataclass(frozen=True, slots=True)
class Hypothesis:
    """A candidate conclusion under test (Phase 4, Ch2 §5)."""

    hid: str
    statement: str
    negated: bool = False
    prior: float = 0.5
    confidence: float = 0.0
    supports: tuple[str, ...] = ()   # evidence handles that support it
    opposes: tuple[str, ...] = ()
    derivation: str = "generated"    # generated | deduced | abduced | induced | analogical
    depth: int = 0
    rationale: str = ""


# --------------------------------------------------------------------------- #
# Trace, products, requests, results (ReL5: no conclusion without a trace)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ReasoningStep:
    """One recorded step of the trace — premise, type, strategy, engine, product."""

    index: int
    rtype: ReasoningType
    strategy: ReasoningStrategy
    engine: str
    premises: tuple[str, ...]
    product: str
    confidence: float
    rationale: str
    depth: int = 0


@dataclass(frozen=True, slots=True)
class EngineRequest:
    """What the faculty hands a substitutable engine for one step (engine-agnostic)."""

    rtype: ReasoningType
    goal: str
    question: str
    question_negated: bool
    facts: Mapping[str, float]            # statement -> confidence (positive assertions)
    negations: Mapping[str, float]        # statement -> confidence (negated assertions)
    evidence: tuple[Evidence, ...]
    hypotheses: tuple[Hypothesis, ...]
    rules: tuple[Rule, ...]
    causes: tuple[CausalLink, ...]
    analogies: tuple[Analogy, ...]
    max_depth: int


@dataclass(frozen=True, slots=True)
class EngineProduct:
    """A substitutable engine's output for one step: a candidate + its own confidence.

    ``confidence`` is the engine's *self-reported* value; the faculty discounts it
    by the engine's calibration (ReL3) — an engine is never trusted at face value.
    """

    engine: str
    statement: str
    negated: bool
    confidence: float
    justification: str
    hypothesis_id: str | None = None
    premises: tuple[str, ...] = ()
    rtype: ReasoningType | None = None
    steps: tuple[ReasoningStep, ...] = ()   # sub-derivations (deduction/recursion)


@dataclass(frozen=True, slots=True)
class Conclusion:
    """The proposed product of an episode (never a commitment — ReL9)."""

    statement: str
    negated: bool
    confidence: float
    uncertainty: UncertaintyKind
    hypothesis_id: str | None
    supporting_evidence: tuple[str, ...]
    contradictions: tuple[str, ...]
    assumptions: tuple[str, ...]
    justification: str


@dataclass(frozen=True, slots=True)
class ReasoningRequest:
    """A request to reason. The faculty acts only on conscious content (ReL12)."""

    goal: str = ""
    question: str = ""                # the statement whose truth is sought (empty -> best explanation)
    question_negated: bool = False
    focus: tuple[str, ...] = ()       # restrict to these conscious targets (empty -> all conscious)
    type_hint: ReasoningType | None = None
    strategy_hint: ReasoningStrategy | None = None
    stakes: float = 0.0               # 0..1, scales the autonomy / escalation threshold (ReL13)
    reversibility: float = 1.0        # 1 = fully reversible; low reversibility raises the bar
    workspace: str | None = None
    max_steps: int | None = None


@dataclass(frozen=True, slots=True)
class ReasoningResult:
    """The observable product of an episode (ReL5 trace + calibrated confidence)."""

    episode_id: str
    concluded: bool
    conclusion: Conclusion | None
    hypotheses: tuple[Hypothesis, ...]
    steps: tuple[ReasoningStep, ...]
    state: EpisodeState
    termination: TerminationReason
    escalated: bool
    products: tuple[str, ...]          # belief handles written to R5
    learning_candidates: tuple[str, ...]  # proposals written to R9
    seq: int


@dataclass(frozen=True, slots=True)
class ReasoningConfig:
    """Bounds and thresholds (the reasoning economy, Ch9). Evolvable only by the
    gated Development hook (item 37)."""

    confidence_sufficient: float = 0.65    # base risk-scaled autonomy threshold (ReL13)
    escalation_stakes: float = 0.7         # stakes above which low confidence escalates
    max_steps: int = 12                    # episode budget (bounded rationality, P8)
    max_depth: int = 4                     # recursion bound (P8)
    max_hypotheses: int = 8
    diminishing_epsilon: float = 0.02      # value-of-computation stop (§9.3 S2)
    hysteresis_margin: float = 0.1         # strategy-switch stabilisation (anti-thrash)
    parsimony_penalty: float = 0.05        # Occam: penalty per extra assumption in an explanation
    fatigue_per_step: float = 0.03
    fatigue_recovery: float = 0.05
    ensemble_size: int = 2
    belief_status: str = "proposed"        # products are PROPOSED, never committed (ReL9)
    engine_calibration: Mapping[str, float] = field(
        default_factory=lambda: MappingProxyType(
            {
                # Verifiable symbolic derivation is exact; generation is least trusted (ReL3).
                "symbolic": 1.0, "probabilistic": 0.9, "heuristic": 0.7, "generative": 0.6,
            }
        )
    )


@dataclass(frozen=True, slots=True)
class ReasoningMetricsSnapshot:
    episodes: int
    steps: int
    hypotheses_generated: int
    deductions: int
    abductions: int
    inductions: int
    contradictions: int
    conflicts_resolved: int
    escalations: int
    interrupts: int
    resumptions: int
    engine_invocations: int
    fatigue: float


@dataclass(frozen=True, slots=True)
class ReasoningHealthReport:
    healthy: bool
    detail: str
    fatigue: float
    engines_available: int


# --------------------------------------------------------------------------- #
# Ports — the model-independence and no-direct-coupling boundaries
# --------------------------------------------------------------------------- #


@runtime_checkable
class ReasoningEnginePort(Protocol):
    """A substitutable reasoning engine (ReL1). The Generation Platform is one such
    engine *behind this port* — never "the reasoner". The faculty depends on the
    port, never on any engine's internals (P1/P6)."""

    @property
    def name(self) -> str: ...
    @property
    def handles(self) -> frozenset[ReasoningType]: ...
    def propose(self, request: EngineRequest, context: Any) -> EngineProduct | None: ...


@runtime_checkable
class PredictionPort(Protocol):
    """The Prediction hook (item 34). Reasoning never predicts; it *requests*
    forecasts/simulations here. A real Prediction engine plugs in behind this
    port (runtime-routed); until then a null implementation reports unavailable."""

    def available(self) -> bool: ...
    def request(self, scenario: Mapping[str, Any], context: Any) -> Mapping[str, Any] | None: ...


@runtime_checkable
class WorkingMemoryReadPort(Protocol):
    """The public, read-only Working-Memory surface Reasoning consumes (ReL12).
    Reasoning reads conscious content; it never owns or mutates WM."""

    def read_focus(self, workspace: str | None = None) -> Sequence[Any]: ...
    def contents(self, workspace: str | None = None) -> Sequence[Any]: ...
