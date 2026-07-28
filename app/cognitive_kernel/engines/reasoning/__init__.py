"""UnityWorks Reasoning Engine — the Thinking Mind (Phase 4).

The first engine that performs true cognitive inference. It transforms consciously
attended information into justified conclusions: it collects and weighs evidence,
generates and ranks hypotheses, runs deductive / inductive / abductive /
analogical / causal / constraint inference behind a *substitutable engine port*,
estimates calibrated confidence, guards its own consistency, knows when to stop,
and records an explainable, auditable trace — while committing nothing (it
proposes candidates for decision and learning). It is a *faculty*, not a wrapper:
engines change; the way UnityWorks thinks does not (ReL1). Built on the Kernel,
Runtime, State Manager, and Working Memory Engine through their public contracts.
"""

from __future__ import annotations

from .contracts import (
    Analogy,
    CausalLink,
    Conclusion,
    EngineProduct,
    EngineRequest,
    EpisodeState,
    Evidence,
    Hypothesis,
    PredictionPort,
    ReasoningConfig,
    ReasoningEnginePort,
    ReasoningHealthReport,
    ReasoningMetricsSnapshot,
    ReasoningRequest,
    ReasoningResult,
    ReasoningStep,
    ReasoningStrategy,
    ReasoningType,
    Rule,
    TerminationReason,
    UncertaintyKind,
    WorkingMemoryReadPort,
)
from .engine import ReasoningEngine
from .errors import (
    EngineUnavailableError,
    EpisodeNotFoundError,
    InvalidPremiseError,
    ReasoningError,
    ReasoningSecurityError,
    UnknownReasoningOperationError,
)
from .pool import (
    EnginePool,
    HeuristicReasoningEngine,
    NullPredictionPort,
    ProbabilisticReasoningEngine,
    SymbolicReasoningEngine,
    default_pool,
)
from .port import ReasoningWMPort

__all__ = [
    "ReasoningEngine",
    "ReasoningWMPort",
    # pool / engines behind the port
    "EnginePool",
    "SymbolicReasoningEngine",
    "ProbabilisticReasoningEngine",
    "HeuristicReasoningEngine",
    "NullPredictionPort",
    "default_pool",
    # value objects
    "ReasoningRequest",
    "ReasoningResult",
    "ReasoningConfig",
    "ReasoningType",
    "ReasoningStrategy",
    "EpisodeState",
    "TerminationReason",
    "UncertaintyKind",
    "Evidence",
    "Rule",
    "CausalLink",
    "Analogy",
    "Hypothesis",
    "Conclusion",
    "ReasoningStep",
    "EngineRequest",
    "EngineProduct",
    "ReasoningMetricsSnapshot",
    "ReasoningHealthReport",
    # ports
    "ReasoningEnginePort",
    "PredictionPort",
    "WorkingMemoryReadPort",
    # errors
    "ReasoningError",
    "InvalidPremiseError",
    "ReasoningSecurityError",
    "UnknownReasoningOperationError",
    "EngineUnavailableError",
    "EpisodeNotFoundError",
]
