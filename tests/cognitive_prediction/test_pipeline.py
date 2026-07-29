"""Integration — the simulation pipeline, executive APIs, events, runtime."""

from __future__ import annotations

from app.cognitive_kernel.runtime import ExecutionRequest

from ._pr import driver, make_prediction, request, teardown


def test_forecast_pipeline_returns_calibrated_forecast() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        f = pred.forecast(request("r", target="release_ok", horizon=2, stakes=0.8, seed=42,
                                  drivers=(driver("deploy", 0.9, 1.0), driver("outage", 0.3, -1.0))), ctx)
        assert 0.0 <= f.outcome_probability <= 1.0 and 0.0 < f.confidence <= 1.0
        assert len(f.scenarios) >= 1 and f.branch_id  # multiple futures coexist (PrL4)
    finally:
        teardown(kernel, rt, state, pred)


def test_executive_risk_api() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        rf = pred.assess_risk(request("r", target="fail", stakes=0.9, seed=7,
                                      drivers=(driver("bug", 0.6, -1.0), driver("load", 0.4, -0.5))), ctx)
        assert rf.risk > 0 and rf.severity > 0 and rf.hypothetical  # Executive Risk API (item 31)
        assert "bug" in rf.top_drivers
    finally:
        teardown(kernel, rt, state, pred)


def test_counterfactual_differs_from_prediction() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        base = pred.forecast(request("b", target="ok", seed=1,
                                     drivers=(driver("win", 0.9, 1.0), driver("crash", 0.1, -1.0))), ctx)
        cf = pred.counterfactual(request("c", target="ok", seed=1,
                                         drivers=(driver("win", 0.9, 1.0), driver("crash", 0.1, -1.0)),
                                         interventions={"crash": True}), ctx)
        assert cf.branch_kind.value == "counterfactual"
        assert cf.outcome_probability <= base.outcome_probability  # forcing the crash worsens it
    finally:
        teardown(kernel, rt, state, pred)


def test_scenario_comparison_ranks_actions() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        good = request("good", target="ok", seed=1, drivers=(driver("a", 0.9, 1.0),))
        bad = request("bad", target="ok", seed=1, drivers=(driver("a", 0.1, 1.0),))
        result = pred.compare([good, bad], ctx)
        assert result["ranking"][0] == "good"  # the more likely future ranks first (item 22)
    finally:
        teardown(kernel, rt, state, pred)


def test_prediction_events_published() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        before = kernel.services().ledger.head()
        pred.forecast(request("r", seed=1, drivers=(driver("d", 0.8, 1.0),)), ctx)
        pred.assess_risk(request("r2", seed=1, drivers=(driver("d", 0.8, -1.0),)), ctx)
        types = {e.event.type for e in kernel.services().ledger.read(since=before)}
        assert "prediction.forecast" in types and "prediction.risk" in types
        # every prediction event is tagged hypothetical (PrL15)
        forecast_events = [e for e in kernel.services().ledger.read(since=before)
                           if e.event.type == "prediction.forecast"]
        assert all(e.event.payload.get("hypothetical") for e in forecast_events)
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, pred)


def test_forecast_via_runtime_execution() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        h = rt.submit(ExecutionRequest(
            engine="prediction", operation="forecast",
            payload={"request_id": "r", "seed": 1, "drivers": [{"name": "d", "probability": 0.8, "impact": 1.0}]},
        ))
        rt.drain()
        result = h.result()
        assert result.state.value == "completed" and result.value["hypothetical"]
    finally:
        teardown(kernel, rt, state, pred)


def test_pipeline_is_deterministic() -> None:
    def run():
        kernel, rt, state, pred, ctx, admin = make_prediction()
        try:
            f = pred.forecast(request("r", seed=99, stakes=0.7,
                                      drivers=(driver("a", 0.7, 1.0), driver("b", 0.4, -1.0))), ctx)
            return f.outcome_probability, f.confidence, f.risk
        finally:
            teardown(kernel, rt, state, pred)

    assert run() == run()  # deterministic simulation lifecycle
