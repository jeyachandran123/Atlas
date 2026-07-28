"""Executive engine errors (extend the kernel's ``KernelError``)."""

from __future__ import annotations

from ...errors import KernelError


class ExecutiveError(KernelError):
    """Root of Executive errors."""


class ExecutiveSecurityError(ExecutiveError):
    """The context lacks the authority for a gated executive act (ExL1)."""


class ConstitutionalViolation(ExecutiveError):
    """A governance move would violate an absolute safety/identity constraint (ExL7/ExL12)."""


class GoalNotFoundError(ExecutiveError):
    """A governance operation referenced an unknown goal."""


class OwnershipError(ExecutiveError):
    """A goal was admitted without a single accountable owner (ExL2)."""


class BudgetExceededError(ExecutiveError):
    """An allocation would exceed the finite total cognitive resource (ExL4)."""


class UnknownExecutiveOperationError(ExecutiveError):
    """The runtime dispatched an unknown executive operation."""
