"""The Forecast Manager — outcome, risk, opportunity, uncertainty, confidence.

Combines the Monte-Carlo distribution with the scenario set into a confidence-
calibrated, hypothetical :class:`Forecast`. Risk and opportunity are estimated
*separately and asymmetrically*, with tail risk over-weighted (PrL17); uncertainty
is typed epistemic vs aleatoric (PrL3); confidence is calibrated and **decays with
the horizon** (PrL12) and is capped for ungrounded predictions (PrL11); the
multi-step consequence cascade is traced (PrL18). Nothing here is asserted as
truth — every product is tagged hypothetical (PrL1/PrL9).
"""

from __future__ import annotations

import hashlib
import json
from typing import Sequence

from .contracts import (
    Consequence,
    Driver,
    Forecast,
    PredictionConfig,
    PredictionRequest,
    RiskForecast,
    UncertaintyKind,
)
from .drivers import CollectedContext
from .montecarlo import Distribution, simulate
from .scenarios import generate_scenarios


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


class ForecastManager:
    def __init__(self, config: PredictionConfig) -> None:
        self._config = config

    # --- the forward model + evaluation ---------------------------------- #

    def run(self, request: PredictionRequest, ctx: CollectedContext, *, seq: int, branch_id: str) -> Forecast:
        drivers = self._drivers(request, ctx)
        samples = min(self._config.max_samples, request.num_samples or self._config.default_samples)
        seed = request.seed if request.seed is not None else self._config.default_seed
        dist = simulate(
            drivers, baseline=ctx.baseline, threshold=request.threshold,
            samples=samples, seed=seed, interventions=request.interventions,
        )
        scenarios = generate_scenarios(
            drivers, baseline=ctx.baseline, threshold=request.threshold,
            num_scenarios=request.num_scenarios, stakes=request.stakes,
        )
        risk = self._risk(dist)
        opportunity = _clamp(dist.opportunity)
        uncertainty = self._uncertainty(dist)
        ukind = self._uncertainty_kind(drivers, uncertainty)
        confidence = self._calibrate(drivers, dist, uncertainty, request.horizon)
        cascade = self._cascade(ctx.cascade, request.target, request.horizon)
        assumptions = self._assumptions(drivers, request, dist)
        return Forecast(
            request_id=request.request_id, target=request.target, horizon=request.horizon,
            branch_kind=request.kind, outcome_probability=dist.outcome_probability,
            expected_value=dist.expected_value, risk=risk, opportunity=opportunity,
            uncertainty=uncertainty, uncertainty_kind=ukind, confidence=confidence,
            scenarios=tuple(scenarios), drivers=tuple(drivers), assumptions=assumptions,
            cascade=cascade, trace_digest=self._digest(drivers, dist, scenarios),
            hypothetical=True, grounded=bool(drivers), seq=seq, branch_id=branch_id,
        )

    def risk_only(self, forecast: Forecast, dist_like: Distribution | None = None) -> RiskForecast:
        top = tuple(d.name for d in sorted(forecast.drivers, key=lambda d: d.impact)[:3] if d.impact < 0)
        return RiskForecast(
            request_id=forecast.request_id, risk=forecast.risk,
            severity=_clamp(max((-d.impact for d in forecast.drivers if d.impact < 0), default=0.0)),
            probability=forecast.outcome_probability, top_drivers=top,
            confidence=forecast.confidence, uncertainty=forecast.uncertainty,
        )

    # --- estimators ------------------------------------------------------ #

    def _drivers(self, request: PredictionRequest, ctx: CollectedContext) -> list[Driver]:
        merged: dict[str, Driver] = {}
        for d in list(ctx.drivers) + list(request.drivers):  # request drivers override conscious ones
            merged[d.name] = d
        return sorted(merged.values(), key=lambda d: (-abs(d.impact), d.name))

    def _risk(self, dist: Distribution) -> float:
        # Asymmetric: the average loss plus an over-weighted tail (PrL17).
        return _clamp(dist.risk_base + (self._config.tail_risk_weight - 1.0) * dist.tail_loss * 0.5)

    def _uncertainty(self, dist: Distribution) -> float:
        return round(_clamp(dist.variance ** 0.5), 6)

    def _uncertainty_kind(self, drivers: Sequence[Driver], uncertainty: float) -> UncertaintyKind:
        if uncertainty < 0.05:
            return UncertaintyKind.NONE
        if len(drivers) < 3:
            return UncertaintyKind.EPISTEMIC   # a sparse model — more evidence would help
        return UncertaintyKind.ALEATORIC       # genuine variance under an adequate model

    def _calibrate(self, drivers: Sequence[Driver], dist: Distribution, uncertainty: float, horizon: int) -> float:
        sample_adequacy = min(1.0, dist.samples / 128.0)
        horizon_factor = max(0.1, 1.0 - self._config.horizon_decay * max(0, horizon))  # PrL12
        base = self._config.calibration * sample_adequacy * horizon_factor
        if not drivers:
            base = min(base, self._config.ungrounded_confidence)   # PrL11: ungrounded -> low confidence
        return round(_clamp(base * (1.0 - min(0.5, uncertainty))), 6)

    def _cascade(self, links: Sequence[tuple[str, str, float]], target: str, max_steps: int) -> tuple[Consequence, ...]:
        consequences: list[Consequence] = []
        frontier = {target}
        seen: set[tuple[str, str]] = set()
        step = 1
        while frontier and step <= max(1, max_steps) + 2:
            nxt: set[str] = set()
            for cause, effect, strength in sorted(links):
                if effect in frontier and (cause, effect) not in seen:
                    seen.add((cause, effect))
                    consequences.append(Consequence(step, cause, effect, round(strength, 4)))
                    nxt.add(cause)
            frontier = nxt
            step += 1
        return tuple(consequences)

    def _assumptions(self, drivers: Sequence[Driver], request: PredictionRequest, dist: Distribution) -> tuple[str, ...]:
        a = [
            "drivers assumed conditionally independent",
            f"horizon={request.horizon} (confidence decays with horizon, PrL12)",
            f"samples={dist.samples}; seed-deterministic",
            f"baseline tendency={request.threshold} threshold",
        ]
        if not drivers:
            a.append("UNGROUNDED: no causal drivers in conscious context (PrL11) — speculative")
        if request.interventions:
            a.append(f"counterfactual interventions forced: {dict(request.interventions)}")
        return tuple(a)

    def _digest(self, drivers, dist, scenarios) -> str:
        blob = json.dumps(
            {"d": [[x.name, x.probability, x.impact] for x in drivers],
             "o": dist.outcome_probability, "e": dist.expected_value,
             "s": [[s.kind.value, s.value, s.probability] for s in scenarios]},
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()
