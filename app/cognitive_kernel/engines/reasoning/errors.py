"""Reasoning engine errors (extend the kernel's ``KernelError``)."""

from __future__ import annotations

from ...errors import KernelError


class ReasoningError(KernelError):
    """Root of Reasoning errors."""


class InvalidPremiseError(ReasoningError):
    """A premise referenced a non-existent or non-conscious cognitive object."""


class ReasoningSecurityError(ReasoningError):
    """The context is not authorised for a gated Reasoning operation."""


class UnknownReasoningOperationError(ReasoningError):
    """The runtime dispatched an unknown Reasoning operation."""


class EngineUnavailableError(ReasoningError):
    """No substitutable reasoning engine could serve a reasoning step (ReL14)."""


class EpisodeNotFoundError(ReasoningError):
    """A resume/reconstruct referenced an unknown reasoning episode."""
