"""The Monte-Carlo-style simulation framework — deterministic and seeded.

Samples a bounded set of futures over the causal drivers, aggregating an outcome
distribution. It is a *deterministic* realization (a seeded PRNG): the same
request + seed yields the same forecast, so the simulation lifecycle is
reproducible while still exploring genuine scenario variety. Risk (losses) and
opportunity (gains) are accumulated *separately* to preserve their asymmetry
(PrL17). Pure function of its inputs — no I/O, no shared mutable state.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from statistics import mean, pvariance
from typing import Mapping, Sequence

from .contracts import Driver


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return sorted_values[idx]


@dataclass(frozen=True, slots=True)
class Distribution:
    outcome_probability: float
    expected_value: float
    variance: float
    opportunity: float          # mean gains (PrL17)
    risk_base: float            # mean losses (PrL17)
    tail_loss: float            # worst-case loss (p95, over-weighted downstream)
    loss_probability: float     # fraction of futures with any loss
    gain_probability: float     # fraction of futures with any gain
    values: tuple[float, ...]   # sorted outcome values (for quantile scenarios)
    samples: int


def simulate(
    drivers: Sequence[Driver],
    *,
    baseline: float,
    threshold: float,
    samples: int,
    seed: int,
    interventions: Mapping[str, bool] | None = None,
) -> Distribution:
    rng = Random(seed)
    forced = dict(interventions or {})
    values: list[float] = []
    gains: list[float] = []
    losses: list[float] = []
    outcomes = 0
    for _ in range(max(1, samples)):
        v = baseline
        g = 0.0
        l = 0.0
        for d in drivers:
            if d.name in forced:
                fired = forced[d.name]
            else:
                fired = rng.random() < _clamp(d.probability)
            if fired:
                v += d.impact
                if d.impact >= 0.0:
                    g += d.impact
                else:
                    l += -d.impact
        values.append(v)
        gains.append(g)
        losses.append(l)
        if v >= threshold:
            outcomes += 1
    n = len(values)
    ordered = tuple(sorted(values))
    return Distribution(
        outcome_probability=round(outcomes / n, 6),
        expected_value=round(mean(values), 6),
        variance=round(pvariance(values) if n > 1 else 0.0, 6),
        opportunity=round(mean(gains), 6),
        risk_base=round(mean(losses), 6),
        tail_loss=round(_quantile(sorted(losses), 0.95), 6),
        loss_probability=round(sum(1 for x in losses if x > 0) / n, 6),
        gain_probability=round(sum(1 for x in gains if x > 0) / n, 6),
        values=ordered,
        samples=n,
    )
