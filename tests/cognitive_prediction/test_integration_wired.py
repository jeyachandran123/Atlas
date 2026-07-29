"""Integration with governed faculties — WM context (read-only) and Executive routing."""

from __future__ import annotations

from app.cognitive_kernel.state import ObjectType
from app.cognitive_kernel.engines.executive import ReasoningProposal

from ._pr import make_prediction_executive, make_prediction_wired, request, teardown_wired


def test_conscious_context_loaded_via_working_memory() -> None:
    kernel, rt, state, wm, wm_api, pred, ctx = make_prediction_wired()
    try:
        tx = state.begin_transaction(ctx)
        h = tx.create(ObjectType.BELIEF,
                      payload={"causes": {"cause": "deploy", "effect": "release_ok", "strength": 0.85}})
        tx.commit()
        wm_api.load(h, ctx)  # make it conscious
        before = pred.canonical_watermark()
        f = pred.forecast(request("r", target="release_ok", seed=1, use_working_memory=True), ctx)
        # The forecast is grounded in the *conscious* causal driver (read-only, via WM).
        assert f.grounded and any(d.name == "deploy" for d in f.drivers)
        assert pred.canonical_watermark() == before and pred.canonical_writes() == 0  # PrL8
    finally:
        teardown_wired(kernel, rt, state, wm, pred)


def test_executive_requests_risk_through_the_runtime() -> None:
    kernel, rt, state, pred, ex, ctx = make_prediction_executive()
    try:
        # The Executive's risk API reaches Prediction ONLY via the runtime-routed port.
        proposal = ReasoningProposal("p", "risky move", 0.5, kind="action", stakes=0.9, reversibility=0.1)
        risk = ex.request_risk(proposal, ctx)
        assert risk is not None and "risk" in risk and risk.get("hypothetical") is True  # PrL1
        assert "prediction" in rt.metrics().engine_utilization  # routed through the runtime
    finally:
        teardown_wired(kernel, rt, state, pred, ex)


def test_governance_triggers_prediction_for_high_stakes() -> None:
    kernel, rt, state, pred, ex, ctx = make_prediction_executive()
    try:
        # A high-stakes irreversible proposal makes the Executive request risk (PrL21).
        ex.govern(ReasoningProposal("p", "irreversible act", 0.6, kind="action",
                                    stakes=0.95, reversibility=0.0), ctx)
        assert "prediction" in rt.metrics().engine_utilization
        assert pred.metrics().risk_assessments >= 1  # Prediction imagined the future for the Executive
    finally:
        teardown_wired(kernel, rt, state, pred, ex)
