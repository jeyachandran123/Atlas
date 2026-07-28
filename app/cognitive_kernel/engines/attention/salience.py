"""The Salience Engine — deterministic, explainable composition (AL2/AL9/AL10).

Hybrid composition (Phase 3 §3.3-§3.4): a few *lexicographic dominance gates*
(safety veto, risk×irreversibility) over a *precision-weighted field* of the
value/priority dimensions, minus cognitive cost. Pure function of the vector and
config, so it is deterministic and reproducible.
"""

from __future__ import annotations

from .contracts import AttentionConfig, SalienceVector


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def compose(vector: SalienceVector, config: AttentionConfig) -> tuple[float, dict[str, float]]:
    """Return (composite, breakdown). Breakdown is retained for transparency."""
    v = vector
    w = config.weights

    # --- dominance gates (non-negotiable) --- #
    # Safety-relevant content must be attended: it dominates the field.
    safety_gate = v.safety_implications if v.safety_implications >= config.safety_veto else 0.0
    # High-risk, hard-to-undo content dominates the weighted tier.
    risk_gate = v.risk * (1.0 - _clamp(v.reversibility))

    # --- precision-weighted field (confidence modulates gain) --- #
    # Bounded, saturating combination (noisy-OR): a single strong dimension
    # contributes ~ weight*value; multiple dimensions combine sub-additively
    # toward 1. Deterministic and always in [0, 1].
    dims = (
        ("goal_relevance", v.goal_relevance),
        ("surprise", v.surprise),
        ("urgency", v.urgency),
        ("user_importance", v.user_importance),
        ("relationship_importance", v.relationship_importance),
        ("reward_expectation", v.reward_expectation),
        ("information_gain", v.information_gain),
        ("conflict", v.conflict),
        ("emotional_significance", v.emotional_significance),
        ("business_priority", v.business_priority),
        ("recency", v.recency),
        ("novelty", v.novelty),
        ("curiosity", v.curiosity),
    )
    survive = 1.0
    for name, value in dims:
        survive *= 1.0 - _clamp(w.get(name, 0.0) * _clamp(value))
    field = 1.0 - survive
    precision = _clamp(v.confidence)
    field_weighted = field * precision

    # --- gates dominate the field; cost is subtracted --- #
    base = max(safety_gate, risk_gate, field_weighted)
    cost = config.cost_weight * v.cognitive_cost
    composite = _clamp(base - cost)

    breakdown = {
        "safety_gate": safety_gate,
        "risk_gate": risk_gate,
        "field_weighted": field_weighted,
        "precision": precision,
        "cost": cost,
        "composite": composite,
    }
    return composite, breakdown


class SalienceEngine:
    def __init__(self, config: AttentionConfig) -> None:
        self._config = config

    def config(self) -> AttentionConfig:
        return self._config

    def set_config(self, config: AttentionConfig) -> None:
        self._config = config

    def score(self, vector: SalienceVector) -> tuple[float, dict[str, float]]:
        return compose(vector, self._config)
