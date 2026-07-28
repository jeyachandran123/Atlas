"""Cognitive State Manager error hierarchy (extends the kernel's ``KernelError``)."""

from __future__ import annotations

from ..errors import KernelError


class StateError(KernelError):
    """Root of Cognitive State errors."""


class ObjectNotFound(StateError):
    """No object exists for the given handle."""


class ImmutableObjectError(StateError):
    """Attempted to mutate an immutable object in place (Identity Core / Executive Decision)."""


class StateConflictError(StateError):
    """Optimistic concurrency conflict: expected version did not match current (Phase 1.5 §12.6)."""


class StateConsistencyError(StateError):
    """A transaction would violate a cognitive-state invariant (RL3 consistency)."""


class StateSecurityError(StateError):
    """The security context is not authorised for the requested state operation."""


class StateIntegrityError(StateError):
    """State integrity verification failed (digest/ledger mismatch)."""


class TransactionError(StateError):
    """The transaction is in an invalid condition (e.g. commit after abort)."""


class PlacementError(StateConsistencyError):
    """An object was placed in a Region it does not constitutionally belong to."""
