"""Typed platform events — Flow 1 set (05_MODULES_PLATFORM_KERNEL M19).

Events are how information travels *upward* without an upward dependency
(01_LAYERED §2). The bus itself is untyped infrastructure; the vocabulary lives
here so that event types are registered rather than stringly-invented at call
sites.

Payloads are small, bounded, and contain no pixels. Anything large becomes a
reference to storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from ...core.model.ids import CameraId, ConfigRevision, ModuleId, PluginId, StreamEpoch
from ...core.model.timebase import Instant


@dataclass(frozen=True, slots=True)
class Event:
    """Base event. ``partition_key`` preserves per-key ordering where declared."""

    event_type: ClassVar[str] = "event"

    occurred_at: Instant
    partition_key: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        """Flat, transport-ready representation."""
        return {
            "event_type": type(self).event_type,
            "occurred_at_ns": self.occurred_at.ns,
            "partition_key": self.partition_key,
            **self.detail,
        }


# --- stream lifecycle (M2) ----------------------------------------------- #


@dataclass(frozen=True, slots=True)
class StreamConnected(Event):
    event_type: ClassVar[str] = "stream.connected"
    camera_id: CameraId = CameraId("")
    stream_epoch: StreamEpoch = StreamEpoch(0)


@dataclass(frozen=True, slots=True)
class StreamLost(Event):
    event_type: ClassVar[str] = "stream.lost"
    camera_id: CameraId = CameraId("")
    stream_epoch: StreamEpoch = StreamEpoch(0)
    reason: str = ""


@dataclass(frozen=True, slots=True)
class EpochAdvanced(Event):
    """A reconnect or reconfigure minted a new stream epoch (02_VOM §4.1)."""

    event_type: ClassVar[str] = "stream.epoch_advanced"
    camera_id: CameraId = CameraId("")
    stream_epoch: StreamEpoch = StreamEpoch(0)


@dataclass(frozen=True, slots=True)
class DecodeFailed(Event):
    event_type: ClassVar[str] = "stream.decode_failed"
    camera_id: CameraId = CameraId("")
    reason: str = ""


@dataclass(frozen=True, slots=True)
class MaskFailure(Event):
    """Privacy masking failed; the frame was dropped. Fails closed."""

    event_type: ClassVar[str] = "privacy.mask_failed"
    camera_id: CameraId = CameraId("")
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ClockQualityChanged(Event):
    event_type: ClassVar[str] = "stream.clock_quality_changed"
    camera_id: CameraId = CameraId("")
    quality: str = ""


# --- scheduling (M3) ------------------------------------------------------ #


@dataclass(frozen=True, slots=True)
class SustainedDropAlarm(Event):
    """The scheduler is shedding beyond tolerance; perception is thinned (V8)."""

    event_type: ClassVar[str] = "scheduler.sustained_drop"
    camera_id: CameraId = CameraId("")
    reason: str = ""
    effective_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class BudgetExceeded(Event):
    event_type: ClassVar[str] = "scheduler.budget_exceeded"
    pressure: float = 0.0


# --- buffering (M4) ------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PoolPressure(Event):
    event_type: ClassVar[str] = "buffer.pool_pressure"
    location: str = "host"
    in_use: int = 0
    total: int = 0


@dataclass(frozen=True, slots=True)
class LeaseLeaked(Event):
    """A holder exceeded its lease deadline and was force-broken.

    One stuck stage must not exhaust the pool for every camera (V9).
    """

    event_type: ClassVar[str] = "buffer.lease_leaked"
    holder_id: str = ""
    frame_ref: str = ""


@dataclass(frozen=True, slots=True)
class FrameEvicted(Event):
    event_type: ClassVar[str] = "buffer.frame_evicted"
    camera_id: CameraId = CameraId("")
    frame_ref: str = ""


# --- camera registry (M1) ------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CameraChanged(Event):
    event_type: ClassVar[str] = "camera.changed"
    camera_id: CameraId = CameraId("")
    change: str = ""


@dataclass(frozen=True, slots=True)
class ViewpointDriftSuspected(Event):
    """The camera may have moved; calibration no longer describes the view.

    Publishes a suspicion, never an automatic invalidation — a false positive
    must not blind a working site (03_MODULES M1).
    """

    event_type: ClassVar[str] = "camera.viewpoint_drift_suspected"
    camera_id: CameraId = CameraId("")
    evidence: str = ""


# --- configuration (M16) -------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ConfigChanged(Event):
    event_type: ClassVar[str] = "config.changed"
    revision: ConfigRevision = ConfigRevision("")
    requires_restart: tuple[str, ...] = ()


# --- plugins (M17) -------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PluginLoaded(Event):
    event_type: ClassVar[str] = "plugin.loaded"
    plugin_id: PluginId = PluginId("")
    port_id: str = ""


@dataclass(frozen=True, slots=True)
class PluginRejected(Event):
    event_type: ClassVar[str] = "plugin.rejected"
    plugin_id: PluginId = PluginId("")
    reason: str = ""


# --- health (M20) --------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class HealthChanged(Event):
    event_type: ClassVar[str] = "health.changed"
    component_id: ModuleId = ModuleId("")
    state: str = ""


@dataclass(frozen=True, slots=True)
class CoverageChanged(Event):
    """Observability changed. Consumers must distinguish this from silence (V8)."""

    event_type: ClassVar[str] = "health.coverage_changed"
    camera_id: CameraId = CameraId("")
    status: str = ""
    reason: str = ""
    effective_rate: float = 1.0


@dataclass(frozen=True, slots=True)
class SilentFailureSuspected(Event):
    """A suspicion, not a verdict (10_RELIABILITY §5.2).

    Degrades coverage confidence and alerts an operator; it never blinds a camera
    automatically, because a false positive that blinds a working camera is
    itself an outage.
    """

    event_type: ClassVar[str] = "health.silent_failure_suspected"
    camera_id: CameraId = CameraId("")
    detector: str = ""
    evidence: str = ""


# --- runtime (M15) -------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PipelineAttached(Event):
    event_type: ClassVar[str] = "runtime.pipeline_attached"
    camera_id: CameraId = CameraId("")


@dataclass(frozen=True, slots=True)
class PipelineDetached(Event):
    event_type: ClassVar[str] = "runtime.pipeline_detached"
    camera_id: CameraId = CameraId("")
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Gap(Event):
    """An explicit delivery gap. Never silence (V8, 09_API §3.3)."""

    event_type: ClassVar[str] = "bus.gap"
    subscription_id: str = ""
    dropped: int = 0
    reason: str = ""


ALL_EVENT_TYPES: tuple[type[Event], ...] = (
    StreamConnected,
    StreamLost,
    EpochAdvanced,
    DecodeFailed,
    MaskFailure,
    ClockQualityChanged,
    SustainedDropAlarm,
    BudgetExceeded,
    PoolPressure,
    LeaseLeaked,
    FrameEvicted,
    CameraChanged,
    ViewpointDriftSuspected,
    ConfigChanged,
    PluginLoaded,
    PluginRejected,
    HealthChanged,
    CoverageChanged,
    SilentFailureSuspected,
    PipelineAttached,
    PipelineDetached,
    Gap,
)
