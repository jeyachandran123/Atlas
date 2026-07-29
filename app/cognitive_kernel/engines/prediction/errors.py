"""Prediction engine errors (extend the kernel's ``KernelError``)."""

from __future__ import annotations

from ...errors import KernelError


class PredictionError(KernelError):
    """Root of Prediction errors."""


class IsolationViolation(PredictionError):
    """A simulation attempted to touch canonical Cognitive State (PrL8)."""


class SimulationBudgetExceeded(PredictionError):
    """Too many open branches / samples — the anytime bound is exceeded (PrL13)."""


class BranchNotFoundError(PredictionError):
    """A lifecycle operation referenced an unknown simulation branch."""


class PredictionSecurityError(PredictionError):
    """The context lacks authority for a gated prediction operation."""


class UnknownPredictionOperationError(PredictionError):
    """The runtime dispatched an unknown prediction operation."""
