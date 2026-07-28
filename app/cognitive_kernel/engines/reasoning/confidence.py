"""The Confidence Estimator — calibrated, monotonic, propagated (Phase 4, Ch2 §7).

Confidence is the mind's currency (Phase 1, Ch6). This estimator enforces the two
inviolable laws: an engine's self-reported confidence is *discounted by its
calibration* (ReL3 — fluency is never trusted at face value), and a conclusion is
*no more confident than its weakest necessary premise* (ReL4 — monotonicity). It
also types the residual uncertainty (item 19) so the mind knows how to respond to
low confidence: reason more (epistemic) or hedge (aleatoric).
"""

from __future__ import annotations

from typing import Sequence

from .contracts import ReasoningConfig, UncertaintyKind


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


class ConfidenceEstimator:
    def __init__(self, config: ReasoningConfig) -> None:
        self._config = config

    def calibrate(self, engine: str, engine_confidence: float) -> float:
        """Discount an engine's self-assessment by its recorded calibration (ReL3)."""
        calibration = self._config.engine_calibration.get(engine, 0.7)
        return round(_clamp(engine_confidence) * _clamp(calibration), 6)

    def monotone(self, conclusion_confidence: float, premise_confidences: Sequence[float]) -> float:
        """Cap a conclusion at its weakest necessary premise (ReL4)."""
        if not premise_confidences:
            return _clamp(conclusion_confidence)
        return round(min(_clamp(conclusion_confidence), min(_clamp(c) for c in premise_confidences)), 6)

    def propagate(self, step_confidences: Sequence[float]) -> float:
        """A chain is as strong as its weakest link (monotonic propagation)."""
        if not step_confidences:
            return 0.0
        return round(min(_clamp(c) for c in step_confidences), 6)

    def sufficient(self, stakes: float, reversibility: float) -> float:
        """The risk-scaled autonomy threshold (ReL13): higher stakes and lower
        reversibility demand more confidence before a conclusion stands alone."""
        risk = _clamp(stakes) * (1.0 - _clamp(reversibility))
        return round(min(0.99, self._config.confidence_sufficient + 0.3 * risk), 6)

    def classify(self, top: float, runner_up: float, *, threshold: float, evidence_count: int) -> UncertaintyKind:
        """Type the uncertainty of a below-threshold conclusion (item 19)."""
        if top >= threshold:
            return UncertaintyKind.NONE
        # Two near-tied contenders on the available evidence -> irreducible here.
        if runner_up > 0.0 and (top - runner_up) < 0.1:
            return UncertaintyKind.ALEATORIC
        # Otherwise more thought / information could resolve it.
        return UncertaintyKind.EPISTEMIC
