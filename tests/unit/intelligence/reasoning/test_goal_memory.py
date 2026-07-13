import pytest
from app.intelligence.reasoning.goal_memory.memory import GoalMemory
from app.intelligence.reasoning.models import GoalType, InferredGoal


@pytest.fixture
def memory():
    return GoalMemory()


def _make_goal(goal_type=GoalType.BUILD, message="build atlas"):
    return InferredGoal(
        goal_type=goal_type,
        primary_objective="Build Atlas",
        sub_objectives=["Design", "Implement"],
        success_criteria=["Done"],
        raw_message=message,
    )


class TestGoalMemory:
    def test_empty_store_returns_no_continuity(self, memory):
        goal = _make_goal()
        ctx = memory.get_active_context("u1", "c1", goal)
        assert ctx.goal_continuity is False
        assert ctx.prior_goals == []

    def test_store_and_retrieve_goal(self, memory):
        goal = _make_goal()
        memory.store("u1", "c1", goal, turn_index=0)
        ctx = memory.get_active_context("u1", "c1", goal)
        assert len(ctx.prior_goals) == 1

    def test_same_goal_type_produces_continuity(self, memory):
        goal1 = _make_goal(goal_type=GoalType.BUILD, message="build atlas")
        goal2 = _make_goal(goal_type=GoalType.BUILD, message="add auth to it")
        memory.store("u1", "c1", goal1, turn_index=0)
        ctx = memory.get_active_context("u1", "c1", goal2)
        assert ctx.goal_continuity is True

    def test_different_goal_type_no_continuity(self, memory):
        goal1 = _make_goal(goal_type=GoalType.BUILD)
        goal2 = _make_goal(goal_type=GoalType.RESEARCH, message="research databases")
        memory.store("u1", "c1", goal1, turn_index=0)
        ctx = memory.get_active_context("u1", "c1", goal2)
        assert ctx.goal_continuity is False

    def test_topic_change_signal_breaks_continuity(self, memory):
        goal1 = _make_goal(goal_type=GoalType.BUILD)
        goal2 = _make_goal(goal_type=GoalType.BUILD, message="never mind, let's talk about something else")
        memory.store("u1", "c1", goal1, turn_index=0)
        ctx = memory.get_active_context("u1", "c1", goal2)
        assert ctx.goal_continuity is False

    def test_non_persistent_goal_type_not_stored(self, memory):
        goal = _make_goal(goal_type=GoalType.UNKNOWN)
        memory.store("u1", "c1", goal, turn_index=0)
        ctx = memory.get_active_context("u1", "c1", goal)
        assert len(ctx.prior_goals) == 0

    def test_max_10_goals_kept(self, memory):
        for i in range(15):
            goal = _make_goal(goal_type=GoalType.BUILD, message=f"build step {i}")
            memory.store("u1", "c1", goal, turn_index=i)
        ctx = memory.get_active_context("u1", "c1", _make_goal())
        assert len(ctx.prior_goals) <= 10

    def test_different_conversations_isolated(self, memory):
        goal = _make_goal()
        memory.store("u1", "c1", goal, turn_index=0)
        ctx = memory.get_active_context("u1", "c2", goal)
        assert len(ctx.prior_goals) == 0

    def test_different_users_isolated(self, memory):
        goal = _make_goal()
        memory.store("u1", "c1", goal, turn_index=0)
        ctx = memory.get_active_context("u2", "c1", goal)
        assert len(ctx.prior_goals) == 0

    def test_clear_removes_goals(self, memory):
        goal = _make_goal()
        memory.store("u1", "c1", goal, turn_index=0)
        memory.clear("u1", "c1")
        ctx = memory.get_active_context("u1", "c1", goal)
        assert len(ctx.prior_goals) == 0
