"""Vision OS error taxonomy (10_RELIABILITY_AND_FAILURE §2).

Every failure in the platform carries a **classification**, because the
classification — not the call site — determines the response. An unclassified
failure gets a guessed response, and guessed responses are how retry storms and
crash loops begin.

Adapters raise ``VisionOSError`` subclasses, or — where failure is an *expected*
outcome rather than an exceptional one — return a typed verdict carrying an
attributed reason (``AdmissionVerdict``, ``MaskOutcome``). They never raise bare
exceptions across a port boundary, and they never fabricate a plausible value on
failure (invariant V4, port obligation A4).
"""

from __future__ import annotations

import enum
from typing import Any


class FailureClass(enum.Enum):
    """10_RELIABILITY_AND_FAILURE §2 — the six failure classes."""

    TRANSIENT = "transient"
    """Self-resolving; a bounded retry is likely to succeed."""

    PERSISTENT = "persistent"
    """Will not self-resolve; retry is futile. Stop, fall back, alarm."""

    POISON = "poison"
    """A specific input reliably fails. Quarantine the input, keep the stream."""

    SYSTEMIC = "systemic"
    """A shared resource is affected; retry makes it worse. Shed load."""

    SILENT = "silent"
    """No error raised, but output is wrong or absent. Requires active detection."""

    BYZANTINE = "byzantine"
    """Confident, plausible, wrong output. Requires cross-checks and evidence."""


class VisionOSError(Exception):
    """Base class for every Vision OS failure.

    Carries a failure classification and structured context so that recovery
    logic never has to parse a message string.
    """

    failure_class: FailureClass = FailureClass.PERSISTENT

    def __init__(self, message: str, /, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = dict(context)

    @property
    def retryable(self) -> bool:
        """Explicit, never inferred by the caller (09_API_CONTRACTS §8)."""
        return self.failure_class is FailureClass.TRANSIENT

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"{type(self).__name__}({self.message!r}, class={self.failure_class.value})"


# --- configuration ------------------------------------------------------- #


class ConfigurationError(VisionOSError):
    """Configuration is invalid, missing, or internally inconsistent."""


class ValidationError(ConfigurationError):
    """A candidate configuration failed schema validation."""

    def __init__(self, message: str, /, violations: tuple[str, ...] = (), **context: Any) -> None:
        super().__init__(message, **context)
        self.violations = violations


class SecretResolutionError(ConfigurationError):
    """A secret reference could not be resolved. Never contains the secret."""


# --- plugins and ports --------------------------------------------------- #


class PluginError(VisionOSError):
    """A plugin could not be discovered, validated, loaded, or activated."""


class ManifestInvalidError(PluginError):
    """A plugin manifest is malformed or incomplete."""


class PortIncompatibleError(PluginError):
    """A plugin declares a port version outside the platform's supported range."""


class ConformanceFailedError(PluginError):
    """A plugin failed its port conformance kit and must not be activated (V3)."""

    def __init__(self, message: str, /, failures: tuple[str, ...] = (), **context: Any) -> None:
        super().__init__(message, **context)
        self.failures = failures


class SignatureInvalidError(PluginError):
    """Plugin signature verification failed. Fails closed (12_SECURITY §6)."""


# --- acquisition --------------------------------------------------------- #


class AcquisitionError(VisionOSError):
    """Base for the L1 acquisition layer."""


class ConnectFailedError(AcquisitionError):
    """A source could not be opened."""

    failure_class = FailureClass.TRANSIENT


class StreamLostError(AcquisitionError):
    """An open source stopped delivering frames."""

    failure_class = FailureClass.TRANSIENT


class DecodeError(AcquisitionError):
    """A frame could not be decoded."""

    failure_class = FailureClass.TRANSIENT


class UnsupportedCodecError(AcquisitionError):
    """No decoder can handle this stream. Fail provisioning loudly."""


class PrivacyMaskError(AcquisitionError):
    """Privacy masking failed.

    The **only** fail-closed path in the platform (12_SECURITY §2.1): the frame
    is dropped rather than emitted unmasked. A masking failure that proceeds is a
    compliance incident regardless of intent.
    """

    failure_class = FailureClass.SYSTEMIC


class NotSeekableError(AcquisitionError):
    """Seek requested on a source that does not support it."""


# --- buffering ----------------------------------------------------------- #


class BufferError(VisionOSError):
    """Base for frame buffer failures."""


class PoolExhaustedError(BufferError):
    """No buffer capacity is available."""

    failure_class = FailureClass.SYSTEMIC


class FrameUnavailableError(BufferError):
    """The requested frame is no longer resident (evicted or never published).

    A normal, expected outcome — not a bug. Callers degrade and count.
    """

    failure_class = FailureClass.TRANSIENT


class LeaseExpiredError(BufferError):
    """A lease was force-broken after exceeding its deadline."""


# --- registry / lookup --------------------------------------------------- #


class NotFoundError(VisionOSError):
    """A referenced entity does not exist."""


class UncalibratedError(VisionOSError):
    """An operation requiring calibration was attempted without one.

    Callers degrade to normalized image space rather than failing (V9).
    """


class CapacityExceededError(VisionOSError):
    """The runtime cannot accept more work of this kind."""

    failure_class = FailureClass.SYSTEMIC


class LifecycleError(VisionOSError):
    """An operation was attempted in an invalid lifecycle state."""
