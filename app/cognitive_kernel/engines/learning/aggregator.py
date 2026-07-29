"""The Evidence Aggregator (item 4/6) — multi-episode accumulation (LeL7).

Groups experiences by claim and accumulates corroborating and *opposing* evidence
across **distinct episodes**. A claim is a candidate only once it is supported by
enough independent episodes — assertion and repetition within a single episode are
not evidence (LeL7, the anti-poisoning firewall). Opposition reduces the aggregate
confidence so that contested claims fail the burden of proof (LeL9/LeL10). Pure and
deterministic.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Sequence

from .contracts import CandidateState, Experience, Impact, LearningCandidate


def _noisy_or(weights: Sequence[float]) -> float:
    survive = 1.0
    for w in weights:
        survive *= 1.0 - max(0.0, min(1.0, w))
    return 1.0 - survive


class EvidenceAggregator:
    def aggregate(self, experiences: Sequence[Experience], *, seq: int) -> list[LearningCandidate]:
        groups: dict[str, list[Experience]] = defaultdict(list)
        for e in experiences:
            groups[e.statement].append(e)

        candidates: list[LearningCandidate] = []
        for statement, exps in sorted(groups.items()):
            positives = [e for e in exps if not e.negated]
            negatives = [e for e in exps if e.negated]
            support = _noisy_or([e.confidence for e in positives])
            oppose = _noisy_or([e.confidence for e in negatives])
            negated = oppose > support
            winning = negatives if negated else positives
            episodes = tuple(sorted({e.episode for e in winning}))
            aggregate_conf = round(max(support, oppose) * (1.0 - min(support, oppose)), 6)
            candidates.append(LearningCandidate(
                candidate_id="cand-" + uuid.uuid4().hex, kind=exps[0].kind, statement=statement,
                negated=negated, target_handle=None,
                evidence=tuple(sorted({e.evidence_handle for e in exps})),
                episodes=episodes, source_handles=tuple(sorted({e.exp_id for e in exps})),
                support=round(support, 6), oppose=round(oppose, 6), aggregate_confidence=aggregate_conf,
                impact=Impact.LOW, state=CandidateState.AGGREGATING, created_seq=seq,
            ))
        return candidates
