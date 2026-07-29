"""UnityWorks Prediction Engine — the faculty that imagines possible futures (Phase 6).

Prediction forecasts outcomes, evaluates consequences, builds isolated simulation
branches, computes uncertainty, and produces confidence-calibrated forecasts —
**without ever changing reality**. It constructs isolated, in-memory, reference-only
simulation branches (PrL8), tags everything hypothetical so it can never become
belief (PrL9), estimates risk and opportunity asymmetrically (PrL17), decays
confidence with the horizon (PrL12), and returns explainable forecasts to the
Executive (PrL20) — importing no sibling engine and writing no canonical state.
"""

from __future__ import annotations

from .contracts import (
    BranchKind,
    BranchState,
    Consequence,
    Driver,
    Forecast,
    PredictionConfig,
    PredictionHealthReport,
    PredictionMetricsSnapshot,
    PredictionRequest,
    ReasoningFeedbackPort,
    RiskForecast,
    Scenario,
    ScenarioKind,
    SimulationBranch,
    UncertaintyKind,
    WorkingMemoryReadPort,
)
from .engine import PredictionEngine
from .errors import (
    BranchNotFoundError,
    IsolationViolation,
    PredictionError,
    PredictionSecurityError,
    SimulationBudgetExceeded,
    UnknownPredictionOperationError,
)
from .ports import (
    NullReasoningFeedbackPort,
    NullWMReadPort,
    RuntimePredictionPort,
    RuntimeWMReadPort,
)

__all__ = [
    "PredictionEngine",
    # ports
    "RuntimeWMReadPort",
    "NullWMReadPort",
    "RuntimePredictionPort",
    "NullReasoningFeedbackPort",
    "WorkingMemoryReadPort",
    "ReasoningFeedbackPort",
    # value objects
    "PredictionRequest",
    "Forecast",
    "RiskForecast",
    "Scenario",
    "ScenarioKind",
    "Consequence",
    "Driver",
    "SimulationBranch",
    "BranchKind",
    "BranchState",
    "UncertaintyKind",
    "PredictionConfig",
    "PredictionMetricsSnapshot",
    "PredictionHealthReport",
    # errors
    "PredictionError",
    "IsolationViolation",
    "SimulationBudgetExceeded",
    "BranchNotFoundError",
    "PredictionSecurityError",
    "UnknownPredictionOperationError",
]
