"""Goal management — ownership, hierarchy, lifecycle, dependencies, completion."""

from __future__ import annotations

import pytest

from app.cognitive_kernel.engines.executive import GoalState, GoalTier, OwnershipError
from app.cognitive_kernel.engines.executive.contracts import DecisionKind
from app.cognitive_kernel.engines.executive.state_io import decision_trail

from ._ex import make_executive, proposal, teardown


def test_goal_requires_a_single_owner() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        g = ex.create_goal(ctx, title="ship", owner="user")
        assert g.owner == "user" and g.state is GoalState.ACTIVE  # ExL2
        with pytest.raises(OwnershipError):
            ex.create_goal(ctx, title="ownerless", owner="")
    finally:
        teardown(kernel, rt, state, ex)


def test_goal_hierarchy_and_children() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        parent = ex.create_goal(ctx, title="strategic", owner="user", tier=GoalTier.STRATEGIC)
        child = ex.create_goal(ctx, title="tactical", owner="user", tier=GoalTier.TACTICAL, parent=parent.goal_id)
        assert child.parent == parent.goal_id
        assert [g.goal_id for g in ex._goals.children(parent.goal_id)] == [child.goal_id]  # noqa: SLF001
    finally:
        teardown(kernel, rt, state, ex)


def test_goal_lifecycle_transitions() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        g = ex.create_goal(ctx, title="work", owner="user")
        assert ex.pause(ctx, g.goal_id) and ex._goals.get_goal(g.goal_id).state is GoalState.SUSPENDED  # noqa: SLF001
        assert ex.resume(ctx, g.goal_id) and ex._goals.get_goal(g.goal_id).state is GoalState.ACTIVE  # noqa: SLF001
    finally:
        teardown(kernel, rt, state, ex)


def test_goal_dependencies_readiness() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        dep = ex.create_goal(ctx, title="prereq", owner="user")
        g = ex.create_goal(ctx, title="dependent", owner="user", dependencies=(dep.goal_id,))
        assert not ex._goals.dependencies_ready(g)                       # noqa: SLF001 - prereq not done
        ex.verify_goal_completion(ctx, dep.goal_id, "done", 0.9) or ex._goals.transition(ctx, dep.goal_id, GoalState.COMPLETED)  # noqa: SLF001
        assert ex._goals.dependencies_ready(ex._goals.get_goal(g.goal_id))  # noqa: SLF001
    finally:
        teardown(kernel, rt, state, ex)


def test_completion_declared_on_evaluated_condition() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        g = ex.create_goal(ctx, title="release", owner="user", success_condition="shipped")
        # A confident proposal asserting the success condition completes the goal (ExL20).
        ex.govern(proposal("p", "shipped", 0.95, goal_id=g.goal_id), ctx)
        assert ex._goals.get_goal(g.goal_id).state is GoalState.COMPLETED  # noqa: SLF001
    finally:
        teardown(kernel, rt, state, ex)


def test_delegation_retains_ownership() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        g = ex.create_goal(ctx, title="parallel", owner="user")
        d = ex.delegate_goal(ctx, g.goal_id, "sub-agent")
        assert d.state is GoalState.DELEGATED and d.owner == "user"  # ExL2: ownership retained
    finally:
        teardown(kernel, rt, state, ex)


def test_abandonment_is_first_class_and_audited() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        g = ex.create_goal(ctx, title="impossible", owner="user")
        ex.abandon_goal(ctx, g.goal_id, "achievable set is empty")
        assert ex._goals.get_goal(g.goal_id).state is GoalState.ABANDONED  # noqa: SLF001
        # never a silent drop: an immutable ABANDON decision is on the record (ExL19)
        kinds = {o.payload["kind"] for o in decision_trail(state, subject=g.goal_id)}
        assert DecisionKind.ABANDON.value in kinds
    finally:
        teardown(kernel, rt, state, ex)


def test_bounded_working_set_suspends_overflow() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive(max_active_goals=3)
    try:
        for i in range(5):
            ex.create_goal(ctx, title=f"g{i}", owner="user", priority=0.5 + i * 0.05)
        assert len(ex._goals.active_goals()) <= 3  # noqa: SLF001 - bounded (ExL15); overflow suspended, not dropped
        assert len(ex._goals.portfolio()) == 5     # noqa: SLF001 - nothing lost
    finally:
        teardown(kernel, rt, state, ex)
