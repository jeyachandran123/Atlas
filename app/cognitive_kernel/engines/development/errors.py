"""Development engine errors (extend the kernel's ``KernelError``)."""

from __future__ import annotations

from ...errors import KernelError


class DevelopmentError(KernelError):
    """Root of Development errors."""


class DevelopmentSecurityError(DevelopmentError):
    """The context lacks authority for a gated development operation."""


class ConstitutionalEvolutionError(DevelopmentError):
    """A proposal would touch the constitution or identity Core — forbidden (DeL1/DeL16)."""


class ProposalNotFoundError(DevelopmentError):
    """A lookup referenced an unknown evolution proposal or artifact."""


class UnknownDevelopmentOperationError(DevelopmentError):
    """The runtime dispatched an unknown development operation."""
