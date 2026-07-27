"""Kernel error hierarchy.

All kernel-level failures derive from :class:`KernelError`. Errors are part of
the stable kernel ABI: engines and tooling may catch these types without
depending on kernel internals.
"""

from __future__ import annotations


class KernelError(Exception):
    """Root of every Cognitive Kernel error."""


class LifecycleError(KernelError):
    """An illegal kernel/engine lifecycle transition was attempted."""


class BootstrapError(KernelError):
    """The boot sequence failed; partial initialization must be rolled back."""


class ConstitutionViolation(KernelError):
    """An operation would violate a frozen constitutional law."""


class LedgerIntegrityError(KernelError):
    """The append-only ledger failed an integrity (hash-chain) check."""


class EngineRegistrationError(KernelError):
    """An engine could not be registered (duplicate, bad metadata, cycle)."""


class DependencyResolutionError(KernelError):
    """A required abstraction was not registered in the container."""


class CheckpointError(KernelError):
    """A checkpoint could not be saved, loaded, or verified."""


class RecoveryError(KernelError):
    """Recovery could not restore a constitutionally consistent state."""


class ContextError(KernelError):
    """A cognitive operation was attempted without a valid execution context."""
