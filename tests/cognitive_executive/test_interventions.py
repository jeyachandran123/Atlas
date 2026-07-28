"""Interventions — interrupt, pause/resume, escalate, resource repair, allocation."""

from __future__ import annotations

from app.cognitive_kernel.engines.executive import ConflictType, ResourceKind
from app.cognitive_kernel.engines.executive.contracts import DecisionKind
from app.cognitive_kernel.engines.executive.state_io import decision_trail

from ._ex import make_executive, teardown


def test_interrupt_preempts_and_records() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        low = ex.create_goal(ctx, title="low", owner="user", priority=0.2)
        assert ex.interrupt(ctx, low.goal_id, "high-priority-matter")
        from app.cognitive_kernel.engines.executive import GoalState
        assert ex._goals.get_goal(low.goal_id).state is GoalState.SUSPENDED  # noqa: SLF001
        assert ex.metrics().interventions >= 1
    finally:
        teardown(kernel, rt, state, ex)


def test_escalation_is_a_recorded_decision() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        ruling = ex.escalate(ctx, "contested-matter", "authority contested")
        assert ruling.kind is DecisionKind.ESCALATE and ruling.outcome.value == "escalated"
        kinds = {o.payload["kind"] for o in decision_trail(state, subject="contested-matter")}
        assert DecisionKind.ESCALATE.value in kinds  # ExL14 human path, audited
    finally:
        teardown(kernel, rt, state, ex)


def test_allocation_and_exhaustion() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        a = ex.allocate(ctx, ResourceKind.REASONING, "m1", 0.5, priority=0.8)
        b = ex.allocate(ctx, ResourceKind.GENERATION, "m2", 0.6, priority=0.3)
        assert a.granted and not b.granted           # bounded total (ExL4)
        assert ex.metrics().committed_budget <= 1.0
    finally:
        teardown(kernel, rt, state, ex)


def test_priority_inversion_repair() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        ex.allocate(ctx, ResourceKind.GENERATION, "low", 0.9, priority=0.2)  # fully held by low priority
        holder = ex.repair_priority_inversion(ctx, ResourceKind.GENERATION, blocked_priority=0.9)
        assert holder == "low" and ex.metrics().interventions >= 1  # ExL18
    finally:
        teardown(kernel, rt, state, ex)


def test_wm_capacity_guidance_is_a_budget_not_a_forced_mutation() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        result = ex.guide_wm_capacity(ctx, "conversation-42", 0.3)
        assert result.resource is ResourceKind.WORKING_MEMORY  # guidance, not a WM mutation (item 24)
    finally:
        teardown(kernel, rt, state, ex)


def test_conflict_resolution_recorded() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        c = ex.resolve_conflict(ctx, ConflictType.GOAL, ["a", "b"], priorities={"a": 0.9, "b": 0.3})
        assert c.winner == "a" and c.resolved and ex.metrics().conflicts_resolved == 1
        assert decision_trail(state, subject=c.conflict_id)  # never silent (ExL23)
    finally:
        teardown(kernel, rt, state, ex)
