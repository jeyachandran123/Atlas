"""Unit tests: assessors, detectors, compliance monitor, recommendations."""

from __future__ import annotations

from app.cognitive_kernel.engines.metacognition import assessors, detectors
from app.cognitive_kernel.engines.metacognition.compliance import ConstitutionalComplianceMonitor
from app.cognitive_kernel.engines.metacognition.contracts import (
    FindingKind,
    Grade,
    HealthLevel,
    InterventionKind,
    MetaConfig,
)
from app.cognitive_kernel.engines.metacognition.recommend import InterventionRecommendationEngine

from ._mc import window

CFG = MetaConfig()


# --- assessors -------------------------------------------------------------- #


def test_reasoning_assessment_rewards_confidence_penalises_escalation() -> None:
    good = assessors.assess_reasoning(window(event_counts={"reasoning.concluded": 10},
                                             samples={"reasoning.confidence": [0.9] * 10}), CFG)
    bad = assessors.assess_reasoning(window(event_counts={"reasoning.concluded": 2, "reasoning.escalated": 8}),
                                     CFG)
    assert good.score > bad.score and good.grade in (Grade.EXCELLENT, Grade.GOOD)


def test_prediction_assessment_measures_calibration() -> None:
    calibrated = assessors.assess_prediction(window(event_counts={"prediction.forecast": 5},
                                                    samples={"prediction.surprise": [0.05] * 5}), CFG)
    miscal = assessors.assess_prediction(window(event_counts={"prediction.forecast": 5},
                                                samples={"prediction.surprise": [0.8] * 5}), CFG)
    assert calibrated.score > miscal.score  # MeL23/MeL24


def test_assessment_confidence_scales_with_evidence() -> None:
    sparse = assessors.assess_reasoning(window(event_counts={"reasoning.concluded": 1},
                                               samples={"reasoning.confidence": [0.9]}), CFG)
    rich = assessors.assess_reasoning(window(event_counts={"reasoning.concluded": 20},
                                             samples={"reasoning.confidence": [0.9] * 20}), CFG)
    assert rich.confidence > sparse.confidence  # MeL17 — honest about its own reliability


def test_health_assessment_reflects_component_status() -> None:
    a = assessors.assess_health(window(health_status={"reasoning": "healthy", "attention": "unhealthy",
                                                      "executive": "degraded"}), CFG)
    assert a.level in (HealthLevel.DEGRADED, HealthLevel.UNHEALTHY) and a.findings


def test_evaluations_are_deterministic() -> None:
    w = window(event_counts={"reasoning.concluded": 5}, samples={"reasoning.confidence": [0.7] * 5})
    assert assessors.assess_reasoning(w, CFG) == assessors.assess_reasoning(w, CFG)


# --- detectors -------------------------------------------------------------- #


def test_failure_detector_fires_on_unhealthy_assessment() -> None:
    unhealthy = assessors.assess_runtime(window(runtime_metrics={"failure_rate": 0.9}), CFG)
    findings = detectors.detect_failures([unhealthy], CFG)
    assert findings and findings[0].kind is FindingKind.FAILURE


def test_contradiction_detector() -> None:
    w = window(event_counts={"reasoning.concluded": 4, "reasoning.contradiction": 3})
    findings = detectors.detect_contradiction_patterns(w, CFG)
    assert findings and findings[0].kind is FindingKind.CONTRADICTION


def test_calibration_and_bias_detectors() -> None:
    w = window(event_counts={"prediction.forecast": 5},
               samples={"prediction.surprise": [0.6] * 5, "prediction.confidence": [0.8] * 5})
    assert detectors.analyze_calibration(w, CFG)[0].kind is FindingKind.MISCALIBRATION
    assert detectors.detect_bias(w, CFG)[0].kind is FindingKind.BIAS


def test_fatigue_detector() -> None:
    findings = detectors.detect_fatigue(window(health_metrics={"attention.fatigue": 0.95}), CFG)
    assert findings and findings[0].kind is FindingKind.FATIGUE


def test_drift_detector() -> None:
    history = [{"reasoning_confidence": 0.9}, {"reasoning_confidence": 0.88}, {"reasoning_confidence": 0.9}]
    findings = detectors.detect_drift(history, {"reasoning_confidence": 0.5}, CFG)
    assert findings and findings[0].kind is FindingKind.DRIFT  # a large drop is detected


def test_resource_inefficiency_detector() -> None:
    findings = detectors.analyze_resource_utilization(window(health_metrics={"executive.committed_budget": 1.4}), CFG)
    assert findings and findings[0].kind is FindingKind.INEFFICIENCY


# --- compliance ------------------------------------------------------------- #


def test_compliance_monitor_passes_clean_window() -> None:
    report = ConstitutionalComplianceMonitor(CFG).audit(
        window(health_metrics={"prediction.canonical_writes": 0.0, "metacognition.canonical_writes": 0.0,
                               "executive.committed_budget": 0.5}), seq=1)
    assert report.compliant and not report.violations


def test_compliance_monitor_detects_violations() -> None:
    report = ConstitutionalComplianceMonitor(CFG).audit(
        window(health_metrics={"prediction.canonical_writes": 3.0, "executive.committed_budget": 1.5},
               samples={"prediction.nonhypothetical": [1.0], "reasoning.missing_confidence": [1.0]}), seq=1)
    assert not report.compliant and len(report.violations) >= 3  # PrL8, PrL9, ReL, ExL4


# --- recommendations -------------------------------------------------------- #


def test_recommendations_are_safe_reversible_and_executive_routed() -> None:
    w = window(health_metrics={"prediction.canonical_writes": 1.0})
    audit = ConstitutionalComplianceMonitor(CFG).audit(w, seq=1)
    recs = InterventionRecommendationEngine(CFG).recommend(list(audit.violations), [], seq=1)
    kinds = {r.kind for r in recs}
    assert InterventionKind.HALT in kinds and InterventionKind.ESCALATE in kinds  # MeL8/MeL31
    assert all(r.reversible for r in recs)                                        # MeL20
    assert all(r.target_engine in ("executive", "") for r in recs)                # MeL2 — via the Executive
