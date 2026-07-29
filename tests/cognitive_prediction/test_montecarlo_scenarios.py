"""Unit tests: the Monte-Carlo framework, scenario generation/ranking, drivers."""

from __future__ import annotations

from app.cognitive_kernel.engines.prediction.contracts import Driver, ScenarioKind
from app.cognitive_kernel.engines.prediction.montecarlo import simulate
from app.cognitive_kernel.engines.prediction.scenarios import (
    compare_scenarios,
    counterfactual_scenario,
    generate_scenarios,
    rank_scenarios,
)


# --- Monte-Carlo ------------------------------------------------------------ #


def test_simulation_is_seed_deterministic() -> None:
    drivers = [Driver("a", 0.7, 1.0), Driver("b", 0.3, -1.0)]
    a = simulate(drivers, baseline=0.0, threshold=0.5, samples=256, seed=42)
    b = simulate(drivers, baseline=0.0, threshold=0.5, samples=256, seed=42)
    assert a == b  # same seed -> identical distribution (deterministic lifecycle)


def test_outcome_probability_tracks_driver_probability() -> None:
    strong = simulate([Driver("d", 0.9, 1.0)], baseline=0.0, threshold=0.5, samples=512, seed=1)
    weak = simulate([Driver("d", 0.2, 1.0)], baseline=0.0, threshold=0.5, samples=512, seed=1)
    assert strong.outcome_probability > weak.outcome_probability
    assert 0.85 < strong.outcome_probability < 0.95  # ~0.9


def test_risk_and_opportunity_are_separate_and_asymmetric() -> None:
    d = simulate([Driver("gain", 0.8, 1.0), Driver("loss", 0.5, -1.0)], baseline=0.0, threshold=0.5,
                 samples=512, seed=3)
    assert d.opportunity > 0 and d.risk_base > 0        # both estimated (PrL17)
    assert d.gain_probability != d.loss_probability     # asymmetric


def test_interventions_force_driver_outcomes() -> None:
    forced_on = simulate([Driver("x", 0.01, 1.0)], baseline=0.0, threshold=0.5, samples=64, seed=1,
                         interventions={"x": True})
    assert forced_on.outcome_probability == 1.0  # counterfactual forcing overrides probability


# --- scenarios -------------------------------------------------------------- #


def test_scenario_generation_is_stakes_scaled() -> None:
    drivers = [Driver("a", 0.6, 1.0), Driver("b", 0.4, -1.0)]
    low = generate_scenarios(drivers, baseline=0.0, threshold=0.5, num_scenarios=5, stakes=0.1)
    high = generate_scenarios(drivers, baseline=0.0, threshold=0.5, num_scenarios=5, stakes=0.9)
    assert len(low) == 1 and len(high) > 1  # PrL19: bounded, stakes-scaled breadth


def test_scenarios_include_tail_risk_for_high_stakes() -> None:
    drivers = [Driver("a", 0.6, 1.0), Driver("b", 0.5, -1.0)]
    kinds = {s.kind for s in generate_scenarios(drivers, baseline=0.0, threshold=0.5,
                                                num_scenarios=5, stakes=0.9)}
    assert ScenarioKind.TAIL_RISK in kinds  # PrL17: the worst case is imagined


def test_scenario_ranking_is_deterministic() -> None:
    drivers = [Driver("a", 0.6, 1.0), Driver("b", 0.4, -1.0)]
    s = generate_scenarios(drivers, baseline=0.0, threshold=0.5, num_scenarios=5, stakes=0.9)
    assert [x.scenario_id for x in rank_scenarios(s)] == list(compare_scenarios(s))


def test_counterfactual_scenario_forces_drivers() -> None:
    drivers = [Driver("outage", 0.1, -1.0)]
    cf = counterfactual_scenario(drivers, baseline=0.0, threshold=0.5, interventions={"outage": True})
    assert cf.kind is ScenarioKind.COUNTERFACTUAL and "outage" in cf.fired


# --- driver collection (read-only) ------------------------------------------ #


def test_driver_collection_reads_causal_payloads_readonly() -> None:
    from app.cognitive_kernel.state import ObjectType
    from ._pr import make_prediction, teardown

    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        tx = state.begin_transaction(ctx)
        h = tx.create(ObjectType.BELIEF, payload={"causes": {"cause": "deploy", "effect": "success", "strength": 0.8}})
        tx.commit()
        from app.cognitive_kernel.engines.prediction.drivers import DriverCollector

        ctxd = DriverCollector(state).collect([h], target="success", baseline=0.0)
        assert len(ctxd.drivers) == 1 and ctxd.drivers[0].name == "deploy"
        assert ctxd.drivers[0].source == h  # traceability, reference not copy
    finally:
        teardown(kernel, rt, state, pred)
