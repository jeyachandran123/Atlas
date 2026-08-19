"""Phase 5 — the rules that make a violation metric trustworthy.

One rule matters more than the rest and most of this file defends it:

    ABSENT means the region was observable and the PPE was not there.
    It never means "I could not see".

A worker whose hands are in a stockpot is not a worker without gloves. If the
dataset ever confuses those, every downstream number about violations is
measuring the confusion instead of the system.
"""

from __future__ import annotations

import json

import pytest

from tools.vision_eval.ppe_dataset import (
    MINIMUM_FOR_A_RATE,
    AnnotatedPerson,
    Observability,
    PersonVisibility,
    PpeAnnotation,
    PpeFrame,
    coverage,
    load,
    quality_report,
    save,
    validate,
)
from tools.vision_eval.schema import AttributeState, BoundingBox

HEAD, HANDS = "head_covering", "hand_covering"
BOTH = (HEAD, HANDS)


def person(pid="p0", ppe=None, **kwargs) -> AnnotatedPerson:
    return AnnotatedPerson(
        person_id=pid, box=BoundingBox(0.1, 0.1, 0.3, 0.9), ppe=ppe or {}, **kwargs
    )


def frame(*people, frame_id="f1", **kwargs) -> PpeFrame:
    return PpeFrame(
        frame_id=frame_id, video_id="v1", camera_id="c1", restaurant_id="r1",
        frame_index=0, timestamp_ms=0.0, persons=tuple(people), **kwargs
    )


def ppe(state, observability, **kwargs) -> PpeAnnotation:
    return PpeAnnotation(state=state, observability=observability, **kwargs)


P, A, N, U = (
    AttributeState.PRESENT, AttributeState.ABSENT,
    AttributeState.NOT_VISIBLE, AttributeState.UNKNOWN,
)
OK, PART, NO = (
    Observability.OBSERVABLE, Observability.PARTIALLY_OBSERVABLE,
    Observability.NOT_OBSERVABLE,
)


class TestTheCentralRule:
    def test_absent_on_an_unobservable_region_is_rejected(self) -> None:
        """The annotation that manufactures a false violation."""
        issues = validate([frame(person(ppe={HANDS: ppe(A, NO)}))])
        assert any(i.rule == "decided_state_without_observability" for i in issues)

    def test_present_on_an_unobservable_region_is_also_rejected(self) -> None:
        """Symmetry matters: a fabricated compliance is a fabricated label too,
        and it inflates PRESENT precision just as silently."""
        issues = validate([frame(person(ppe={HEAD: ppe(P, NO)}))])
        assert any(i.rule == "decided_state_without_observability" for i in issues)

    def test_not_visible_on_an_unobservable_region_is_correct(self) -> None:
        assert validate([frame(person(ppe={HANDS: ppe(N, NO)}))]) == []

    def test_a_partially_observable_region_may_still_be_decided(self) -> None:
        """Half a head is often enough to see a covering. Refusing here would
        discard real evidence, and the annotator still has UNKNOWN."""
        assert validate([frame(person(ppe={HEAD: ppe(P, PART)}))]) == []

    def test_unknown_is_permitted_at_any_observability(self) -> None:
        for observability in (OK, PART, NO):
            assert validate([frame(person(ppe={HEAD: ppe(U, observability)}))]) == []

    def test_saving_an_invalid_annotation_is_refused(self, tmp_path) -> None:
        """Enforced on write, because an invalid file in the repository will
        eventually be read by something that does not check."""
        with pytest.raises(ValueError, match="unobservable"):
            save([frame(person(ppe={HANDS: ppe(A, NO)}))], tmp_path / "a.json")

    def test_a_refusal_on_a_visible_region_needs_a_reason(self) -> None:
        """Not an error — but NOT_VISIBLE where the region is fully observable
        is unusual enough to need a note, or it is probably a slip."""
        issues = validate([frame(person(ppe={HEAD: ppe(N, OK)}))])
        assert any(i.rule == "unexplained_refusal" for i in issues)
        assert validate([frame(person(ppe={HEAD: ppe(N, OK, note="behind a pillar")}))]) == []


class TestPeopleAreNotDefinedByTheDetector:
    def test_a_person_the_detector_missed_is_still_annotated(self) -> None:
        """The flaw in every earlier dataset: built from detector proposals, so
        a missed worker was invisible to every metric."""
        undetected = person("p1", detected_by_reference_model=False,
                            ppe={HEAD: ppe(P, OK)})
        report = quality_report([frame(undetected)], BOTH)
        assert report["persons_missed_by_reference_detector"] == 1
        assert report["annotated_persons"] == 1

    def test_detection_recall_is_measurable_only_when_every_person_is_marked(self) -> None:
        marked = person("p0", detected_by_reference_model=True)
        unmarked = person("p1")
        assert quality_report([frame(marked)], BOTH)["detection_recall_measurable"]
        assert not quality_report([frame(marked, unmarked)], BOTH)["detection_recall_measurable"]

    def test_an_empty_dataset_cannot_measure_detection_recall(self) -> None:
        assert not quality_report([], BOTH)["detection_recall_measurable"]


class TestStructuralValidation:
    def test_a_duplicate_person_in_one_frame_is_caught(self) -> None:
        issues = validate([frame(person("p0"), person("p0"))])
        assert any(i.rule == "duplicate_person" for i in issues)

    def test_a_duplicate_frame_id_is_caught(self) -> None:
        issues = validate([frame(frame_id="f1"), frame(frame_id="f1")])
        assert any(i.rule == "duplicate_frame" for i in issues)

    def test_a_missing_person_id_is_caught(self) -> None:
        issues = validate([frame(person(""))])
        assert any(i.rule == "missing_person_id" for i in issues)

    def test_an_undeclared_attribute_is_caught(self) -> None:
        issues = validate([frame(person(ppe={"apron": ppe(P, OK)}))], attributes=BOTH)
        assert any(i.rule == "unknown_attribute" for i in issues)

    def test_a_degenerate_box_is_refused_at_construction(self) -> None:
        with pytest.raises(ValueError):
            BoundingBox(0.5, 0.5, 0.4, 0.9)

    def test_ppe_on_an_invisible_person_is_caught(self) -> None:
        issues = validate([frame(person(
            visibility=PersonVisibility.NOT_VISIBLE, ppe={HEAD: ppe(N, NO)}
        ))])
        assert any(i.rule == "ppe_on_invisible_person" for i in issues)

    def test_model_derived_ground_truth_is_caught(self) -> None:
        """Ground truth from a model measures the system against itself."""
        issues = validate([frame(person(), annotation_source="vlm_output")])
        assert any(i.rule == "non_human_annotation" for i in issues)

    def test_validation_returns_every_issue_not_just_the_first(self) -> None:
        issues = validate([frame(person("p0", ppe={HANDS: ppe(A, NO)}), person("p0"))])
        assert len({i.rule for i in issues}) >= 2


class TestMeasurability:
    """§ "No metric is reported when the dataset cannot support it"."""

    def test_a_dataset_without_violations_cannot_measure_violation_precision(self) -> None:
        """The finding that motivated this entire phase."""
        frames = [
            frame(person(f"p{i}", ppe={HEAD: ppe(P, OK)}), frame_id=f"f{i}")
            for i in range(30)
        ]
        head = coverage(frames, BOTH)[0]
        assert head.count(AttributeState.ABSENT) == 0
        assert not head.can_measure_absent_precision
        assert "INSUFFICIENT DATA" in head.verdict()

    def test_a_handful_of_violations_is_still_insufficient(self) -> None:
        """Three examples cannot support a rate, and saying so is the point."""
        frames = [
            frame(person(f"p{i}", ppe={HEAD: ppe(A, OK)}), frame_id=f"f{i}")
            for i in range(3)
        ]
        assert not coverage(frames, BOTH)[0].can_measure_absent_precision

    def test_enough_violations_makes_the_metric_measurable(self) -> None:
        frames = [
            frame(person(f"p{i}", ppe={HEAD: ppe(A, OK)}), frame_id=f"f{i}")
            for i in range(MINIMUM_FOR_A_RATE)
        ]
        head = coverage(frames, BOTH)[0]
        assert head.can_measure_absent_precision
        assert head.verdict() == "measurable"

    def test_the_report_states_measurability_per_attribute(self) -> None:
        """Heads and hands fail independently; one figure would hide it."""
        frames = [
            frame(person(f"p{i}", ppe={HEAD: ppe(A, OK), HANDS: ppe(P, OK)}),
                  frame_id=f"f{i}")
            for i in range(MINIMUM_FOR_A_RATE)
        ]
        report = quality_report(frames, BOTH)
        assert report["attributes"][HEAD]["absent_precision_measurable"]
        assert not report["attributes"][HANDS]["absent_precision_measurable"]

    def test_the_report_is_produced_before_any_model_runs(self) -> None:
        """It takes annotations only. A quality report written after the metrics
        is a rationalisation of them."""
        import inspect

        assert "prediction" not in inspect.signature(quality_report).parameters


class TestRoundTrip:
    def test_annotations_survive_a_round_trip(self, tmp_path) -> None:
        original = frame(person("p0", ppe={
            HEAD: ppe(P, OK, note="hairnet"),
            HANDS: ppe(N, NO, note="inside a pot"),
        }))
        assert load(save([original], tmp_path / "a.json"))[0] == original

    def test_observability_survives_serialization(self, tmp_path) -> None:
        saved = save([frame(person(ppe={HANDS: ppe(N, NO)}))], tmp_path / "a.json")
        raw = json.loads(saved.read_text())
        entry = raw["frames"][0]["persons"][0]["ppe"][HANDS]
        assert entry["observability"] == "not_observable"
        assert entry["state"] == "not_visible"

    def test_a_file_from_another_schema_is_refused(self, tmp_path) -> None:
        path = tmp_path / "a.json"
        path.write_text(json.dumps({"schema_version": "1.0.0", "frames": []}))
        with pytest.raises(ValueError):
            load(path)
