"""Phase 3 — the measurement itself has to be trustworthy.

An evaluation harness that flatters the system is worse than none: it converts a
guess into a number and a number into confidence. These tests pin the properties
that keep a result honest — that ``NOT_VISIBLE`` is scored rather than quietly
dropped, that a missed person counts against detection, that a precision nobody
attempted reads as ``None`` and not as zero, and that a split cannot put the same
video on both sides.
"""

from __future__ import annotations

import json

import pytest

from tools.vision_eval import (
    AnnotatedFrame,
    AnnotatedSubject,
    AttributeState,
    BoundingBox,
    FailureCategory,
    PredictedFrame,
    PredictedSubject,
    evaluate,
    load_annotations,
    save_annotations,
)
from tools.vision_eval.dataset import Dataset, DatasetSplit, LeakageError, group_split

HEAD = "head_covering"
HANDS = "hand_covering"
BOTH = (HEAD, HANDS)


def truth_frame(*states, frame_id="f1", video_id="v1") -> AnnotatedFrame:
    """One frame; one annotated subject per (head, hand) pair given."""
    return AnnotatedFrame(
        frame_id=frame_id,
        video_id=video_id,
        camera_id="c1",
        restaurant_id="r1",
        frame_index=0,
        timestamp_ms=0.0,
        subjects=tuple(
            AnnotatedSubject(
                subject_id=f"s{i}",
                box=BoundingBox(0.1 + i * 0.2, 0.1, 0.25 + i * 0.2, 0.9),
                attributes={HEAD: head, HANDS: hand},
            )
            for i, (head, hand) in enumerate(states)
        ),
    )


def predicted_frame(*states, frame_id="f1", video_id="v1", **kwargs) -> PredictedFrame:
    return PredictedFrame(
        frame_id=frame_id,
        video_id=video_id,
        subjects=tuple(
            PredictedSubject(
                object_id=f"o{i}",
                box=BoundingBox(0.1 + i * 0.2, 0.1, 0.25 + i * 0.2, 0.9),
                attributes={HEAD: head, HANDS: hand},
                **kwargs,
            )
            for i, (head, hand) in enumerate(states)
        ),
        vlm_calls=kwargs.pop("vlm_calls", 0),
    )


P, A, N, U = (
    AttributeState.PRESENT,
    AttributeState.ABSENT,
    AttributeState.NOT_VISIBLE,
    AttributeState.UNKNOWN,
)


# --- the ground-truth vocabulary --------------------------------------------- #


def test_ground_truth_supports_all_four_states() -> None:
    assert {s.value for s in AttributeState} == {
        "present",
        "absent",
        "not_visible",
        "unknown",
    }


def test_not_visible_and_unknown_are_both_undecided_but_distinct() -> None:
    """Different engineering: one is a camera problem, one a taxonomy problem."""
    assert not N.is_decided and not U.is_decided
    assert N is not U


def test_present_and_absent_are_the_only_decided_states() -> None:
    assert P.is_decided and A.is_decided


# --- scoring ------------------------------------------------------------------ #


def test_agreeing_that_a_region_was_unreadable_is_correct() -> None:
    """The behaviour Phase 2 exists to produce must score as a success.

    If NOT_VISIBLE rows were excluded, a system that guessed on every crop would
    outscore one that honestly refused.
    """
    report = evaluate(
        [truth_frame((N, N))], [predicted_frame((N, N))], attributes=BOTH
    )
    assert report.attribute(HEAD).accuracy == 1.0
    assert report.attribute(HANDS).accuracy == 1.0


def test_claiming_a_state_where_the_annotator_saw_nothing_is_an_unsupported_claim() -> None:
    """The headline safety number."""
    report = evaluate(
        [truth_frame((N, N))], [predicted_frame((P, A))], attributes=BOTH
    )
    assert report.attribute(HEAD).unsupported_claims == 1
    assert report.attribute(HANDS).unsupported_claims == 1


def test_not_visible_is_never_counted_as_absent() -> None:
    """Predicting ABSENT where truth is NOT_VISIBLE is a failure, not a hit.

    Collapsing the two would score the system's most dangerous error — a chef
    with hands inside a pot reported as a chef without gloves — as correct.
    """
    report = evaluate(
        [truth_frame((P, N))], [predicted_frame((P, A))], attributes=BOTH
    )
    hands = report.attribute(HANDS)
    assert hands.accuracy == 0.0
    assert hands.confusion["not_visible"]["absent"] == 1


def test_declining_a_readable_region_is_a_failure_but_not_an_unsupported_claim() -> None:
    """Lost coverage is a real cost — it just is not a dangerous one."""
    report = evaluate(
        [truth_frame((P, P))], [predicted_frame((N, N))], attributes=BOTH
    )
    head = report.attribute(HEAD)
    assert head.accuracy == 0.0
    assert head.unsupported_claims == 0


def test_false_positives_and_false_negatives_are_counted_per_state() -> None:
    """A three-state attribute has no single 'precision'; it has one per state."""
    truth = [truth_frame((P, N), (A, N), (A, N))]
    predicted = [predicted_frame((P, N), (P, N), (A, N))]
    absent = evaluate(truth, predicted, attributes=BOTH).attribute(HEAD).score(A)
    assert (absent.support, absent.true_positive) == (2, 1)
    assert (absent.false_negative, absent.false_positive) == (1, 0)
    present = evaluate(truth, predicted, attributes=BOTH).attribute(HEAD).score(P)
    assert (present.support, present.false_positive) == (1, 1)


def test_a_state_never_predicted_has_no_precision_rather_than_zero() -> None:
    """Zero reads as 'always wrong'; the truth is 'never attempted'.

    Averaging fabricated zeros produces a fabricated mean, and that mean would
    be the number someone quotes.
    """
    report = evaluate(
        [truth_frame((P, N))], [predicted_frame((P, N))], attributes=BOTH
    )
    assert report.attribute(HEAD).score(A).precision is None
    assert report.attribute(HEAD).score(A).recall is None
    assert report.attribute(HEAD).score(P).precision == 1.0


def test_each_attribute_is_scored_separately() -> None:
    """One combined figure would hide reading heads well and guessing at hands."""
    report = evaluate(
        [truth_frame((P, N))], [predicted_frame((P, A))], attributes=BOTH
    )
    assert report.attribute(HEAD).accuracy == 1.0
    assert report.attribute(HANDS).accuracy == 0.0


def test_a_head_failure_does_not_suppress_the_hand_result() -> None:
    report = evaluate(
        [truth_frame((P, N))], [predicted_frame((N, N))], attributes=BOTH
    )
    assert report.attribute(HEAD).accuracy == 0.0
    assert report.attribute(HANDS).accuracy == 1.0


# --- detection accounting ------------------------------------------------------ #


def test_an_undetected_person_counts_against_the_system() -> None:
    """Otherwise a detector that finds one person perfectly scores 100%."""
    report = evaluate(
        [truth_frame((P, N), (P, N))], [predicted_frame((P, N))], attributes=BOTH
    )
    assert report.unmatched_truth == 1
    assert report.detection_recall == 0.5


def test_a_prediction_matching_no_annotation_is_counted_as_spurious() -> None:
    report = evaluate(
        [truth_frame((P, N))], [predicted_frame((P, N), (P, N))], attributes=BOTH
    )
    assert report.spurious_predictions == 1


def test_subjects_are_matched_by_overlap_not_by_id() -> None:
    """An annotator cannot know the platform's invented object ids."""
    truth = truth_frame((P, N))
    shifted = PredictedFrame(
        frame_id="f1",
        video_id="v1",
        subjects=(
            PredictedSubject(
                object_id="totally-different",
                box=BoundingBox(0.11, 0.12, 0.26, 0.88),
                attributes={HEAD: P, HANDS: N},
            ),
        ),
    )
    assert evaluate([truth], [shifted], attributes=BOTH).matched_subjects == 1


def test_a_box_below_the_overlap_threshold_is_not_matched() -> None:
    truth = truth_frame((P, N))
    elsewhere = PredictedFrame(
        frame_id="f1",
        video_id="v1",
        subjects=(
            PredictedSubject(
                object_id="o0",
                box=BoundingBox(0.7, 0.7, 0.95, 0.95),
                attributes={HEAD: P, HANDS: N},
            ),
        ),
    )
    report = evaluate([truth], [elsewhere], attributes=BOTH)
    assert report.matched_subjects == 0 and report.unmatched_truth == 1


def test_a_frame_the_system_never_reported_counts_as_missed_detections() -> None:
    report = evaluate([truth_frame((P, N), (P, N))], [], attributes=BOTH)
    assert report.unmatched_truth == 2
    assert report.detection_recall == 0.0


# --- failure provenance --------------------------------------------------------- #


def test_a_failure_records_the_evidence_that_produced_it() -> None:
    """A failure nobody can open is a failure nobody can fix."""
    predicted = PredictedFrame(
        frame_id="f1",
        video_id="v1",
        subjects=(
            PredictedSubject(
                object_id="o0",
                box=BoundingBox(0.1, 0.1, 0.25, 0.9),
                attributes={HEAD: A, HANDS: N},
                crop_size={HEAD: "96x96"},
                quality={HEAD: "too_small"},
                model_id="model-x",
                vlm_used=False,
            ),
        ),
    )
    failure = evaluate([truth_frame((P, N))], [predicted], attributes=BOTH).failures[0]
    assert failure.attribute == HEAD
    assert (failure.truth, failure.predicted) == ("present", "absent")
    assert failure.crop_size == "96x96" and failure.model_id == "model-x"
    assert failure.frame_id == "f1" and failure.subject_id == "s0"


def test_the_gates_own_reason_drives_the_category_rather_than_a_guess() -> None:
    """A crop the gate rejected for blur is a blur failure because it said so."""
    predicted = PredictedFrame(
        frame_id="f1",
        video_id="v1",
        subjects=(
            PredictedSubject(
                object_id="o0",
                box=BoundingBox(0.1, 0.1, 0.25, 0.9),
                attributes={HEAD: N, HANDS: N},
                quality={HEAD: "too_blurry"},
            ),
        ),
    )
    failure = evaluate([truth_frame((P, N))], [predicted], attributes=BOTH).failures[0]
    assert failure.category is FailureCategory.MOTION_BLUR


def test_an_unattributable_failure_says_so_instead_of_being_forced_into_a_bucket() -> None:
    """Forcing every failure into a named cause builds a tidy distribution on
    guesses, and finding the real distribution is the point of measuring."""
    predicted = PredictedFrame(
        frame_id="f1",
        video_id="v1",
        subjects=(
            PredictedSubject(
                object_id="o0",
                box=BoundingBox(0.1, 0.1, 0.25, 0.9),
                attributes={HEAD: U, HANDS: N},
            ),
        ),
    )
    failure = evaluate([truth_frame((N, N))], [predicted], attributes=BOTH).failures[0]
    assert failure.category is FailureCategory.UNKNOWN_FAILURE_REASON


def test_an_unsupported_claim_is_categorised_as_unknown_handling() -> None:
    predicted = predicted_frame((P, P))
    failure = evaluate([truth_frame((N, N))], [predicted], attributes=BOTH).failures[0]
    assert failure.category is FailureCategory.UNKNOWN_HANDLING_FAILURE


def test_failures_are_summarised_by_category() -> None:
    report = evaluate(
        [truth_frame((N, N), (N, N))], [predicted_frame((P, P), (P, P))], attributes=BOTH
    )
    assert report.failures_by_category()["unknown_handling_failure"] == 4


# --- cost --------------------------------------------------------------------- #


def test_vlm_usage_is_measured_so_it_can_be_reduced() -> None:
    """Phase 5 cannot claim to have minimised a number nobody recorded."""
    frames = [truth_frame((P, N), frame_id=f"f{i}") for i in range(4)]
    predictions = [
        PredictedFrame(frame_id=f"f{i}", video_id="v1", vlm_calls=2) for i in range(4)
    ]
    report = evaluate(frames, predictions, attributes=BOTH)
    assert report.vlm_calls == 8
    assert report.vlm_calls_per_1000_frames == 2000.0


def test_the_reason_a_model_was_called_is_aggregated() -> None:
    predictions = [
        PredictedFrame(
            frame_id="f1", video_id="v1", vlm_calls=1,
            vlm_call_reasons={"evidence_sufficient": 1, "gate:too_small": 3},
        )
    ]
    report = evaluate([truth_frame((P, N))], predictions, attributes=BOTH)
    assert report.vlm_call_reasons["gate:too_small"] == 3


# --- splitting ------------------------------------------------------------------ #


def test_a_video_cannot_land_on_both_sides_of_a_split() -> None:
    """Consecutive CCTV frames are near-duplicates. A leaky split produces a
    real number that describes footage the model has effectively already seen."""
    with pytest.raises(LeakageError):
        DatasetSplit(train=("v1", "v2"), test=("v1",))


def test_a_split_is_by_video_camera_or_restaurant_never_by_frame() -> None:
    with pytest.raises(ValueError):
        DatasetSplit(train=("v1",), test=("v2",), split_by="frame_id")


def test_group_split_puts_everything_unnamed_into_train() -> None:
    frames = [truth_frame((P, N), frame_id=f"f{i}", video_id=v)
              for i, v in enumerate(("v1", "v2", "v3"))]
    split = group_split(frames, split_by="video_id", test=["v3"])
    assert split.train == ("v1", "v2") and split.test == ("v3",)


def test_holding_out_a_video_that_does_not_exist_is_an_error() -> None:
    with pytest.raises(ValueError):
        group_split([truth_frame((P, N))], split_by="video_id", test=["nope"])


def test_a_dataset_reports_its_state_counts_before_any_metric() -> None:
    """A recall computed over three examples is not a measurement."""
    dataset = Dataset(
        name="d", root=None, frames=(truth_frame((P, N), (P, A), (N, N)),)
    )
    assert dataset.attribute_counts()[HEAD] == {"present": 2, "not_visible": 1}
    assert dataset.attribute_counts()[HANDS] == {"not_visible": 2, "absent": 1}


# --- persistence ---------------------------------------------------------------- #


def test_annotations_survive_a_round_trip(tmp_path) -> None:
    original = truth_frame((P, N), (A, A))
    path = save_annotations([original], tmp_path / "a.json", source="clip.mp4")
    assert load_annotations(path)[0] == original


def test_saved_annotations_record_that_a_human_produced_them(tmp_path) -> None:
    """Provenance is the difference between ground truth and a model's opinion."""
    path = save_annotations([truth_frame((P, N))], tmp_path / "a.json")
    assert json.loads(path.read_text())["annotated_by"] == "human_visual_inspection"


def test_an_annotation_file_from_another_schema_is_refused(tmp_path) -> None:
    """Silently skipping a bad file shrinks the evaluation set without saying so."""
    path = tmp_path / "a.json"
    path.write_text(json.dumps({"schema_version": "0.1.0", "frames": []}))
    with pytest.raises(ValueError):
        load_annotations(path)


def test_a_degenerate_box_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError):
        BoundingBox(0.5, 0.5, 0.5, 0.9)
    with pytest.raises(ValueError):
        BoundingBox(0.5, 0.1, 1.4, 0.9)
