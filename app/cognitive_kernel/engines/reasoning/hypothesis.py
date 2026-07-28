"""The Hypothesis Manager — generation (item 5) and ranking (item 6).

Generates the live set of candidate conclusions for an episode and ranks them by
prior plausibility, evidential support (noisy-OR), and opposition. It *manages the
space of candidates*; it neither decides belief (the Consistency Guard and
Confidence Estimator qualify them) nor commits anything (ReL9). Deterministic
ordering throughout.
"""

from __future__ import annotations

import dataclasses
from typing import Sequence

from .contracts import Analogy, CausalLink, Evidence, Hypothesis, ReasoningConfig, Rule
from .evidence import EvidenceEvaluator, _noisy_or
from .inference import abduce


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


class HypothesisGenerator:
    def __init__(self, config: ReasoningConfig) -> None:
        self._config = config

    def generate(
        self,
        *,
        question: str,
        question_negated: bool,
        evidence: Sequence[Evidence],
        rules: Sequence[Rule],
        causes: Sequence[CausalLink],
        analogies: Sequence[Analogy],
    ) -> list[Hypothesis]:
        hyps: list[Hypothesis] = []
        counter = 0

        def nid() -> str:
            nonlocal counter
            counter += 1
            return f"h{counter}"

        if question:
            # Assessment mode: the question and its negation compete (self-consistency).
            hyps.append(Hypothesis(nid(), question, question_negated, prior=0.5, derivation="question"))
            hyps.append(Hypothesis(nid(), question, not question_negated, prior=0.5, derivation="question"))
        else:
            # Best-explanation mode: abduce candidate causes for the observations.
            observations = frozenset(e.statement for e in evidence if not e.negated)
            for expl in abduce(observations, causes, self._config.parsimony_penalty):
                covered_handles = tuple(sorted(
                    e.handle for e in evidence if e.statement in expl.covered and not e.negated
                ))
                hyps.append(
                    Hypothesis(
                        nid(), expl.statement, False, prior=expl.score, derivation="abduced",
                        supports=covered_handles,  # the observation evidence it explains (traceability)
                        rationale=f"explains {list(expl.covered)}",
                    )
                )
            # Abduction over rules: an observed consequent makes its antecedents candidate causes.
            seen = {(h.statement, h.negated) for h in hyps}
            for r in sorted(rules, key=lambda r: r.handle):
                if r.consequent in observations and not r.consequent_negated:
                    for a in r.antecedents:
                        if (a, False) not in seen:
                            seen.add((a, False))
                            hyps.append(
                                Hypothesis(
                                    nid(), a, False, prior=_clamp(r.reliability * 0.6),
                                    derivation="abduced_rule", rationale=f"would entail {r.consequent}",
                                )
                            )
            # Analogical transfer: a conscious source case suggests its conclusion (discounted).
            for a in sorted(analogies, key=lambda a: a.handle):
                if (a.conclusion, a.conclusion_negated) not in seen:
                    seen.add((a.conclusion, a.conclusion_negated))
                    hyps.append(
                        Hypothesis(
                            nid(), a.conclusion, a.conclusion_negated, prior=_clamp(a.strength * 0.8),
                            derivation="analogical", rationale=f"transferred via relation '{a.relation}'",
                        )
                    )
        return hyps

    def rank(self, hyps: Sequence[Hypothesis], evidence: Sequence[Evidence]) -> list[Hypothesis]:
        evaluator = EvidenceEvaluator()
        ranked: list[Hypothesis] = []
        for h in hyps:
            support, oppose = evaluator.evaluate_belief(h.statement, evidence)
            if h.negated:
                support, oppose = oppose, support
            score = _clamp(_noisy_or([h.prior, support]) * (1.0 - oppose))
            direct = {e.handle for e in evidence if e.statement == h.statement and e.negated == h.negated}
            supports = tuple(sorted(set(h.supports) | direct))  # keep abductive/analogical supports
            opposes = tuple(
                sorted(e.handle for e in evidence if e.statement == h.statement and e.negated != h.negated)
            )
            ranked.append(
                dataclasses.replace(h, confidence=round(score, 6), supports=supports, opposes=opposes)
            )
        ranked.sort(key=lambda h: (-h.confidence, h.statement, h.negated))
        return ranked[: self._config.max_hypotheses]
