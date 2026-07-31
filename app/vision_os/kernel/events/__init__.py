"""M19 Event Bus — decoupled control-plane notification.

Enables upward communication without upward dependencies (01_LAYERED §2).
"""

from __future__ import annotations

from .bus import BusStats, DeliveryPolicy, EventBus, OverflowPolicy, Subscription
from .events import (
    ALL_EVENT_TYPES,
    BudgetExceeded,
    CameraChanged,
    ClockQualityChanged,
    ConfigChanged,
    CoverageChanged,
    DecodeFailed,
    EpochAdvanced,
    Event,
    FrameEvicted,
    Gap,
    HealthChanged,
    LeaseLeaked,
    MaskFailure,
    PipelineAttached,
    PipelineDetached,
    PluginLoaded,
    PluginRejected,
    PoolPressure,
    SilentFailureSuspected,
    StreamConnected,
    StreamLost,
    SustainedDropAlarm,
    ViewpointDriftSuspected,
)

__all__ = [
    "ALL_EVENT_TYPES",
    "BudgetExceeded",
    "BusStats",
    "CameraChanged",
    "ClockQualityChanged",
    "ConfigChanged",
    "CoverageChanged",
    "DecodeFailed",
    "DeliveryPolicy",
    "EpochAdvanced",
    "Event",
    "EventBus",
    "FrameEvicted",
    "Gap",
    "HealthChanged",
    "LeaseLeaked",
    "MaskFailure",
    "OverflowPolicy",
    "PipelineAttached",
    "PipelineDetached",
    "PluginLoaded",
    "PluginRejected",
    "PoolPressure",
    "SilentFailureSuspected",
    "StreamConnected",
    "StreamLost",
    "Subscription",
    "SustainedDropAlarm",
    "ViewpointDriftSuspected",
]
