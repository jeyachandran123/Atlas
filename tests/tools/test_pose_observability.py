"""Phase 4.4 — pose answers "is there a head to look at", nothing more.

The invariant every test here defends: **an unobservable head must never become
a covering claim.** A worker bent over a pot whose head the camera never saw is
not a worker without a hairnet, and the distance between those two statements is
a false violation against someone doing their job correctly.

These tests cover the observability signal only. They assert nothing about
whether a head is covered — that is the VLM's question, and pose has no opinion
on it (§21).
"""

from __future__ import annotations

import numpy as np
import pytest

from tools.vision_eval.pose_observability import (
    DEFAULT_KEYPOINT_CONFIDENCE,
    HEAD_KEYPOINTS,
    LEFT_EAR,
    LEFT_EYE,
    NOSE,
    RIGHT_EAR,
    RIGHT_EYE,
    HeadEstimate,
    HeadObservability,
    head_estimate,
    iou,
)


def keypoints(**seen: tuple[float, float, float]) -> np.ndarray:
    """A COCO-17 array with only the named head keypoints carrying signal."""
    kp = np.zeros((17, 3), dtype=np.float64)
    index = {"nose": NOSE, "left_eye": LEFT_EYE, "right_eye": RIGHT_EYE,
             "left_ear": LEFT_EAR, "right_ear": RIGHT_EAR}
    for name, value in seen.items():
        kp[index[name]] = value
    return kp


class TestHeadPointDefinition:
    """§14 — the head point must have one stable, documented definition."""

    def test_a_visible_face_locates_the_head(self) -> None:
        estimate = head_estimate(
            keypoints(nose=(0.50, 0.20, 0.9), left_eye=(0.48, 0.18, 0.8),
                      right_eye=(0.52, 0.18, 0.8))
        )
        assert estimate.observability is HeadObservability.LOCATED
        assert estimate.keypoints_seen == 3
        assert estimate.point is not None
        assert estimate.point[0] == pytest.approx(0.50, abs=0.01)

    def test_a_head_turned_away_is_still_located(self) -> None:
        """Ears without a nose is a head facing away — the camera can see it.

        Requiring the nose would refuse every worker facing a counter, which is
        most of them, and would discard evidence the camera plainly has.
        """
        estimate = head_estimate(
            keypoints(left_ear=(0.40, 0.25, 0.8), right_ear=(0.46, 0.25, 0.75))
        )
        assert estimate.observability is HeadObservability.LOCATED
        assert estimate.point[0] == pytest.approx(0.429, abs=0.01)

    def test_the_point_is_confidence_weighted(self) -> None:
        """A keypoint the model is surer about pulls the centre further."""
        estimate = head_estimate(
            keypoints(nose=(0.0, 0.5, 0.9), left_ear=(1.0, 0.5, 0.1))
        )
        assert estimate.point[0] < 0.5

    def test_a_single_keypoint_still_locates_but_is_recorded_as_thin(self) -> None:
        estimate = head_estimate(keypoints(nose=(0.5, 0.2, 0.85)))
        assert estimate.observability is HeadObservability.LOCATED
        assert estimate.keypoints_seen == 1, "so a thin location can be audited"

    def test_only_head_keypoints_are_consulted(self) -> None:
        """Shoulders are not a head. A body pose without a face is not a
        located head, however confident the rest of the skeleton is."""
        kp = np.zeros((17, 3))
        for shoulder in (5, 6):
            kp[shoulder] = (0.5, 0.5, 0.99)
        assert head_estimate(kp).observability is not HeadObservability.LOCATED
        assert set(HEAD_KEYPOINTS) == {NOSE, LEFT_EYE, RIGHT_EYE, LEFT_EAR, RIGHT_EAR}


class TestThreeStates:
    """§15 — never reduce the answer to yes/no."""

    def test_no_signal_at_all_is_not_located(self) -> None:
        estimate = head_estimate(keypoints(nose=(0.5, 0.2, 0.02)))
        assert estimate.observability is HeadObservability.NOT_LOCATED
        assert estimate.point is None

    def test_weak_signal_is_low_confidence_not_absence(self) -> None:
        """The case where the system knows it is guessing.

        Collapsing this into NOT_LOCATED would discard the distinction; into
        LOCATED it would hand a VLM the crop most likely to be misread.
        """
        estimate = head_estimate(keypoints(nose=(0.5, 0.2, 0.3)))
        assert estimate.observability is HeadObservability.LOW_CONFIDENCE
        assert estimate.point is None

    def test_the_threshold_is_explicit(self) -> None:
        below = head_estimate(keypoints(nose=(0.5, 0.2, DEFAULT_KEYPOINT_CONFIDENCE - 0.01)))
        at = head_estimate(keypoints(nose=(0.5, 0.2, DEFAULT_KEYPOINT_CONFIDENCE)))
        assert below.observability is not HeadObservability.LOCATED
        assert at.observability is HeadObservability.LOCATED


class TestTheSafetyInvariant:
    """§16, §22.7, §22.8 — the whole point of the phase."""

    def test_only_a_confidently_located_head_permits_a_covering_claim(self) -> None:
        assert HeadObservability.LOCATED.permits_a_covering_claim

    def test_a_missing_head_never_permits_a_covering_claim(self) -> None:
        """NOT_LOCATED must not reach the VLM, because whatever it answers about
        a picture of someone's back becomes a violation against that worker."""
        assert not HeadObservability.NOT_LOCATED.permits_a_covering_claim

    def test_a_low_confidence_head_never_permits_a_covering_claim(self) -> None:
        assert not HeadObservability.LOW_CONFIDENCE.permits_a_covering_claim

    def test_no_state_maps_to_a_decided_answer(self) -> None:
        """There is deliberately no state meaning 'absent'. Pose cannot see a
        covering and must never be able to express one."""
        values = {s.value for s in HeadObservability}
        assert not any(v in values for v in ("absent", "present", "head_absent"))

    def test_exactly_one_state_opens_the_gate(self) -> None:
        opens = [s for s in HeadObservability if s.permits_a_covering_claim]
        assert opens == [HeadObservability.LOCATED]


class TestAssociation:
    """§13 — a pose result must be tied to the right person."""

    def test_overlapping_boxes_associate(self) -> None:
        class Box:
            x1, y1, x2, y2 = 0.1, 0.1, 0.3, 0.9

        assert iou(Box(), (0.11, 0.11, 0.31, 0.89)) > 0.8

    def test_a_different_person_does_not_associate(self) -> None:
        """The multi-person failure: another worker's head must never be
        adopted as this subject's evidence."""
        class Box:
            x1, y1, x2, y2 = 0.1, 0.1, 0.3, 0.9

        assert iou(Box(), (0.6, 0.1, 0.8, 0.9)) == 0.0

    def test_an_unassociated_subject_is_not_located(self) -> None:
        """No pose match means no head signal — which must fail closed."""
        estimate = HeadEstimate(HeadObservability.NOT_LOCATED, None, 0.0, 0, 0.1)
        assert not estimate.observability.permits_a_covering_claim


class TestConfigurationUntouched:
    """§18, §29.3-5 — this phase changes nothing else."""

    def test_the_default_detector_is_still_yolov8n(self) -> None:
        from app.vision_os.adapters.configuration.detector_providers import (
            default_weights_path,
        )

        assert default_weights_path().name == "yolov8n.onnx"

    def test_head_evidence_is_still_448_and_hands_still_default(self) -> None:
        from app.vision_os.adapters.configuration.semantic_policy import SemanticPolicy

        policy = SemanticPolicy.from_file("config/policies/kitchen-safety.example.json")
        assert policy.output_sizes == {"head_covering": (448, 448)}
        assert "hand_covering" not in policy.output_sizes

    def test_the_head_evidence_region_is_unchanged(self) -> None:
        from app.vision_os.adapters.configuration.semantic_policy import SemanticPolicy

        policy = SemanticPolicy.from_file("config/policies/kitchen-safety.example.json")
        assert policy.evidence_regions["head_covering"] == (0.0, 0.45)

    def test_pose_is_not_imported_by_any_runtime_module(self) -> None:
        """It is an experiment under tools/, not a perception stage. Wiring it
        into the pipeline is a decision for after the measurement is reviewed."""
        import pathlib

        app = pathlib.Path("app/vision_os")
        offenders = [
            str(p) for p in app.rglob("*.py")
            if "pose_observability" in p.read_text(encoding="utf-8")
        ]
        assert offenders == []
