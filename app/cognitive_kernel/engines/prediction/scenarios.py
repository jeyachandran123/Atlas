"""Scenario generation, ranking, and comparison (Phase 6 Ch3; PrL4/PrL17/PrL19).

Generates a *bounded, stakes-scaled* set of qualitatively distinct futures — never
exhaustive (PrL19): the single most-likely, the expected, the optimistic and
pessimistic tails, and the over-weighted worst case (PrL17). Multiple futures
coexist (PrL4); they are ranked and comparable so the Executive can choose among
them (PrL20). Deterministic construction and ordering throughout.
"""

from __future__ import annotations

from typing import Sequence

from .contracts import Driver, Scenario, ScenarioKind


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _joint_probability(drivers: Sequence[Driver], fired: set[str]) -> float:
    p = 1.0
    for d in drivers:
        pf = _clamp(d.probability)
        p *= pf if d.name in fired else (1.0 - pf)
    return p


def _scenario(kind: ScenarioKind, drivers: Sequence[Driver], fired: set[str],
              baseline: float, threshold: float, note: str) -> Scenario:
    value = baseline + sum(d.impact for d in drivers if d.name in fired)
    probability = _joint_probability(drivers, fired)
    outcome = value >= threshold
    # Desirability-weighted rank: probability x value, with tail losses penalised.
    rank_score = round(probability * value, 6)
    return Scenario(
        scenario_id=f"scn-{kind.value}", kind=kind, fired=tuple(sorted(fired)),
        outcome=outcome, value=round(value, 6), probability=round(probability, 6),
        rank_score=rank_score, note=note,
    )


def generate_scenarios(
    drivers: Sequence[Driver], *, baseline: float, threshold: float, num_scenarios: int, stakes: float,
) -> list[Scenario]:
    positive = {d.name for d in drivers if d.impact > 0}
    negative = {d.name for d in drivers if d.impact < 0}
    modal = {d.name for d in drivers if _clamp(d.probability) >= 0.5}

    scenarios: list[Scenario] = [
        _scenario(ScenarioKind.EXPECTED, drivers, modal, baseline, threshold, "the modal future"),
    ]
    # Low-stakes matters get a single fast future (System-1); higher stakes broaden (PrL19).
    if stakes >= 0.3:
        modal_positive = {d.name for d in drivers if d.impact > 0 and _clamp(d.probability) >= 0.5}
        scenarios.append(_scenario(ScenarioKind.OPTIMISTIC, drivers, positive, baseline, threshold,
                                   "favourable drivers realise"))
        # Plausible downside: risks fire, but the likely upsides still stand.
        scenarios.append(_scenario(ScenarioKind.PESSIMISTIC, drivers, negative | modal_positive,
                                    baseline, threshold, "adverse drivers realise"))
        # The worst case: every risk fires and no upside materialises (over-weighted, PrL17).
        scenarios.append(_scenario(ScenarioKind.TAIL_RISK, drivers, set(negative), baseline, threshold,
                                   "worst case — all risks materialise, no upside"))
    # De-duplicate identical fired sets, keep the richest labelling, bound the count.
    unique: dict[tuple[str, ...], Scenario] = {}
    for s in scenarios:
        unique.setdefault(s.fired, s)
    ranked = rank_scenarios(list(unique.values()))
    return ranked[: max(1, num_scenarios)]


def rank_scenarios(scenarios: Sequence[Scenario]) -> list[Scenario]:
    """Rank futures by desirability (item 8), deterministic tie-break by kind."""
    return sorted(scenarios, key=lambda s: (-s.rank_score, s.kind.value))


def counterfactual_scenario(
    drivers: Sequence[Driver], *, baseline: float, threshold: float, interventions,
) -> Scenario:
    """A contrary-to-fact future with drivers forced on/off (PrL10/PrL16)."""
    fired = {d.name for d in drivers if interventions.get(d.name, _clamp(d.probability) >= 0.5)}
    return _scenario(ScenarioKind.COUNTERFACTUAL, drivers, fired, baseline, threshold,
                     f"counterfactual: {dict(interventions)}")


def compare_scenarios(scenarios: Sequence[Scenario]) -> tuple[str, ...]:
    """Ordered scenario ids, best-first (item 22)."""
    return tuple(s.scenario_id for s in rank_scenarios(scenarios))
