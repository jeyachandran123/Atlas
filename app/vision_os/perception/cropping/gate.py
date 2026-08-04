"""The quality gate — refuse to spend an expensive call on an unanswerable input.

> §M8 responsibility 3: *"Reject crops that cannot support a defensible claim,
> with a recorded reason."*

The gate is where V7 (perceptual economy) and V4 (explainability) meet. It saves
money by not asking a VLM about a 9-pixel-tall blur, and it stays honest by
recording *which* axis failed — so "the VLM never answers for far-away people"
becomes a statistic with a name rather than a mystery (02_VOM section 10.7).

**The gate does not grade.** Grading is P13's job; the gate maps grades onto a
verdict. Keeping them apart means a deployment can swap in a learned quality
predictor without touching the thresholds that decide what is affordable, and a
threshold change never silently alters what "blur" means.

**Order matters.** Checks run cheapest-and-most-certain first, so a rejected crop
names the axis a human would name: a 9-pixel object is `TOO_SMALL`, not
`TOO_BLURRY`, even though it is also unavoidably blurry.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...core.model.crop import GateRejection, GateResult
from ...core.model.detection import ExposureLevel, QualityGrades, QualityLevel


@dataclass(frozen=True, slots=True)
class GateThresholds:
    """What the gate considers unusable.

    Every value is configuration. The architecture fixes *which* axes exist
    (02_VOM section 10.8) and that a rejection must be attributable; it does not
    fix where the lines fall, because that depends on the model downstream and
    the camera upstream.
    """

    min_scale_pixels: float = 48.0
    max_truncation: float = 0.5
    max_occlusion: float = 0.7
    max_blur: float = 0.85
    max_crowding: float = 0.9
    reject_extreme_exposure: bool = False
    """Off by default. Under- and over-exposure degrade a claim but rarely make
    it impossible, and rejecting on exposure blinds a site at dawn and dusk —
    V9: degrade, never die."""

    def __post_init__(self) -> None:
        if self.min_scale_pixels < 0:
            raise ValueError("min_scale_pixels must be non-negative")
        for name in ("max_truncation", "max_occlusion", "max_blur", "max_crowding"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0,1], got {value}")


class QualityGate:
    """Map grades onto a pass/reject verdict with an attributable reason.

    Pure and stateless: the same grades always produce the same verdict, which
    is what lets a rejection be reproduced from a replay (V13). Counting is the
    engine's job, not the gate's.
    """

    __slots__ = ("_thresholds",)

    def __init__(self, thresholds: GateThresholds | None = None) -> None:
        self._thresholds = thresholds or GateThresholds()

    @property
    def thresholds(self) -> GateThresholds:
        return self._thresholds

    def evaluate(self, grades: QualityGrades) -> GateResult:
        """Decide. Every rejection names its axis and its measurement."""
        t = self._thresholds

        # Degenerate geometry first: nothing else is meaningful without area.
        if grades.scale_pixels is not None and grades.scale_pixels <= 0.0:
            return GateResult.reject(
                GateRejection.DEGENERATE_GEOMETRY,
                "the region has no area in source pixels",
            )

        # Scale — the strongest single predictor of a useless claim (§M8).
        if grades.scale_pixels is not None and grades.scale_pixels < t.min_scale_pixels:
            return GateResult.reject(
                GateRejection.TOO_SMALL,
                f"{grades.scale_pixels:.1f}px tall, floor is {t.min_scale_pixels:.1f}px",
            )

        # Truncation — a fragment is not the object.
        if grades.truncation is not None and grades.truncation > t.max_truncation:
            return GateResult.reject(
                GateRejection.TOO_TRUNCATED,
                f"{grades.truncation:.2f} of the object is outside the frame, "
                f"ceiling is {t.max_truncation:.2f}",
            )

        if grades.occlusion is not None and grades.occlusion > t.max_occlusion:
            return GateResult.reject(
                GateRejection.TOO_OCCLUDED,
                f"occlusion {grades.occlusion:.2f} exceeds {t.max_occlusion:.2f}",
            )

        if grades.crowding is not None and grades.crowding > t.max_crowding:
            return GateResult.reject(
                GateRejection.TOO_OCCLUDED,
                f"crowding {grades.crowding:.2f} exceeds {t.max_crowding:.2f}",
            )

        if grades.blur is not None and grades.blur > t.max_blur:
            return GateResult.reject(
                GateRejection.TOO_BLURRY,
                f"blur {grades.blur:.2f} exceeds {t.max_blur:.2f}",
            )

        if t.reject_extreme_exposure and grades.exposure in (
            ExposureLevel.UNDER,
            ExposureLevel.OVER,
        ):
            return GateResult.reject(
                GateRejection.EXPOSURE_UNUSABLE,
                f"exposure is {grades.exposure.value}",
            )

        # The estimator's own verdict is the last word, and only when it says
        # insufficient for a reason no individual threshold above caught. It is
        # checked last so the *specific* axis wins the attribution when one is
        # available — an unattributed rejection is the thing this module exists
        # to prevent.
        if grades.overall is QualityLevel.INSUFFICIENT:
            return GateResult.reject(
                GateRejection.TOO_SMALL
                if grades.scale_pixels is None
                else GateRejection.DEGENERATE_GEOMETRY,
                "the estimator graded this input insufficient",
            )

        return GateResult.accept()

    def would_pass(self, grades: QualityGrades) -> bool:
        """Cheap pre-check, used before paying for extraction.

        The same logic, so a pre-check that passes and a post-check that rejects
        can only differ because a pixel-derived grade arrived — never because two
        implementations of "good enough" drifted apart.
        """
        return self.evaluate(grades).passed
