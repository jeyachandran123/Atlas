"""The Consistency / Coherence Guard (Phase 4, Ch2 §8; ReL10).

Reasoning is self-consistent: contradictions are *detected and arbitrated, never
silently accepted*. This module tracks assumptions (item 15), detects
contradictions among evidence and hypotheses and against the belief set (item 16),
and resolves conflicts by the arbitration ladder (item 17): priority -> confidence
-> authority -> escalation (Phase 2, Ch7). It revises no belief itself — it emits
verdicts and conflict signals for the faculty to act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .contracts import Evidence, Hypothesis
from .evidence import _noisy_or

_EPSILON = 0.05


@dataclass(frozen=True, slots=True)
class Contradiction:
    statement: str
    positive_weight: float
    negative_weight: float
    positive_sources: tuple[str, ...]
    negative_sources: tuple[str, ...]
    resolved: bool
    winner_negated: bool | None   # None = unresolved (escalate); else the surviving polarity
    method: str                   # "confidence" | "escalate"


class AssumptionTracker:
    """Tracks unvalidated assumptions a conclusion rests on (item 15)."""

    def assumptions(self, evidence: Sequence[Evidence]) -> tuple[str, ...]:
        return tuple(sorted(e.handle for e in evidence if e.kind == "assumption"))

    def used_by(self, supporting_handles: Sequence[str], evidence: Sequence[Evidence]) -> tuple[str, ...]:
        assumption_handles = {e.handle for e in evidence if e.kind == "assumption"}
        return tuple(sorted(h for h in supporting_handles if h in assumption_handles))


class ConsistencyGuard:
    def __init__(self, hysteresis_margin: float = 0.1) -> None:
        self._margin = hysteresis_margin

    def detect(
        self, evidence: Sequence[Evidence], hypotheses: Sequence[Hypothesis]
    ) -> list[Contradiction]:
        """Find statements asserted with both polarities at meaningful weight."""
        pos: dict[str, list[tuple[float, str]]] = {}
        neg: dict[str, list[tuple[float, str]]] = {}
        for e in evidence:
            (neg if e.negated else pos).setdefault(e.statement, []).append((e.weight, e.handle))
        for h in hypotheses:
            if h.confidence <= _EPSILON:
                continue
            (neg if h.negated else pos).setdefault(h.statement, []).append((h.confidence, h.hid))

        contradictions: list[Contradiction] = []
        for statement in sorted(set(pos) & set(neg)):
            p_weight = _noisy_or([w for w, _ in pos[statement]])
            n_weight = _noisy_or([w for w, _ in neg[statement]])
            if p_weight <= _EPSILON or n_weight <= _EPSILON:
                continue
            contradictions.append(
                self._resolve(
                    statement, p_weight, n_weight,
                    tuple(sorted(s for _, s in pos[statement])),
                    tuple(sorted(s for _, s in neg[statement])),
                )
            )
        return contradictions

    def _resolve(
        self,
        statement: str,
        p_weight: float,
        n_weight: float,
        p_sources: tuple[str, ...],
        n_sources: tuple[str, ...],
    ) -> Contradiction:
        """Arbitrate: confidence decides when the margin is clear; else escalate (P10)."""
        if abs(p_weight - n_weight) >= self._margin:
            return Contradiction(
                statement, round(p_weight, 6), round(n_weight, 6), p_sources, n_sources,
                resolved=True, winner_negated=(n_weight > p_weight), method="confidence",
            )
        # Genuinely balanced and contested -> the ladder ends in escalation, not silent choice.
        return Contradiction(
            statement, round(p_weight, 6), round(n_weight, 6), p_sources, n_sources,
            resolved=False, winner_negated=None, method="escalate",
        )
