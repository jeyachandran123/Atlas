"""The Detection object (02_VISION_OBJECT_MODEL section 10.4).

An assertion that a taxonomy class occupies a location in **one frame**. It is
immutable, memoryless, and carries no identity beyond its own: detection never
remembers a previous frame and never claims that this thing is that thing. Those
are the Tracking Engine's job (Flow 3).

Everything a future Observation Builder needs to explain this result — the exact
weights, the exact configuration, the timing, the decisions taken — travels with
it (invariant V4).
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field

from .confidence import Confidence, ConfidenceSemantics
from .ids import ClassId, DetectionId, FrameRef, SiteId, TenantId
from .provenance import InferenceTiming, Provenance
from .space import SpatialInfo
from .taxonomy import GeometryKind
from .timebase import Duration, Instant

DETECTION_SCHEMA_VERSION = "1.0.0"


class ExposureLevel(enum.Enum):
    UNDER = "under"
    OK = "ok"
    OVER = "over"


@dataclass(frozen=True, slots=True)
class QualityGrades:
    """Input quality, insofar as it is derivable at this stage (02_VOM section 10.8).

    Detection populates ``scale`` and ``truncation`` (port obligation D8). The
    remaining grades — occlusion, blur, crowding — require either neighbour
    context or a crop, and belong to Flow 4. They are ``None`` here rather than
    zero, because "not measured" and "measured as zero" are different claims.
    """

    scale_pixels: float | None = None
    """Object height in source pixels — the strongest single predictor of how
    reliable anything inferred from this region will be."""

    truncation: float | None = None
    """Fraction of the object outside the frame, in [0,1]."""

    occlusion: float | None = None
    blur: float | None = None
    crowding: float | None = None
    exposure: ExposureLevel | None = None

    def __post_init__(self) -> None:
        for name in ("truncation", "occlusion", "blur"):
            value = getattr(self, name)
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0,1], got {value}")
        if self.scale_pixels is not None and self.scale_pixels < 0:
            raise ValueError(f"scale_pixels must be non-negative, got {self.scale_pixels}")


class DecisionStep(enum.Enum):
    """A step taken while producing a detection.

    Records *why the result looks the way it does* — a threshold applied, a
    coordinate clamped, a calibration used. Six months later this is the
    difference between explaining a result and guessing at it (invariant V4).
    """

    THRESHOLD_APPLIED = "threshold_applied"
    NMS_APPLIED_BY_ADAPTER = "nms_applied_by_adapter"
    NMS_APPLIED_BY_PLATFORM = "nms_applied_by_platform"
    CALIBRATION_APPLIED = "calibration_applied"
    CALIBRATION_UNAVAILABLE = "calibration_unavailable"
    COORDINATES_CLAMPED = "coordinates_clamped"
    TAXONOMY_MAPPED = "taxonomy_mapped"
    MAX_DETECTIONS_TRUNCATED = "max_detections_truncated"
    FALLBACK_MODEL_USED = "fallback_model_used"
    DEGRADED_FIDELITY = "degraded_fidelity"


@dataclass(frozen=True, slots=True)
class DetectionEvidence:
    """The evidence *inputs* for this detection.

    Deliberately not the ``Evidence`` object of 02_VOM section 10.9 — that is
    bound to an ``observation_id`` and assembled by the Observation Builder in
    Flow 6. Flow 2 produces the raw material and nothing more.
    """

    input_hash: str
    """Hash of the exact pixels the model saw, after any letterboxing."""

    decision_path: tuple[DecisionStep, ...] = ()
    raw_output_ref: str | None = None
    """Reference to retained verbatim model output, when policy retains it."""

    notes: str = ""


@dataclass(frozen=True, slots=True)
class Detection:
    """One frame-scoped assertion that something is present, and where.

    Carries no ``track_id`` and no ``object_id``: a detection has no memory and
    no persistent identity by construction, which is what keeps the Detection
    Engine trivially testable and freely replaceable.
    """

    detection_id: DetectionId
    frame_ref: FrameRef
    tenant_id: TenantId
    site_id: SiteId

    t_capture: Instant
    t_capture_uncertainty: Duration

    class_id: ClassId
    taxonomy_version: str
    confidence: Confidence
    spatial: SpatialInfo

    provenance: Provenance
    timing: InferenceTiming
    evidence: DetectionEvidence

    quality: QualityGrades = QualityGrades()
    class_scores: tuple[tuple[ClassId, float], ...] = ()
    """The full distribution when the adapter provides it. Retained rather than
    discarded so the Object Registry can later resolve class flapping using the
    distribution instead of a majority vote over information already thrown
    away (02_VOM section 10.4)."""

    geometry_kind: GeometryKind = GeometryKind.BOX
    schema_version: str = DETECTION_SCHEMA_VERSION
    labels: Mapping[str, str] = field(default_factory=dict)
    """Opaque operational tags. No platform logic may branch on these."""

    def __post_init__(self) -> None:
        if self.confidence.semantics is not ConfidenceSemantics.DETECTION_PRESENCE:
            raise ValueError(
                f"a Detection must carry DETECTION_PRESENCE confidence, got "
                f"{self.confidence.semantics.value} (port obligation D3)"
            )
        if self.spatial.bbox is None:
            raise ValueError("a Detection must carry a bounding box")
        if not self.spatial.bbox.is_within_unit():
            raise ValueError(
                f"detection box {self.spatial.bbox} escapes normalized [0,1] space; "
                f"adapters must invert letterboxing exactly (port obligation D1)"
            )
        if not self.taxonomy_version:
            raise ValueError("a Detection must name the taxonomy version it used")

    @property
    def detector_name(self) -> str | None:
        return self.provenance.detector_name

    @property
    def detector_version(self) -> str | None:
        return self.provenance.detector_version

    @property
    def inference_ms(self) -> float:
        return self.timing.inference_ms

    @property
    def coordinate_space(self) -> str:
        return self.spatial.frame_of_reference.value

    def is_a(self, ancestor: ClassId) -> bool:
        """Hierarchical class match without consulting the registry."""
        return self.class_id == ancestor or self.class_id.startswith(f"{ancestor}.")
