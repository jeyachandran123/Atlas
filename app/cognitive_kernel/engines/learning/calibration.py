"""Calibration Learning (items 13/14/34) — confidence from realized outcomes (LeL26).

Confidence evolves *only* from realized outcomes reconciled against reality — never
from hypothetical forecasts (LeL7/LeL26). This learner accumulates reconciled
prediction outcomes and, once enough have accrued (never from a few), smoothly
updates a durable calibration model. The update is reversible (the prior value is
recorded) and checkpointed. Deterministic.
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Sequence

from .contracts import Experience, LearningConfig


class CalibrationLearner:
    def __init__(self, config: LearningConfig) -> None:
        self._config = config
        self._calibration = 1.0
        self._samples = 0

    def value(self) -> float:
        return round(self._calibration, 6)

    def learn(self, reconciled: Sequence[Experience], *, seq: int) -> dict | None:
        # Never recalibrate from a handful of outcomes (LeL26).
        if len(reconciled) < self._config.calibration_min:
            return None
        realized_accuracy = mean(e.confidence for e in reconciled)  # confidence == 1 - surprise
        old = self._calibration
        new = round(0.5 * old + 0.5 * realized_accuracy, 6)
        self._calibration = new
        self._samples += len(reconciled)
        return {"from": round(old, 6), "to": new, "samples": len(reconciled),
                "episodes": sorted({e.episode for e in reconciled}), "seq": seq}

    def rollback(self, to_value: float) -> None:
        self._calibration = to_value

    def to_payload(self) -> dict[str, Any]:
        return {"calibration": self._calibration, "samples": self._samples}

    def load_payload(self, data: dict[str, Any]) -> None:
        self._calibration = float(data.get("calibration", 1.0))
        self._samples = int(data.get("samples", 0))
