"""Working Memory engine errors (extend the kernel's ``KernelError``)."""

from __future__ import annotations

from ...errors import KernelError


class WorkingMemoryError(KernelError):
    """Root of Working Memory errors."""


class UnknownWorkspaceError(WorkingMemoryError):
    """Referenced a workspace that does not exist."""


class MissingTargetError(WorkingMemoryError):
    """Attempted to activate a reference to a non-existent cognitive object."""


class CapacityViolation(WorkingMemoryError):
    """A capacity invariant would be violated (should never escape — WM evicts)."""


class WorkingMemorySecurityError(WorkingMemoryError):
    """The context is not authorised for a gated Working Memory operation."""


class UnknownOperationError(WorkingMemoryError):
    """The runtime dispatched an unknown Working Memory operation."""
