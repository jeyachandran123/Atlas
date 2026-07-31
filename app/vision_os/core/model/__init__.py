"""The Vision Object Model — Flow 1 subset (02_VISION_OBJECT_MODEL).

The ontology is **closed**: eleven object kinds, fixed. New capability adds
instances and attributes, never new kinds.

Flow 1 implements the kinds acquisition needs:

    Camera · Frame · Region  (+ the identity, time and space models)

Deliberately **not** implemented, because they belong to later flows and
implementing them early would be speculative:

    Detection (Flow 2) · Track (Flow 3) · Crop (Flow 4) ·
    Attribute (Flow 5) · VisualObject (Flow 3/7) ·
    Observation, Evidence (Flow 6) · VisionState (Flow 7)
"""

from __future__ import annotations

from .camera import (
    Camera,
    CameraStatus,
    NativeProfile,
    PipelineProfile,
    SourceSemantics,
    SourceSpec,
)
from .frame import (
    DecodeQuality,
    Frame,
    FrameDimensions,
    FrameQuality,
    PixelBuffer,
    PrivacyState,
    SourceMeta,
)
from .health import (
    ComponentHealth,
    CoverageGap,
    HealthState,
    ObservabilityReason,
    ObservabilityState,
)
from .ids import (
    AdapterId,
    CalibrationId,
    CameraId,
    ConfigRevision,
    FrameRef,
    FrameSeq,
    ModuleId,
    PluginId,
    PortId,
    PrivacyPolicyId,
    ProfileId,
    RegionId,
    SiteId,
    StreamEpoch,
    TenantId,
    new_ulid,
    ulid_timestamp_ms,
)
from .region import ContainmentMethod, MembershipState, Region
from .space import (
    Box,
    Calibration,
    Ellipse,
    FrameOfReference,
    Homography,
    Point,
    Polygon,
    SpatialInfo,
)
from .timebase import ZERO_DURATION, ClockQuality, Duration, FrameTime, Instant

__all__ = [
    "ZERO_DURATION",
    "AdapterId",
    "Box",
    "Calibration",
    "CalibrationId",
    "Camera",
    "CameraId",
    "CameraStatus",
    "ClockQuality",
    "ComponentHealth",
    "ConfigRevision",
    "ContainmentMethod",
    "CoverageGap",
    "DecodeQuality",
    "Duration",
    "Ellipse",
    "Frame",
    "FrameDimensions",
    "FrameOfReference",
    "FrameQuality",
    "FrameRef",
    "FrameSeq",
    "FrameTime",
    "HealthState",
    "Homography",
    "Instant",
    "MembershipState",
    "ModuleId",
    "NativeProfile",
    "ObservabilityReason",
    "ObservabilityState",
    "PipelineProfile",
    "PixelBuffer",
    "PluginId",
    "Point",
    "Polygon",
    "PortId",
    "PrivacyPolicyId",
    "PrivacyState",
    "ProfileId",
    "Region",
    "RegionId",
    "SiteId",
    "SourceMeta",
    "SourceSemantics",
    "SourceSpec",
    "SpatialInfo",
    "StreamEpoch",
    "TenantId",
    "new_ulid",
    "ulid_timestamp_ms",
]
