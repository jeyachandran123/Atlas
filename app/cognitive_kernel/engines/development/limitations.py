"""Architectural Limitation Detector (item 6) + Capability Gap Analysis (item 7).

Detects *architectural limitations* — capacity saturation, coverage gaps,
persistent miscalibration, instability — and computes the gap between each
capability's certified maturity and its target. It *detects and describes*
limitations within fixed architectural bounds (DeL13); it never removes them.
Pure and deterministic.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from .contracts import (
    Capability,
    CapabilityAssessment,
    CapabilityGap,
    DevelopmentConfig,
    DevelopmentWindow,
    Limitation,
    LimitationKind,
    MaturityLevel,
    Trend,
    TrendDirection,
)


def _lim(kind, cap, severity, detail, evidence) -> Limitation:
    return Limitation("lim-" + uuid.uuid4().hex, kind, cap, max(0.0, min(1.0, severity)), detail, tuple(evidence))


class ArchitecturalLimitationDetector:
    def __init__(self, config: DevelopmentConfig) -> None:
        self._config = config

    def detect(self, window: DevelopmentWindow, assessments: Sequence[CapabilityAssessment],
               trends: Sequence[Trend]) -> list[Limitation]:
        lims: list[Limitation] = []
        # Capacity: working-memory churn (evictions exceed loads).
        loads = window.rate("wm.loads")
        churn = window.rate("wm.evictions") / max(1.0, loads)
        if loads >= self._config.min_evidence and churn > 1.0:
            lims.append(_lim(LimitationKind.CAPACITY, Capability.WORKING_MEMORY, min(1.0, churn - 1.0),
                             f"working-memory churn {churn:.2f} indicates capacity pressure",
                             (f"loads={loads:.0f}", f"evictions={window.rate('wm.evictions'):.0f}")))
        # Calibration: predictions made but rarely reconciled against reality.
        pv = window.rate("prediction.volume")
        if pv >= self._config.min_evidence and window.rate("prediction.reconciled") / max(1.0, pv) < 0.2:
            lims.append(_lim(LimitationKind.CALIBRATION, Capability.CALIBRATION, 0.6,
                             "few predictions are reconciled — calibration evidence is thin",
                             (f"forecasts={pv:.0f}", f"reconciled={window.rate('prediction.reconciled'):.0f}")))
        # Coverage: a capability stuck low despite adequate activity.
        for a in assessments:
            if a.maturity <= MaturityLevel.DEVELOPING and a.evidence_count >= self._config.min_evidence:
                lims.append(_lim(LimitationKind.COVERAGE, a.capability, 0.5,
                                 f"{a.capability.value} certified {a.maturity.name} despite activity",
                                 (f"score={a.score:.3f}",)))
        # Robustness: a declining trend is an instability signal.
        for t in trends:
            if t.direction is TrendDirection.DECLINING:
                lims.append(_lim(LimitationKind.ROBUSTNESS, self._cap(t.metric), min(1.0, abs(t.slope) * 4),
                                 f"{t.metric} maturity is declining ({t.first:.3f} -> {t.last:.3f})",
                                 (f"slope={t.slope:.3f}",)))
        return lims

    @staticmethod
    def _cap(metric: str) -> Capability:
        try:
            return Capability(metric)
        except ValueError:
            return Capability.SELF_IMPROVEMENT


class GapAnalyzer:
    def __init__(self, config: DevelopmentConfig) -> None:
        self._config = config

    def analyze(self, assessments: Sequence[CapabilityAssessment]) -> list[CapabilityGap]:
        target = self._config.target_maturity
        gaps: list[CapabilityGap] = []
        for a in assessments:
            if a.maturity < target:
                gaps.append(CapabilityGap(
                    gap_id="gap-" + uuid.uuid4().hex, capability=a.capability, current=a.maturity,
                    target=target, gap=int(target) - int(a.maturity),
                    detail=f"{a.capability.value}: {a.maturity.name} -> {target.name}",
                ))
        return gaps
