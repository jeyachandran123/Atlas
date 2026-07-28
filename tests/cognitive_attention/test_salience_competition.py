"""Unit tests: salience composition and biased competition (deterministic)."""

from __future__ import annotations

from app.cognitive_kernel.engines.attention import AttentionConfig, SalienceVector, compose
from app.cognitive_kernel.engines.attention.competition import compete, is_interrupt
from app.cognitive_kernel.engines.attention.contracts import ScoredCandidate

CFG = AttentionConfig()


def _c(v: float) -> float:
    return compose(SalienceVector(goal_relevance=v), CFG)[0]


# --- salience --------------------------------------------------------------- #


def test_salience_is_deterministic() -> None:
    v = SalienceVector(goal_relevance=0.7, urgency=0.4, cognitive_cost=0.2)
    assert compose(v, CFG) == compose(v, CFG)


def test_safety_gate_dominates() -> None:
    safe = compose(SalienceVector(safety_implications=0.95), CFG)[0]
    goal = compose(SalienceVector(goal_relevance=1.0), CFG)[0]
    assert safe >= 0.9 and safe > goal  # safety-relevant content dominates (AL8/§3.4)


def test_risk_amplified_by_irreversibility() -> None:
    reversible = compose(SalienceVector(risk=0.8, reversibility=1.0), CFG)[0]
    irreversible = compose(SalienceVector(risk=0.8, reversibility=0.0), CFG)[0]
    assert irreversible > reversible  # risk*(1-reversibility) is a dominant gate


def test_precision_modulates_gain() -> None:
    full = compose(SalienceVector(goal_relevance=0.9, confidence=1.0), CFG)[0]
    half = compose(SalienceVector(goal_relevance=0.9, confidence=0.5), CFG)[0]
    assert half < full  # confidence (precision) modulates the weighted field


def test_cost_is_subtracted() -> None:
    cheap = compose(SalienceVector(goal_relevance=0.9, cognitive_cost=0.0), CFG)[0]
    costly = compose(SalienceVector(goal_relevance=0.9, cognitive_cost=0.8), CFG)[0]
    assert costly < cheap  # opportunity cost lowers salience


def test_novelty_is_a_low_priority_dimension() -> None:
    novelty = compose(SalienceVector(novelty=1.0), CFG)[0]
    goal = compose(SalienceVector(goal_relevance=1.0), CFG)[0]
    assert novelty < goal  # curiosity/novelty are the lowest priority (§3.4)


# --- competition ------------------------------------------------------------ #


def _sc(target: str, composite: float, **dims) -> ScoredCandidate:
    v = SalienceVector(**dims)
    return ScoredCandidate(target=target, vector=v, composite=composite, breakdown={"safety_gate": v.safety_implications if v.safety_implications >= CFG.safety_veto else 0.0}, source="t")


def test_elimination_removes_below_floor() -> None:
    scored = [_sc("a", 0.05), _sc("b", 0.5)]
    winners, inhibited = compete(scored, CFG)
    assert [w.target for w in winners] == ["b"] and "a" not in inhibited  # eliminated, not merely inhibited


def test_threshold_gates_ignition() -> None:
    scored = [_sc("a", 0.35), _sc("b", 0.2)]  # both survive floor, both below ignition (0.4)
    winners, inhibited = compete(scored, CFG)
    assert winners == [] and set(inhibited) == {"a", "b"}  # AL11: ignite nothing


def test_capacity_caps_the_coalition() -> None:
    cfg = AttentionConfig(coalition_capacity=2)
    scored = [_sc(x, 0.9) for x in ("a", "b", "c", "d")]
    winners, inhibited = compete(scored, cfg)
    assert len(winners) == 2 and len(inhibited) == 2


def test_competition_is_deterministic_and_ordered() -> None:
    scored = [_sc("z", 0.6), _sc("a", 0.9), _sc("m", 0.6)]
    w1, _ = compete(list(scored), CFG)
    w2, _ = compete(list(scored), CFG)
    assert [w.target for w in w1] == [w.target for w in w2]  # deterministic
    assert w1[0].target == "a"  # highest first; ties broken by handle (a before m/z)


def test_interrupt_preempts() -> None:
    interrupt = _sc("safe", 0.95, safety_implications=0.95)
    normal = _sc("n", 0.5)
    cfg = AttentionConfig(coalition_capacity=1)
    winners, _ = compete([normal, interrupt], cfg)
    assert winners[0].target == "safe" and is_interrupt(interrupt, cfg)  # safety interrupt wins the slot
