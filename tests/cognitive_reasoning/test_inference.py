"""Unit tests: the logical inference engine, confidence, hypotheses, evidence."""

from __future__ import annotations

from app.cognitive_kernel.engines.reasoning.confidence import ConfidenceEstimator
from app.cognitive_kernel.engines.reasoning.contracts import (
    Analogy,
    CausalLink,
    Evidence,
    Hypothesis,
    ReasoningConfig,
    UncertaintyKind,
)
from app.cognitive_kernel.engines.reasoning.evidence import EvidenceEvaluator
from app.cognitive_kernel.engines.reasoning.hypothesis import HypothesisGenerator
from app.cognitive_kernel.engines.reasoning.inference import (
    CONTRADICTION,
    abduce,
    analogize,
    causal_query,
    deduce_forward,
    induce,
    prove,
    satisfy_constraints,
)
from app.cognitive_kernel.engines.reasoning.contracts import Rule

CFG = ReasoningConfig()


def _rule(h, ants, then, rel=1.0, neg=False):
    return Rule(handle=h, antecedents=tuple(ants), consequent=then, consequent_negated=neg, reliability=rel)


# --- deduction -------------------------------------------------------------- #


def test_modus_ponens_chain_is_proven_and_ordered() -> None:
    rules = [_rule("r1", ["a"], "b", 0.9), _rule("r2", ["b"], "c", 0.8)]
    proof = prove("c", False, {"a": 0.9}, {}, rules, max_depth=4)
    assert proof.proven
    # Derivations flow premise-first: a (asserted) -> b -> c.
    assert [d.statement for d in proof.derivations] == ["a", "b", "c"]


def test_deduction_is_monotone_in_confidence() -> None:
    rules = [_rule("r1", ["a"], "b", 0.9), _rule("r2", ["b"], "c", 0.8)]
    proof = prove("c", False, {"a": 0.5}, {}, rules, max_depth=4)
    assert proof.confidence == 0.5  # no more confident than the weakest necessary premise (ReL4)


def test_recursion_is_depth_bounded() -> None:
    # a->b->c->d needs depth 3; bound it at 2 and the goal is unreachable (P8).
    rules = [_rule("r1", ["a"], "b"), _rule("r2", ["b"], "c"), _rule("r3", ["c"], "d")]
    assert prove("d", False, {"a": 1.0}, {}, rules, max_depth=4).proven
    assert not prove("d", False, {"a": 1.0}, {}, rules, max_depth=2).proven


def test_forward_chaining_derives_consequences() -> None:
    rules = [_rule("r1", ["a", "b"], "c", 0.9)]
    derived = deduce_forward({"a": 1.0, "b": 0.8}, rules, max_iters=4)
    assert [d.statement for d in derived] == ["c"] and derived[0].confidence == 0.8


# --- abduction -------------------------------------------------------------- #


def test_abduction_prefers_the_broader_explanation() -> None:
    causes = [
        CausalLink("l1", "C1", "e1", 0.9), CausalLink("l2", "C1", "e2", 0.9),
        CausalLink("l3", "C2", "e1", 0.9),
    ]
    ranked = abduce(frozenset({"e1", "e2"}), causes, parsimony_penalty=0.05)
    assert ranked[0].statement == "C1"  # explains both observations -> best explanation
    assert ranked[0].score > ranked[1].score


# --- induction -------------------------------------------------------------- #


def test_induction_confidence_grows_with_instances_but_stays_below_one() -> None:
    gens = induce(["swan1.white", "swan2.white", "swan3.white"])
    assert gens and gens[0].predicate == "white" and gens[0].count == 3
    assert 0.0 < gens[0].confidence < 1.0


# --- analogy / causal / constraints ----------------------------------------- #


def test_analogical_transfer_is_discounted() -> None:
    transfers = analogize([Analogy("a1", "is_a_mammal", "breathes_air", strength=1.0)], "is_a_mammal")
    assert transfers and transfers[0].statement == "breathes_air"
    assert transfers[0].confidence < 1.0  # analogy is never certain


def test_causal_query_returns_parents_and_children() -> None:
    causes = [CausalLink("l1", "rain", "wet"), CausalLink("l2", "wet", "slippery")]
    assert causal_query("wet", causes, direction="causes") == ["rain"]
    assert causal_query("wet", causes, direction="effects") == ["slippery"]


def test_constraint_violation_is_detected() -> None:
    rules = [_rule("c1", ["north", "south"], CONTRADICTION)]
    assert satisfy_constraints({"north": 1.0}, rules) == (True, ())
    ok, violated = satisfy_constraints({"north": 1.0, "south": 1.0}, rules)
    assert not ok and violated == ("c1",)


# --- confidence ------------------------------------------------------------- #


def test_calibration_discounts_engine_self_assessment() -> None:
    est = ConfidenceEstimator(CFG)
    assert est.calibrate("symbolic", 0.9) == 0.9         # exact engine trusted
    assert est.calibrate("heuristic", 0.9) < 0.9         # fluency discounted (ReL3)


def test_monotonicity_caps_at_weakest_premise() -> None:
    est = ConfidenceEstimator(CFG)
    assert est.monotone(0.95, [0.9, 0.4]) == 0.4         # ReL4


def test_sufficiency_threshold_scales_with_stakes_and_irreversibility() -> None:
    est = ConfidenceEstimator(CFG)
    base = est.sufficient(0.0, 1.0)
    risky = est.sufficient(1.0, 0.0)
    assert risky > base  # irreversible high-stakes demands more confidence (ReL13)


def test_uncertainty_typed_epistemic_vs_aleatoric() -> None:
    est = ConfidenceEstimator(CFG)
    assert est.classify(0.9, 0.1, threshold=0.65, evidence_count=3) is UncertaintyKind.NONE
    assert est.classify(0.4, 0.38, threshold=0.65, evidence_count=3) is UncertaintyKind.ALEATORIC
    assert est.classify(0.3, 0.0, threshold=0.65, evidence_count=1) is UncertaintyKind.EPISTEMIC


# --- hypotheses & evidence -------------------------------------------------- #


def test_hypothesis_ranking_is_deterministic_and_evidence_weighted() -> None:
    gen = HypothesisGenerator(CFG)
    ev = [Evidence("h1", "x", weight=0.9), Evidence("h2", "x", negated=True, weight=0.2)]
    hyps = gen.generate(question="x", question_negated=False, evidence=ev, rules=(), causes=(), analogies=())
    ranked = gen.rank(hyps, ev)
    assert ranked[0].statement == "x" and not ranked[0].negated  # supported polarity ranks first
    assert gen.rank(hyps, ev)[0].confidence == ranked[0].confidence  # deterministic


def test_evidence_weighting_combines_reliability_confidence_relevance() -> None:
    ev = [Evidence("h1", "q", reliability=1.0, confidence=0.8), Evidence("h2", "z", reliability=1.0, confidence=0.8)]
    weighted = EvidenceEvaluator().weigh(ev, question="q", relevant_statements=frozenset())
    by = {e.statement: e.weight for e in weighted}
    assert by["q"] > by["z"]  # on-question evidence is more relevant -> heavier
