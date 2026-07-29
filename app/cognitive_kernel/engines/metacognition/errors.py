"""Meta-Cognition engine errors (extend the kernel's ``KernelError``)."""

from __future__ import annotations

from ...errors import KernelError


class MetaError(KernelError):
    """Root of Meta-Cognition errors."""


class MetaSecurityError(MetaError):
    """The context lacks authority for a gated meta operation (MeL34)."""


class ReflectionNotFoundError(MetaError):
    """A lookup referenced an unknown reflection artifact."""


class UnknownMetaOperationError(MetaError):
    """The runtime dispatched an unknown meta operation."""
