"""Constitutional audit — the always-on compliance monitor (item 14/40; MeL29)."""

from __future__ import annotations

from ._mc import emit, make_meta, teardown


def test_clean_mind_is_compliant() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        report = meta.constitutional_audit(ctx)
        assert report.compliant and not report.violations
    finally:
        teardown(kernel, rt, state, meta)


def test_non_hypothetical_prediction_is_a_violation() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        emit(kernel.services(), "prediction.forecast", "prediction", hypothetical=False, confidence=0.9)
        report = meta.constitutional_audit(ctx)
        assert not report.compliant  # PrL9 — imagined content presented as non-hypothetical
        assert any("PrL9" in v.detail for v in report.violations)
    finally:
        teardown(kernel, rt, state, meta)


def test_reasoning_conclusion_without_confidence_is_a_violation() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        # publish a conclusion event lacking a confidence field
        from app.cognitive_kernel.contracts import CognitiveEvent
        kernel.services().events.publish(CognitiveEvent(
            event_id="c", type="reasoning.concluded", sequence=kernel.services().clock.tick(),
            source="reasoning", correlation_id="t", payload={"statement": "x"}))  # no confidence
        report = meta.constitutional_audit(ctx)
        assert not report.compliant and any("ReL" in v.detail for v in report.violations)
    finally:
        teardown(kernel, rt, state, meta)


def test_audit_is_confidence_qualified_and_lists_checks() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        report = meta.constitutional_audit(ctx)
        assert 0.0 < report.confidence <= 1.0 and len(report.checked) >= 5  # MeL18 + transparency
    finally:
        teardown(kernel, rt, state, meta)


def test_audit_report_published_as_event() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        before = kernel.services().ledger.head()
        meta.constitutional_audit(ctx)
        types = {e.event.type for e in kernel.services().ledger.read(since=before)}
        assert "metacognition.audit" in types
    finally:
        teardown(kernel, rt, state, meta)
