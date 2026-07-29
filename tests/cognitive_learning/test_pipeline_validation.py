"""Unit/validation tests: aggregation, validation gates, policy classification."""

from __future__ import annotations

from app.cognitive_kernel.engines.learning.aggregator import EvidenceAggregator
from app.cognitive_kernel.engines.learning.contracts import (
    Experience,
    Impact,
    LearningCandidate,
    LearningConfig,
    LearningKind,
    CandidateState,
    Verdict,
)
from app.cognitive_kernel.engines.learning.policy import LearningPolicyManager

CFG = LearningConfig()


def _exp(statement, episode, confidence=0.8, negated=False):
    return Experience("e-" + episode, LearningKind.PATTERN_GENERALIZATION, statement, negated, confidence,
                      "ev-" + episode, episode, "reasoning", 1)


def _cand(statement="x", episodes=("a", "b", "c"), evidence=("a", "b", "c"), support=0.9, oppose=0.0,
          conf=0.9, negated=False, kind=LearningKind.PATTERN_GENERALIZATION):
    return LearningCandidate("c", kind, statement, negated, None, evidence, episodes, evidence, support,
                             oppose, conf, Impact.LOW, CandidateState.AGGREGATING, 1)


# --- aggregation ------------------------------------------------------------ #


def test_aggregation_accumulates_distinct_episodes() -> None:
    exps = [_exp("swan", "ep1"), _exp("swan", "ep2"), _exp("swan", "ep3")]
    cands = EvidenceAggregator().aggregate(exps, seq=1)
    assert len(cands) == 1 and len(cands[0].episodes) == 3 and cands[0].support > 0.9


def test_aggregation_weighs_opposition() -> None:
    exps = [_exp("x", "e1"), _exp("x", "e2"), _exp("x", "e3", negated=True)]
    cand = EvidenceAggregator().aggregate(exps, seq=1)[0]
    assert cand.oppose > 0 and cand.aggregate_confidence < cand.support  # conflict lowers confidence


# --- validation gates (needs the state manager for consistency) ------------- #


def test_validation_gates() -> None:
    from ._ln import make_learning, teardown
    from app.cognitive_kernel.engines.learning.validation import ValidationPipeline

    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        v = ValidationPipeline(state, CFG)
        # too few episodes -> insufficient (LeL7)
        assert v.validate(_cand(episodes=("a",), evidence=("a",))).verdict is Verdict.INSUFFICIENT_EVIDENCE
        # opposition not overcome -> disconfirmed (LeL10)
        assert v.validate(_cand(support=0.6, oppose=0.55, conf=0.6)).verdict is Verdict.DISCONFIRMED
        # below the confidence floor -> low confidence (LeL9)
        assert v.validate(_cand(support=0.5, oppose=0.0, conf=0.4)).verdict is Verdict.LOW_CONFIDENCE
        # sufficient, corroborated, consistent -> PASS
        assert v.validate(_cand()).verdict is Verdict.PASS
    finally:
        teardown(kernel, rt, state, learn)


def test_consistency_blocks_contradiction() -> None:
    from ._ln import active_belief, make_learning, teardown
    from app.cognitive_kernel.engines.learning.validation import ValidationPipeline

    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        active_belief(state, ctx, "sky_blue", confidence=0.95)         # established knowledge
        v = ValidationPipeline(state, CFG)
        result = v.validate(_cand(statement="sky_blue", negated=True, conf=0.8))  # the opposite, weaker
        assert result.verdict is Verdict.INCONSISTENT and not result.consistency_ok  # LeL12/LeL23
    finally:
        teardown(kernel, rt, state, learn)


# --- policy ----------------------------------------------------------------- #


def test_policy_impact_classification() -> None:
    pm = LearningPolicyManager(CFG)
    assert pm.classify_impact(_cand(statement="swans_white")) is Impact.LOW
    assert pm.classify_impact(_cand(statement="x", kind=LearningKind.RULE_INDUCTION)) is Impact.MODERATE
    assert pm.classify_impact(_cand(statement="relax_safety_rule")) is Impact.HIGH
    assert pm.requires_authorization(Impact.LOW) is False
    assert pm.requires_authorization(Impact.HIGH) is True


def test_constitution_is_forbidden() -> None:
    pm = LearningPolicyManager(CFG)
    forbidden, _ = pm.forbidden(_cand(statement="amend_the_constitution"))
    assert forbidden  # LeL5 — the constitution can never be learned
