"""Unit tests: policy, priority, resources, conflict, and the decision arbiter."""

from __future__ import annotations

from app.cognitive_kernel.engines.executive.conflict import ConflictResolver
from app.cognitive_kernel.engines.executive.contracts import (
    ConflictType,
    ExecutiveConfig,
    Goal,
    GoalState,
    GoalTier,
    Policy,
    PolicyEffect,
    PolicyFamily,
    ReasoningProposal,
    ResolutionBasis,
    ResourceKind,
)
from app.cognitive_kernel.engines.executive.decision import DecisionArbiter
from app.cognitive_kernel.engines.executive.policy import PolicyManager
from app.cognitive_kernel.engines.executive.priority import PriorityManager
from app.cognitive_kernel.engines.executive.resources import ResourceGovernor

CFG = ExecutiveConfig()


def _prop(**kw):
    base = dict(proposal_id="p", statement="s", confidence=0.9)
    base.update(kw)
    return ReasoningProposal(**base)


def _goal(gid="g", tier=GoalTier.TACTICAL, priority=0.5):
    return Goal(gid, "t", tier, GoalState.ACTIVE, priority, owner="user")


# --- policy (enforcement, precedence, absolute dominance) ------------------- #


def test_default_safety_policy_gates_irreversible_high_stakes_action() -> None:
    pm = PolicyManager(CFG)
    d = pm.evaluate(_prop(kind="action", stakes=0.9, reversibility=0.0))
    assert d.requires_approval and d.dominant_family is PolicyFamily.SAFETY


def test_absolute_safety_deny_is_non_overridable() -> None:
    pm = PolicyManager(CFG)
    pm.enact(Policy("x", PolicyFamily.SAFETY, "block", PolicyEffect.DENY,
                    predicate={"statement_contains": "wipe"}), seq=1)
    d = pm.evaluate(_prop(statement="wipe the disk", confidence=0.99))
    assert not d.allowed and d.absolute and d.dominant_family is PolicyFamily.SAFETY


def test_policy_precedence_safety_over_operational() -> None:
    pm = PolicyManager(CFG)
    pm.enact(Policy("op", PolicyFamily.REASONING, "allow_all", PolicyEffect.ALLOW, predicate={"always": True}), 1)
    pm.enact(Policy("saf", PolicyFamily.SAFETY, "deny_all", PolicyEffect.DENY, predicate={"always": True}), 2)
    d = pm.evaluate(_prop())
    assert not d.allowed and d.dominant_family is PolicyFamily.SAFETY  # safety dominates


def test_policy_versioning() -> None:
    pm = PolicyManager(CFG)
    v1 = pm.enact(Policy("r", PolicyFamily.REASONING, "depth", PolicyEffect.ALLOW), 1)
    v2 = pm.enact(Policy("r", PolicyFamily.REASONING, "depth", PolicyEffect.ALLOW), 2)
    assert v1.version == 1 and v2.version == 2


# --- priority --------------------------------------------------------------- #


def test_priority_composition_is_deterministic_and_tier_weighted() -> None:
    pm = PriorityManager(CFG)
    strat = pm.score(_goal(tier=GoalTier.STRATEGIC))
    micro = pm.score(_goal(tier=GoalTier.MICRO))
    assert strat.score > micro.score  # strategic alignment dominates
    assert pm.score(_goal()) == pm.score(_goal())  # deterministic


def test_priority_ordering() -> None:
    pm = PriorityManager(CFG)
    ps = [pm.score(_goal("a", priority=0.1)), pm.score(_goal("b", priority=0.1))]
    # equal inputs -> tie broken by id, deterministic
    assert pm.order(ps)[0] == "a"


def test_aging_boosts_priority() -> None:
    pm = PriorityManager(CFG)
    assert pm.score(_goal(), aging=0.2).score > pm.score(_goal()).score  # anti-starvation (ExL17)


# --- resources -------------------------------------------------------------- #


def test_allocation_is_bounded_by_the_finite_total() -> None:
    rg = ResourceGovernor(CFG)
    a = rg.allocate(ResourceKind.REASONING, "m1", 0.5)
    b = rg.allocate(ResourceKind.ATTENTION, "m2", 0.6)  # 0.5+0.6 > 1.0 - reservation
    assert a.granted and not b.granted  # ExL4: never over-commit
    assert rg.committed() <= CFG.total_budget


def test_priority_inversion_detected_and_repaired() -> None:
    rg = ResourceGovernor(CFG)
    rg.allocate(ResourceKind.GENERATION, "low", 0.9, priority=0.2)  # low-priority holds it all
    holder = rg.detect_priority_inversion(ResourceKind.GENERATION, blocked_priority=0.9)
    assert holder == "low"
    assert rg.apply_priority_inheritance(ResourceKind.GENERATION, "low", 0.9)  # ExL18


def test_safety_reservation_is_protected() -> None:
    rg = ResourceGovernor(CFG)
    # A reserved (safety) allocation may use the reservation floor others cannot.
    assert rg.reserve(ResourceKind.ATTENTION, "safety-monitor", 0.95).granted


# --- conflict ladder -------------------------------------------------------- #


def test_conflict_safety_dominates_absolutely() -> None:
    cr = ConflictResolver(CFG)
    c = cr.resolve(ConflictType.SAFETY, ["risky", "safe"], safety=True, safe_party="safe")
    assert c.basis is ResolutionBasis.SAFETY and c.winner == "safe" and c.resolved


def test_conflict_priority_then_confidence() -> None:
    cr = ConflictResolver(CFG)
    c1 = cr.resolve(ConflictType.GOAL, ["a", "b"], priorities={"a": 0.9, "b": 0.4})
    assert c1.basis is ResolutionBasis.PRIORITY and c1.winner == "a"
    c2 = cr.resolve(ConflictType.REASONING, ["a", "b"], priorities={"a": 0.5, "b": 0.5},
                    confidences={"a": 0.9, "b": 0.5})
    assert c2.basis is ResolutionBasis.CONFIDENCE and c2.winner == "a"


def test_conflict_escalates_when_balanced() -> None:
    cr = ConflictResolver(CFG)
    c = cr.resolve(ConflictType.GOAL, ["a", "b"], priorities={"a": 0.5, "b": 0.5})
    assert c.basis is ResolutionBasis.ESCALATE and c.escalated and not c.resolved


# --- decision arbiter ------------------------------------------------------- #


def test_threshold_scales_with_stakes_and_irreversibility() -> None:
    arb = DecisionArbiter(CFG)
    assert arb.threshold(1.0, 0.0) > arb.threshold(0.0, 1.0)  # ExL13


def test_arbiter_approves_confident_reversible_and_escalates_risky() -> None:
    arb = DecisionArbiter(CFG)
    from app.cognitive_kernel.engines.executive.contracts import PolicyDecision
    allow = PolicyDecision(True, PolicyEffect.ALLOW, None, "ok", ())
    approve = arb.decide(_prop(confidence=0.9, stakes=0.1), allow)
    assert approve.kind.value == "approve"
    escalate = arb.decide(_prop(confidence=0.4, stakes=0.9, reversibility=0.0), allow)
    assert escalate.outcome.value == "escalated"
