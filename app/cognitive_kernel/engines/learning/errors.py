"""Learning engine errors (extend the kernel's ``KernelError``)."""

from __future__ import annotations

from ...errors import KernelError


class LearningError(KernelError):
    """Root of Learning errors."""


class InsufficientEvidenceError(LearningError):
    """A candidate lacked the multi-episode evidence to be learned (LeL7/LeL8)."""


class ConsistencyViolationError(LearningError):
    """A revision would break belief-graph consistency (LeL23)."""


class UnauthorizedLearningError(LearningError):
    """An above-automatic-tier change lacked Executive/human authorization (LeL3)."""


class LearningSecurityError(LearningError):
    """The context lacks authority for a gated learning operation."""


class RollbackError(LearningError):
    """A rollback of a committed revision failed."""


class UnknownLearningOperationError(LearningError):
    """The runtime dispatched an unknown learning operation."""
