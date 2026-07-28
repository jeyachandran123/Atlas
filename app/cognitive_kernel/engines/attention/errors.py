"""Attention engine errors (extend the kernel's ``KernelError``)."""

from __future__ import annotations

from ...errors import KernelError


class AttentionError(KernelError):
    """Root of Attention errors."""


class InvalidCandidateError(AttentionError):
    """A candidate referenced a non-existent cognitive object."""


class AttentionSecurityError(AttentionError):
    """The context is not authorised for a gated Attention operation."""


class UnknownAttentionOperationError(AttentionError):
    """The runtime dispatched an unknown Attention operation."""
