"""Intervention model — recommend-only, Executive-routed, reversible, auditable (MeL2/6/20)."""

from __future__ import annotations

from app.cognitive_kernel.engines.metacognition.contracts import (
    InterventionKind,
    InterventionRecommendation,
)

from ._mc import emit, make_meta_wired, teardown


def _rec(kind, **payload):
    engine = "" if kind is InterventionKind.FLAG else "executive"
    op = {"halt": "pause", "resume": "resume"}.get(kind.value, "escalate")
    return InterventionRecommendation("r", kind, engine, op, payload, "m1", "meta recommendation",
                                      1.0, reversible=True)


def test_intervention_request_routes_to_executive_through_runtime() -> None:
    kernel, rt, state, engines, ctx = make_meta_wired()
    try:
        ok = engines["meta"].request_intervention(_rec(InterventionKind.HALT, matter_id="m1"), ctx)
        assert ok and "executive" in rt.metrics().engine_utilization  # MeL2 — via the Executive
    finally:
        teardown(kernel, rt, state, *engines.values())


def test_intervention_is_observable_and_auditable() -> None:
    kernel, rt, state, engines, ctx = make_meta_wired()
    try:
        before = kernel.services().ledger.head()
        engines["meta"].request_intervention(_rec(InterventionKind.ESCALATE, subject="m", reason="risk"), ctx)
        types = {e.event.type for e in kernel.services().ledger.read(since=before)}
        assert "metacognition.intervention" in types  # MeL19 — every intervention recorded
    finally:
        teardown(kernel, rt, state, *engines.values())


def test_flag_is_record_only_no_runtime_request() -> None:
    kernel, rt, state, engines, ctx = make_meta_wired()
    try:
        # A FLAG carries no target — it is recorded, never submitted.
        assert engines["meta"].request_intervention(_rec(InterventionKind.FLAG), ctx) is False
    finally:
        teardown(kernel, rt, state, *engines.values())


def test_halt_is_reversible_by_resume() -> None:
    kernel, rt, state, engines, ctx = make_meta_wired()
    try:
        meta = engines["meta"]
        assert meta.request_intervention(_rec(InterventionKind.HALT, matter_id="m1"), ctx)     # halt
        assert meta.request_intervention(_rec(InterventionKind.RESUME, matter_id="m1"), ctx)   # release (MeL20)
    finally:
        teardown(kernel, rt, state, *engines.values())


def test_auto_request_submits_on_constitutional_violation() -> None:
    kernel, rt, state, engines, ctx = make_meta_wired(auto_request=True)
    try:
        # Inject a constitutional violation into the trace, then reflect.
        emit(kernel.services(), "prediction.forecast", "prediction", hypothetical=False, confidence=0.9)
        art = engines["meta"].reflect(ctx)
        assert not art.audit.compliant                      # violation detected
        assert engines["meta"].metrics().interventions_requested >= 1  # auto-submitted via runtime
        assert "executive" in rt.metrics().engine_utilization
    finally:
        teardown(kernel, rt, state, *engines.values())
