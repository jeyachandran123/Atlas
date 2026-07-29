"""The Long-Term Trend Analyzer (items 4/25) — capability trends over cycles (DeL12).

Computes per-capability maturity trends across the development history (many cycles),
and detects growth opportunities. Trend-based and aggregate — robust to noise and
gaming. Pure and deterministic.
"""

from __future__ import annotations

from typing import Sequence

from .contracts import (
    Capability,
    CapabilityAssessment,
    DevelopmentConfig,
    MaturityLevel,
    Trend,
    TrendDirection,
)


class LongTermTrendAnalyzer:
    def __init__(self, config: DevelopmentConfig) -> None:
        self._config = config

    def analyze(self, history: Sequence[dict]) -> list[Trend]:
        window = list(history)[-self._config.trend_window:]
        if len(window) < 2:
            return [Trend("overall", TrendDirection.INSUFFICIENT_DATA, 0.0, 0.0, 0.0, len(window))]
        caps = sorted({c for h in window for c in h.get("scores", {})})
        trends: list[Trend] = []
        for cap in caps:
            series = [h["scores"][cap] for h in window if cap in h.get("scores", {})]
            if len(series) < 2:
                continue
            slope = round((series[-1] - series[0]) / (len(series) - 1), 6)
            if slope > self._config.trend_epsilon:
                direction = TrendDirection.IMPROVING
            elif slope < -self._config.trend_epsilon:
                direction = TrendDirection.DECLINING
            else:
                direction = TrendDirection.STABLE
            trends.append(Trend(cap, direction, round(series[0], 6), round(series[-1], 6), slope, len(series)))
        return trends

    def growth_opportunities(self, assessments: Sequence[CapabilityAssessment]) -> list[Capability]:
        return [a.capability for a in assessments if a.maturity < MaturityLevel.MATURE]

    def regressing(self, trends: Sequence[Trend]) -> bool:
        return any(t.direction is TrendDirection.DECLINING for t in trends)
