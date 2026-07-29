"""Oversight hooks — per-faculty assessment, governance/learning/development reports."""

from __future__ import annotations

from app.cognitive_kernel.engines.metacognition.contracts import AssessmentKind

from ._mc import emit, make_meta, teardown


def test_per_faculty_oversight_hooks() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        assert meta.oversee_executive().kind is AssessmentKind.EXECUTIVE
        assert meta.oversee_reasoning().kind is AssessmentKind.REASONING
        assert meta.oversee_prediction().kind is AssessmentKind.PREDICTION
        assert meta.oversee_attention().kind is AssessmentKind.ATTENTION
        assert meta.oversee_working_memory().kind is AssessmentKind.WORKING_MEMORY
    finally:
        teardown(kernel, rt, state, meta)


def test_oversight_does_not_advance_the_reflection_cursor() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        emit(kernel.services(), "reasoning.concluded", "reasoning", confidence=0.9)
        meta.oversee_reasoning()   # peek — must not consume events
        art = meta.reflect(ctx)
        # the reasoning event is still observed by the reflection (cursor untouched by oversight)
        assert any(a.metrics.get("concluded", 0) >= 1 for a in art.assessments if a.subject == "reasoning")
    finally:
        teardown(kernel, rt, state, meta)


def test_governance_report() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        report = meta.governance_report()
        assert report.executive.kind is AssessmentKind.EXECUTIVE and report.report_id
    finally:
        teardown(kernel, rt, state, meta)


def test_learning_recommendations_are_review_gated_proposals() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        # Inject miscalibration evidence, then reflect so it becomes a finding.
        for _ in range(6):
            emit(kernel.services(), "prediction.forecast", "prediction", confidence=0.9, hypothetical=True)
            emit(kernel.services(), "prediction.reconciled", "prediction", surprise=0.8)
        meta.reflect(ctx)
        proposals = meta.learning_recommendations()  # item 38
        assert proposals and all(p["requires_human_review"] for p in proposals)  # MeL33
    finally:
        teardown(kernel, rt, state, meta)


def test_development_evidence_reports_trends() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        for _ in range(3):
            emit(kernel.services(), "reasoning.concluded", "reasoning", confidence=0.8)
            meta.reflect(ctx)
        evidence = meta.development_evidence()  # item 39
        assert evidence["reflections"] == 3 and "trends" in evidence
    finally:
        teardown(kernel, rt, state, meta)
