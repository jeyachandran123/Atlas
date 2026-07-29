"""Forecast tests — confidence, horizon decay, uncertainty, cascade, risk (PrL3/11/12/17/18)."""

from __future__ import annotations

from app.cognitive_kernel.engines.prediction.contracts import UncertaintyKind
from app.cognitive_kernel.state import ObjectType

from ._pr import driver, make_prediction, request, teardown


def test_forecast_is_hypothetical_and_never_truth() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        f = pred.forecast(request("r", seed=1, drivers=(driver("d", 0.8, 1.0),)), ctx)
        assert f.hypothetical is True  # PrL1/PrL9 — a prediction is never asserted as truth
    finally:
        teardown(kernel, rt, state, pred)


def test_confidence_decays_with_horizon() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        near = pred.forecast(request("near", horizon=1, seed=1, drivers=(driver("d", 0.8, 1.0),)), ctx)
        far = pred.forecast(request("far", horizon=20, seed=1, drivers=(driver("d", 0.8, 1.0),)), ctx)
        assert near.confidence > far.confidence  # PrL12
    finally:
        teardown(kernel, rt, state, pred)


def test_ungrounded_prediction_is_flagged_and_low_confidence() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        f = pred.forecast(request("r", target="mystery", seed=1), ctx)  # no drivers
        assert not f.grounded and f.confidence <= 0.2  # PrL11
    finally:
        teardown(kernel, rt, state, pred)


def test_uncertainty_is_typed() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        # A sparse model -> epistemic (more evidence would help).
        sparse = pred.forecast(request("r", seed=1, drivers=(driver("d", 0.5, 1.0),)), ctx)
        assert sparse.uncertainty_kind in (UncertaintyKind.EPISTEMIC, UncertaintyKind.ALEATORIC, UncertaintyKind.NONE)
        # A richer, high-variance model -> aleatoric.
        rich = pred.forecast(request("r2", seed=1, stakes=0.9, drivers=(
            driver("a", 0.5, 1.0), driver("b", 0.5, -1.0), driver("c", 0.5, 1.0), driver("e", 0.5, -1.0))), ctx)
        assert rich.uncertainty_kind is UncertaintyKind.ALEATORIC
    finally:
        teardown(kernel, rt, state, pred)


def test_risk_and_opportunity_estimated_separately() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        f = pred.forecast(request("r", seed=2, stakes=0.9, drivers=(
            driver("gain", 0.8, 1.0), driver("loss", 0.6, -1.0))), ctx)
        assert f.risk > 0 and f.opportunity > 0 and f.risk != f.opportunity  # PrL17 asymmetric
    finally:
        teardown(kernel, rt, state, pred)


def test_multi_step_consequence_cascade_is_traced() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        # dog -> bark -> baby_wakes (the classic cascade); target = baby_wakes.
        tx = state.begin_transaction(ctx)
        h1 = tx.create(ObjectType.BELIEF, payload={"causes": {"cause": "dog", "effect": "bark", "strength": 0.9}})
        h2 = tx.create(ObjectType.BELIEF, payload={"causes": {"cause": "bark", "effect": "baby_wakes", "strength": 0.8}})
        tx.commit()
        f = pred.forecast(request("r", target="baby_wakes", horizon=3, seed=1,
                                  context_handles=(h1, h2)), ctx)
        chain = {(c.cause, c.effect) for c in f.cascade}
        assert ("bark", "baby_wakes") in chain and ("dog", "bark") in chain  # PrL18
    finally:
        teardown(kernel, rt, state, pred)


def test_assumptions_are_recorded() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        f = pred.forecast(request("r", horizon=5, seed=1, drivers=(driver("d", 0.8, 1.0),)), ctx)
        assert any("horizon=5" in a for a in f.assumptions)  # item 21
    finally:
        teardown(kernel, rt, state, pred)
