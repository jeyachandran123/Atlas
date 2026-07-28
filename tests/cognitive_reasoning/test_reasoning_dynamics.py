"""Contradiction, escalation, recursion, multi-step, and strategy dynamics."""

from __future__ import annotations

from app.cognitive_kernel.engines.reasoning import ReasoningRequest, ReasoningStrategy, ReasoningType

from ._rz import assertion, conscious, make_reasoning, rule, teardown


def test_contradiction_is_detected_and_resolved_by_confidence() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        xp = assertion(state, ctx, "x", confidence=0.9)
        xn = assertion(state, ctx, "x", negated=True, confidence=0.3)
        conscious(wm_api, [xp, xn], ctx)
        res = rz.reason(ReasoningRequest(goal="assess x", question="x"), ctx)
        assert rz.metrics().contradictions >= 1 and rz.metrics().conflicts_resolved >= 1
        assert "x" in res.conclusion.contradictions
        assert not res.conclusion.negated  # arbitrated toward the better-supported polarity
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_unresolved_contradiction_under_stakes_escalates() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        yp = assertion(state, ctx, "y", confidence=0.5)
        yn = assertion(state, ctx, "y", negated=True, confidence=0.5)
        conscious(wm_api, [yp, yn], ctx)
        res = rz.reason(ReasoningRequest(goal="assess y", question="y", stakes=0.9), ctx)
        assert res.escalated and res.state.value == "terminated_escalate"  # ReL13/P10
        assert not res.concluded
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_low_confidence_high_stakes_escalates() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        weak = assertion(state, ctx, "maybe", confidence=0.2)
        conscious(wm_api, [weak], ctx)
        res = rz.reason(ReasoningRequest(goal="assess", question="firm_claim", stakes=0.9), ctx)
        assert res.escalated and not res.concluded  # bold only where confident (ReL13)
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_recursive_multi_step_chain() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        a = assertion(state, ctx, "a", confidence=1.0)
        chain = [rule(state, ctx, [pre], post) for pre, post in (("a", "b"), ("b", "c"), ("c", "d"))]
        conscious(wm_api, [a, *chain], ctx)
        res = rz.reason(ReasoningRequest(goal="derive d", question="d"), ctx)
        assert res.concluded and res.conclusion.statement == "d"
        assert len(res.steps) >= 4  # a -> b -> c -> d (recursive, multi-step)
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_depth_bound_stops_runaway_recursion() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning(max_depth=2)
    try:
        a = assertion(state, ctx, "a", confidence=1.0)
        chain = [rule(state, ctx, [pre], post) for pre, post in (("a", "b"), ("b", "c"), ("c", "d"))]
        conscious(wm_api, [a, *chain], ctx)
        res = rz.reason(ReasoningRequest(goal="derive d", question="d"), ctx)
        assert not res.concluded  # the goal lies beyond the recursion bound (P8)
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_strategy_switches_on_impasse() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        # A deductive request for something no conscious rule can derive: symbolic
        # fails, and the faculty switches strategy/type rather than giving up.
        ev = assertion(state, ctx, "q", confidence=0.9)
        conscious(wm_api, [ev], ctx)
        before = kernel.services().ledger.head()
        rz.reason(ReasoningRequest(goal="derive z", question="z", type_hint=ReasoningType.DEDUCTIVE), ctx)
        types = {e.event.type for e in kernel.services().ledger.read(since=before)}
        assert "reasoning.strategy_switched" in types  # impasse -> switch (Ch5)
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_deliberation_budget_bounds_the_episode() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        e1 = assertion(state, ctx, "effect1", confidence=1.0)
        from ._rz import cause

        c1 = cause(state, ctx, "C1", "effect1", strength=0.4)  # weak -> won't converge fast
        conscious(wm_api, [e1, c1], ctx)
        res = rz.reason(ReasoningRequest(goal="explain", max_steps=1), ctx)
        assert len(res.steps) <= 3  # a single engine step's worth of trace (bounded, ReL7)
    finally:
        teardown(kernel, rt, state, wm, rz)
