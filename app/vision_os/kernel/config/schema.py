"""The closed configuration schema (05_MODULES_PLATFORM_KERNEL M16).

**The schema is closed, and that is the point.** A vertical may supply exactly
four things: taxonomy mappings, region geometry with opaque labels, prompt pack
selection, and resource profiles. There is no schema slot for a threshold with
business meaning, a role definition, or a rule. Adding one requires a schema
change, which is a reviewed, visible act.

Closing the schema turns "don't put business logic in config" from a code-review
convention into a structural property (invariant V2).

Flow 1 declares the acquisition and kernel sections. Taxonomy and prompt-pack
sections arrive with Flows 2 and 5 respectively.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from ...core.errors import ValidationError


class DeploymentProfile(enum.Enum):
    """13_DEPLOYMENT_ARCHITECTURE §1 — the topology family."""

    EMBEDDED = "embedded"
    EDGE = "edge"
    NODE = "node"
    CLUSTER = "cluster"


class ClockMode(enum.Enum):
    SYSTEM = "system"
    VIRTUAL = "virtual"
    SCALED = "scaled"


# --- typed slices --------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PlatformSection:
    deployment_profile: DeploymentProfile = DeploymentProfile.EMBEDDED
    clock_mode: ClockMode = ClockMode.SYSTEM
    clock_scale_factor: float = 60.0
    deterministic: bool = False


@dataclass(frozen=True, slots=True)
class BufferSection:
    """Pool sizing is by *pipeline depth*, not camera count (03_MODULES M4)."""

    slots_per_camera: int = 4
    bytes_per_slot: int = 1920 * 1080 * 3
    lease_deadline_ms: int = 2_000
    history_window_ms: int = 1_500
    jitter_factor: float = 1.5

    def __post_init__(self) -> None:
        if self.slots_per_camera < 1:
            raise ValidationError("buffer.slots_per_camera must be >= 1")
        if self.bytes_per_slot < 1:
            raise ValidationError("buffer.bytes_per_slot must be >= 1")
        if self.lease_deadline_ms < 1:
            raise ValidationError("buffer.lease_deadline_ms must be >= 1")


@dataclass(frozen=True, slots=True)
class SchedulerSection:
    global_budget_fps: float = 150.0
    """Aggregate admitted frames/second across every camera on this node."""

    sustained_drop_threshold: float = 0.5
    """Effective rate below which a sustained-drop alarm fires."""

    drop_alarm_window_ms: int = 5_000
    duplicate_suppression: bool = False

    def __post_init__(self) -> None:
        if self.global_budget_fps <= 0:
            raise ValidationError("scheduler.global_budget_fps must be positive")
        if not 0.0 <= self.sustained_drop_threshold <= 1.0:
            raise ValidationError("scheduler.sustained_drop_threshold must be in [0,1]")


@dataclass(frozen=True, slots=True)
class SourceSection:
    reconnect_backoff_initial_ms: int = 500
    reconnect_backoff_max_ms: int = 30_000
    reconnect_backoff_jitter: float = 0.2
    stall_watchdog_ms: int = 10_000
    """No frames while the socket is open — the most common real-world RTSP
    failure and the one naive implementations miss entirely."""

    max_consecutive_decode_errors: int = 30
    max_connect_attempts: int = 0
    """0 = unlimited. Bounded for persistent failures like bad credentials, so
    the platform does not hammer a camera and lock the account."""

    def __post_init__(self) -> None:
        if self.reconnect_backoff_initial_ms < 1:
            raise ValidationError("source.reconnect_backoff_initial_ms must be >= 1")
        if self.reconnect_backoff_max_ms < self.reconnect_backoff_initial_ms:
            raise ValidationError("source.reconnect_backoff_max_ms must be >= initial")
        if self.stall_watchdog_ms < 1:
            raise ValidationError("source.stall_watchdog_ms must be >= 1")


@dataclass(frozen=True, slots=True)
class HealthSection:
    report_timeout_ms: int = 15_000
    """Silence is never health. A component that stops reporting is unhealthy."""

    aggregation_interval_ms: int = 1_000
    frozen_frame_threshold: int = 30
    """Identical consecutive frames before silent-failure suspicion."""

    hysteresis_samples: int = 3
    """State changes require persistence, to avoid alarm storms."""

    def __post_init__(self) -> None:
        if self.report_timeout_ms < 1:
            raise ValidationError("health.report_timeout_ms must be >= 1")
        if self.hysteresis_samples < 1:
            raise ValidationError("health.hysteresis_samples must be >= 1")


@dataclass(frozen=True, slots=True)
class MetricsSection:
    max_label_cardinality: int = 512
    histogram_window: int = 2048
    export_interval_ms: int = 10_000


@dataclass(frozen=True, slots=True)
class RuntimeSection:
    drain_timeout_ms: int = 30_000
    pipeline_restart_backoff_ms: int = 1_000
    max_pipeline_restarts: int = 5
    """After this, the camera is marked failed and the platform keeps running."""

    attach_stagger_ms: int = 50
    """One hundred cameras connecting at once is a self-inflicted thundering
    herd that can cause boot itself to fail (08_RUNTIME §7.1)."""

    max_pipelines: int = 512


# --- declarations --------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RegionDeclaration:
    region_id: str
    label: str
    """Opaque. Never interpreted by the platform."""

    vertices: tuple[tuple[float, float], ...]
    frame_of_reference: str = "normalized"
    camera_id: str | None = None
    version: str = "1.0.0"


@dataclass(frozen=True, slots=True)
class ProfileDeclaration:
    profile_id: str
    target_fps: float
    max_in_flight: int = 4
    priority_class: str = "default"
    inference_width: int = 640
    inference_height: int = 640


@dataclass(frozen=True, slots=True)
class CalibrationDeclaration:
    calibration_id: str
    homography: tuple[tuple[float, float, float], ...] | None = None
    ground_uncertainty_at_unit_distance: float = 0.05


@dataclass(frozen=True, slots=True)
class CameraDeclaration:
    camera_id: str
    tenant_id: str
    site_id: str
    uri: str
    transport: str
    source_semantics: str
    profile_id: str
    width: int = 1920
    height: int = 1080
    fps: float = 25.0
    codec: str = "raw"
    colour_space: str = "bgr24"
    credential_ref: str | None = None
    privacy_policy_id: str | None = None
    region_ids: tuple[str, ...] = ()
    calibration: CalibrationDeclaration | None = None
    labels: dict[str, str] = field(default_factory=dict)
    source_options: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class EffectiveConfig:
    """The fully resolved, validated configuration tree."""

    platform: PlatformSection
    buffer: BufferSection
    scheduler: SchedulerSection
    source: SourceSection
    health: HealthSection
    metrics: MetricsSection
    runtime: RuntimeSection
    profiles: tuple[ProfileDeclaration, ...] = ()
    regions: tuple[RegionDeclaration, ...] = ()
    cameras: tuple[CameraDeclaration, ...] = ()


# --- the closed key set --------------------------------------------------- #

SECTION_TYPES: dict[str, type] = {
    "platform": PlatformSection,
    "buffer": BufferSection,
    "scheduler": SchedulerSection,
    "source": SourceSection,
    "health": HealthSection,
    "metrics": MetricsSection,
    "runtime": RuntimeSection,
}

LIST_SECTIONS: frozenset[str] = frozenset({"profiles", "regions", "cameras"})

ALLOWED_TOP_LEVEL: frozenset[str] = frozenset(SECTION_TYPES) | LIST_SECTIONS

_ENUM_FIELDS: dict[tuple[str, str], type[enum.Enum]] = {
    ("platform", "deployment_profile"): DeploymentProfile,
    ("platform", "clock_mode"): ClockMode,
}


def allowed_keys(section: str) -> frozenset[str]:
    """The closed key set for a scalar section."""
    section_type = SECTION_TYPES.get(section)
    if section_type is None:
        return frozenset()
    return frozenset(section_type.__dataclass_fields__)


def validate(document: dict[str, Any]) -> tuple[str, ...]:
    """Validate a merged document against the closed schema.

    Returns a tuple of violation messages; empty means valid. Unknown keys are
    violations, not warnings — that is what makes the schema closed.
    """
    violations: list[str] = []

    for key in document:
        if key not in ALLOWED_TOP_LEVEL:
            violations.append(
                f"unknown configuration section '{key}'. The schema is closed "
                f"(V2); allowed sections: {sorted(ALLOWED_TOP_LEVEL)}"
            )

    for section in SECTION_TYPES:
        raw = document.get(section)
        if raw is None:
            continue
        if not isinstance(raw, dict):
            violations.append(f"section '{section}' must be a mapping, got {type(raw).__name__}")
            continue
        permitted = allowed_keys(section)
        for key in raw:
            if key not in permitted:
                violations.append(
                    f"unknown key '{section}.{key}'. The schema is closed (V2); "
                    f"allowed keys: {sorted(permitted)}"
                )
        for key, value in raw.items():
            enum_type = _ENUM_FIELDS.get((section, key))
            if enum_type is not None and not _valid_enum(enum_type, value):
                allowed = sorted(m.value for m in enum_type)
                violations.append(f"'{section}.{key}' must be one of {allowed}, got {value!r}")

    for section in LIST_SECTIONS:
        raw = document.get(section)
        if raw is None:
            continue
        if not isinstance(raw, list):
            violations.append(f"section '{section}' must be a list, got {type(raw).__name__}")

    violations.extend(_validate_cameras(document))
    return tuple(violations)


def _valid_enum(enum_type: type[enum.Enum], value: Any) -> bool:
    if isinstance(value, enum_type):
        return True
    return any(member.value == value for member in enum_type)


def _validate_cameras(document: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    cameras = document.get("cameras")
    if not isinstance(cameras, list):
        return violations

    profiles = document.get("profiles")
    profile_ids = {
        p.get("profile_id") for p in profiles if isinstance(p, dict)
    } if isinstance(profiles, list) else set()

    regions = document.get("regions")
    region_ids = {
        r.get("region_id") for r in regions if isinstance(r, dict)
    } if isinstance(regions, list) else set()

    seen: set[str] = set()
    for index, camera in enumerate(cameras):
        if not isinstance(camera, dict):
            violations.append(f"cameras[{index}] must be a mapping")
            continue
        camera_id = camera.get("camera_id")
        if not camera_id:
            violations.append(f"cameras[{index}].camera_id is required")
            continue
        if camera_id in seen:
            violations.append(f"duplicate camera_id '{camera_id}'")
        seen.add(camera_id)

        for required in ("tenant_id", "site_id", "uri", "transport", "profile_id"):
            if not camera.get(required):
                violations.append(f"cameras['{camera_id}'].{required} is required")

        semantics = camera.get("source_semantics")
        if semantics not in ("realtime", "archival", "discrete"):
            violations.append(
                f"cameras['{camera_id}'].source_semantics must be one of "
                f"['archival', 'discrete', 'realtime'], got {semantics!r}"
            )

        profile_id = camera.get("profile_id")
        if profile_id and profile_ids and profile_id not in profile_ids:
            violations.append(
                f"cameras['{camera_id}'].profile_id '{profile_id}' is not declared. "
                f"Provisioning fails fast at startup, not at first frame."
            )

        for region_id in camera.get("region_ids", ()) or ():
            if region_ids and region_id not in region_ids:
                violations.append(
                    f"cameras['{camera_id}'] references undeclared region '{region_id}'"
                )

    return violations
