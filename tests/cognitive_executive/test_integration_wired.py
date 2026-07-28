"""Integration with the governed faculties — coordination routed via the Runtime."""

from __future__ import annotations

from app.cognitive_kernel.state import ObjectType
from app.cognitive_kernel.engines.reasoning import ReasoningRequest
from app.cognitive_kernel.engines.executive import ReasoningProposal

from ._ex import make_executive_wired, teardown_wired


def _assert(statement, state, ctx, **payload):
    tx = state.begin_transaction(ctx)
    h = tx.create(ObjectType.EVIDENCE, payload={"statement": statement, **payload}, confidence=0.9)
    tx.commit()
    return h


def _rule(state, ctx, ants, then):
    tx = state.begin_transaction(ctx)
    h = tx.create(ObjectType.CONSTRAINT, payload={"rule": {"if": list(ants), "then": then}})
    tx.commit()
    return h


def test_governance_directives_route_through_the_runtime() -> None:
    kernel, rt, state, wm, wm_api, att, rz, ex, ctx = make_executive_wired()
    try:
        g = ex.create_goal(ctx, title="ship feature", owner="user")
        out = ex.govern(
            ReasoningProposal("p1", "execute plan", 0.9, kind="action", goal_id=g.goal_id, stakes=0.1), ctx
        )
        assert out.authorized and len(out.directives) >= 1
        # The executive coordinated the faculties ONLY through the runtime (ExL8).
        util = rt.metrics().engine_utilization
        assert "attention" in util and "reasoning" in util
    finally:
        teardown_wired(kernel, rt, state, wm, att, rz, ex)


def test_executive_governs_a_real_reasoning_proposal() -> None:
    kernel, rt, state, wm, wm_api, att, rz, ex, ctx = make_executive_wired()
    try:
        a = _assert("a", state, ctx)
        r = _rule(state, ctx, ["a"], "b")
        wm_api.load(a, ctx)
        wm_api.load(r, ctx)
        result = rz.reason(ReasoningRequest(goal="derive b", question="b"), ctx)
        assert result.concluded
        # Reasoning proposes; the executive governs the proposal (Reasoning Proposal -> Decision).
        proposal = ReasoningProposal(
            "rp", result.conclusion.statement, result.conclusion.confidence, kind="belief", stakes=0.1,
        )
        out = ex.govern(proposal, ctx)
        assert out.authorized and out.decision.kind.value == "approve"
    finally:
        teardown_wired(kernel, rt, state, wm, att, rz, ex)


def test_governance_dashboard_reports_state() -> None:
    kernel, rt, state, wm, wm_api, att, rz, ex, ctx = make_executive_wired()
    try:
        ex.create_goal(ctx, title="a", owner="user", priority=0.7)
        ex.govern(ReasoningProposal("p", "ok", 0.9, stakes=0.1), ctx)
        dash = ex.dashboard()
        assert dash.mode is not None and dash.metrics.governance_passes == 1
        assert len(dash.active_goals) == 1 and dash.policies  # constitutional policies present
    finally:
        teardown_wired(kernel, rt, state, wm, att, rz, ex)
