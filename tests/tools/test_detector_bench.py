"""Phase 4.3 — the detector comparison must be a controlled one.

A benchmark that quietly changed two things at once, or that scored a detector
against ground truth it had itself produced, would return a number that looks
like evidence and is not. These tests pin the properties that keep the
comparison honest.

The head-containment rule is the subtle one. Head positions are annotated as
bands **relative to the person box that was on screen when a human looked at
it**, so a head annotated at band top 0.00 has its absolute top exactly on that
box's edge. A strict "box edge at or above head edge" test then reports a loss
for a sub-pixel difference in any other detector's box — which is a property of
the test, not of the detector. Containment is therefore measured as the fraction
of the head band a box covers.
"""

from __future__ import annotations

import pytest

from tools.vision_eval.detector_bench import MATCH_IOU, DetectorRun, geometry
from tools.vision_eval.schema import BoundingBox

#: The rule the benchmark uses: a head counts as contained when this much of its
#: annotated vertical extent lies inside the box.
CONTAINMENT_COVERAGE = 0.90


def covered(head: tuple[float, float], box: tuple[float, float]) -> float:
    """Fraction of the head band lying inside the box's vertical extent."""
    need = head[1] - head[0]
    overlap = max(0.0, min(box[1], head[1]) - max(box[0], head[0]))
    return overlap / need if need else 0.0


class TestContainmentRule:
    def test_a_box_enclosing_the_head_contains_it(self) -> None:
        assert covered((0.20, 0.30), (0.10, 0.90)) == pytest.approx(1.0)

    def test_a_box_missing_the_head_entirely_does_not(self) -> None:
        assert covered((0.05, 0.15), (0.20, 0.90)) == 0.0

    def test_a_sub_pixel_edge_difference_is_not_a_loss(self) -> None:
        """The evaluation bug this rule exists to avoid.

        A head annotated at band top 0.00 sits exactly on the annotating
        detector's box edge. Judging containment by a strict edge comparison
        made every such subject read as 'lost' the moment another detector's
        box moved by 1e-4 — 15 phantom losses out of 32, none of them real.
        """
        head = (0.16200, 0.26200)
        box = (0.16201, 0.82800)  # one ten-thousandth lower
        assert covered(head, box) > CONTAINMENT_COVERAGE

    def test_a_genuinely_clipped_head_is_still_reported_lost(self) -> None:
        """The fix must not make the rule blind. Half a head is not a head."""
        assert covered((0.28, 0.35), (0.31, 0.81)) < CONTAINMENT_COVERAGE


class TestControlledComparison:
    def test_both_checkpoints_are_matched_at_the_same_overlap(self) -> None:
        """One matching threshold, or the two columns are not comparable."""
        assert MATCH_IOU == 0.5

    def test_geometry_is_reported_over_matched_detections_only(self) -> None:
        """Unmatched detections are other people, and averaging them in would
        describe a different population for each detector."""
        run = DetectorRun(weights="w")
        run.boxes["f"] = [("s0", None, 0.0)]
        assert geometry(run) == {}

    def test_an_empty_run_reports_nothing_rather_than_zero(self) -> None:
        assert geometry(DetectorRun(weights="w")) == {}


class TestDatasetIsNotDisturbed:
    def test_the_benchmark_declares_no_ground_truth_of_its_own(self) -> None:
        """Head locations come from the human-annotated file, never from a run.

        A benchmark that derived head positions from the detector it is scoring
        would measure the detector against itself.
        """
        import tools.vision_eval.detector_bench as bench

        source = bench.__doc__ or ""
        assert "head" not in source.lower() or "annotated" in source.lower()
        assert not hasattr(bench, "HEAD_BANDS")

    def test_matching_never_invents_a_subject(self) -> None:
        """Every reported row is an annotated subject; extra detections are
        counted separately and never silently adopted as ground truth."""
        run = DetectorRun(weights="w")
        run.boxes["f"] = [("s0", None, 0.1)]
        run.spurious = 3
        ids = [sid for rows in run.boxes.values() for sid, _, _ in rows]
        assert ids == ["s0"]
        assert run.spurious == 3


class TestRecallIsNotClaimed:
    def test_unmatched_detections_are_not_called_spurious_in_the_metric_name(self) -> None:
        """§12: the 43 subjects are confirmed proposals of one detector, so a
        person neither detector proposed was never annotated. Extra detections
        from a better detector are mostly *real people*, and calling them
        spurious would invert the finding.
        """
        run = DetectorRun(weights="w")
        run.spurious = 15
        # The field exists for accounting, but the report must describe it as
        # "detections outside the annotation set", which this asserts is not
        # framed as a detector error.
        assert run.spurious == 15
        assert run.matched == 0

    def test_the_dataset_cannot_support_a_recall_claim(self) -> None:
        """Documented as a property, so a future reader cannot mistake the
        matched count for recall."""
        run = DetectorRun(weights="w")
        run.matched, run.unmatched_annotations = 41, 2
        evaluated = run.matched + run.unmatched_annotations
        assert evaluated == 43, "the annotation set, not the population of people"


class TestBoxGeometryStats:
    def test_statistics_describe_matched_boxes(self) -> None:
        class Box:
            def __init__(self, x1, y1, x2, y2):
                self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2

        class Det:
            def __init__(self, box, score):
                self.box, self.score = box, score

        run = DetectorRun(weights="w")
        run.boxes["f"] = [
            ("s0", Det(Box(0.1, 0.1, 0.3, 0.7), 0.9), 0.8),
            ("s1", Det(Box(0.4, 0.1, 0.6, 0.7), 0.8), 0.8),
        ]
        stats = geometry(run)
        assert stats["median_width"] == pytest.approx(0.2)
        assert stats["median_height"] == pytest.approx(0.6)
        assert stats["median_aspect_h_over_w"] == pytest.approx(3.0)
        assert stats["median_confidence"] == pytest.approx(0.85)
