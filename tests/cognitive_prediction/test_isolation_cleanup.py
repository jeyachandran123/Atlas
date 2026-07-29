"""Branch isolation, canonical-state protection, cleanup, and simulation budget."""

from __future__ import annotations

import pytest

from app.cognitive_kernel.state import ObjectType
from app.cognitive_kernel.engines.prediction.errors import SimulationBudgetExceeded

from ._pr import driver, make_prediction, request, teardown


def test_forecast_never_modifies_canonical_state() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        # Seed some canonical objects; record the watermark.
        tx = state.begin_transaction(ctx)
        tx.create(ObjectType.BELIEF, payload={"statement": "x"})
        tx.create(ObjectType.GOAL, payload={"title": "g", "state": "active", "owner": "u", "tier": "tactical"})
        tx.commit()
        before = pred.canonical_watermark()
        regions_before = state.metrics().by_region

        for i in range(10):
            pred.forecast(request(f"r{i}", target="ok", stakes=0.9, seed=i,
                                  drivers=(driver("a", 0.7, 1.0), driver("b", 0.4, -1.0))), ctx)
            pred.assess_risk(request(f"k{i}", seed=i, drivers=(driver("b", 0.5, -1.0),)), ctx)
            pred.counterfactual(request(f"c{i}", seed=i, drivers=(driver("a", 0.7, 1.0),),
                                        interventions={"a": True}), ctx)

        assert pred.canonical_watermark() == before          # PrL8 — no objects added/removed
        assert state.metrics().by_region == regions_before   # no region touched
        assert pred.canonical_writes() == 0                  # zero write path, by construction
    finally:
        teardown(kernel, rt, state, pred)


def test_branches_are_destroyed_after_completion() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        pred.forecast(request("r", seed=1, drivers=(driver("d", 0.8, 1.0),)), ctx)
        created, destroyed, archived, open_ = pred._sim.counts()  # noqa: SLF001
        assert open_ == 0 and destroyed == created and archived == 0  # item 36: cleaned up
    finally:
        teardown(kernel, rt, state, pred)


def test_retained_branch_is_archived_not_destroyed() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        pred.forecast(request("r", seed=1, retain=True, drivers=(driver("d", 0.8, 1.0),)), ctx)
        _, _, archived, open_ = pred._sim.counts()  # noqa: SLF001
        assert archived == 1 and open_ == 0  # explicitly retained for audit (hypothetical, PrL15)
    finally:
        teardown(kernel, rt, state, pred)


def test_branch_holds_references_not_copies() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction(retain_default=True)
    try:
        tx = state.begin_transaction(ctx)
        h = tx.create(ObjectType.BELIEF, payload={"causes": {"cause": "c", "effect": "ok", "strength": 0.7}})
        tx.commit()
        pred.forecast(request("r", target="ok", seed=1, context_handles=(h,)), ctx)
        branch = next(iter(pred._sim._archived.values()))  # noqa: SLF001
        assert h in branch.references and branch.hypothetical  # references only (OL7), tagged hypothetical
    finally:
        teardown(kernel, rt, state, pred)


def test_simulation_budget_is_bounded() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction(max_open_branches=2)
    try:
        # Open branches without evaluating (create directly) to exhaust the budget.
        from app.cognitive_kernel.engines.prediction.contracts import PredictionRequest
        pred._sim.create(PredictionRequest("a"), (), ())  # noqa: SLF001
        pred._sim.create(PredictionRequest("b"), (), ())  # noqa: SLF001
        with pytest.raises(SimulationBudgetExceeded):
            pred._sim.create(PredictionRequest("c"), (), ())  # noqa: SLF001 - PrL13
    finally:
        teardown(kernel, rt, state, pred)


def test_cleanup_destroys_all_open_branches() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        from app.cognitive_kernel.engines.prediction.contracts import PredictionRequest
        pred._sim.create(PredictionRequest("a"), (), ())  # noqa: SLF001
        pred._sim.create(PredictionRequest("b"), (), ())  # noqa: SLF001
        assert pred.cleanup() == 2 and pred._sim.open_count() == 0  # noqa: SLF001 - item 36
    finally:
        teardown(kernel, rt, state, pred)
