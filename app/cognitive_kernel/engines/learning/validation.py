"""The Validation Pipeline (items 5/7/8) — the burden of proof (LeL9/LeL10/LeL23).

Learning defaults to **no change**; a candidate must *earn* a commit by surviving
every gate: multi-episode evidence sufficiency (LeL7/LeL8), disconfirmation —
opposition must be overcome by a margin (LeL10), a confidence floor (LeL9), and
belief-graph consistency — it must not contradict established, corroborated
knowledge (LeL12/LeL23). Reads existing beliefs read-only; deterministic verdicts.
"""

from __future__ import annotations

from ...state import CognitiveStateManager, ObjectStatus, ObjectType, Region
from .contracts import LearningCandidate, LearningConfig, ValidationResult, Verdict


class ValidationPipeline:
    def __init__(self, state: CognitiveStateManager, config: LearningConfig) -> None:
        self._state = state
        self._config = config

    def validate(self, candidate: LearningCandidate) -> ValidationResult:
        cfg = self._config
        ev_count = len(candidate.evidence)
        ep_count = len(candidate.episodes)

        # 1. Multi-episode evidence sufficiency (LeL7/LeL8) — never from one event.
        if ep_count < cfg.min_episodes or ev_count < cfg.min_evidence:
            return self._fail(Verdict.INSUFFICIENT_EVIDENCE, candidate, ev_count, ep_count,
                              f"needs >= {cfg.min_episodes} episodes and {cfg.min_evidence} evidence")

        # 2. Disconfirmation (LeL10) — support must overcome opposition by the margin.
        if candidate.support - candidate.oppose < cfg.disconfirm_margin:
            return self._fail(Verdict.DISCONFIRMED, candidate, ev_count, ep_count,
                              "opposing evidence not overcome")

        # 3. Confidence floor (LeL9 burden of proof).
        if candidate.aggregate_confidence < cfg.min_confidence:
            return self._fail(Verdict.LOW_CONFIDENCE, candidate, ev_count, ep_count,
                              f"confidence {candidate.aggregate_confidence:.3f} < {cfg.min_confidence}")

        # 4. Belief-graph consistency (LeL12/LeL23).
        ok, reason = self._consistency(candidate)
        if not ok:
            return ValidationResult(Verdict.INCONSISTENT, candidate.aggregate_confidence, False,
                                    ev_count, ep_count, (reason,))

        return ValidationResult(Verdict.PASS, candidate.aggregate_confidence, True, ev_count, ep_count,
                                ("evidence sufficient; disconfirmation survived; consistent",))

    def _consistency(self, candidate: LearningCandidate) -> tuple[bool, str]:
        for b in self._state.query(region=Region.R5_BELIEF, type=ObjectType.BELIEF, status=ObjectStatus.ACTIVE):
            if b.payload.get("statement") != candidate.statement:
                continue
            if bool(b.payload.get("negated", False)) != candidate.negated:  # opposite polarity
                b_conf = b.confidence if b.confidence is not None else 0.5
                # To overwrite verified knowledge, the candidate must clearly exceed it (LeL12).
                if b_conf >= candidate.aggregate_confidence - self._config.consistency_margin:
                    return False, f"contradicts active belief {b.handle} (confidence {b_conf:.3f})"
        return True, "consistent"

    def _fail(self, verdict, candidate, ev_count, ep_count, reason) -> ValidationResult:
        return ValidationResult(verdict, candidate.aggregate_confidence, True, ev_count, ep_count, (reason,))
