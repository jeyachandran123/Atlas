import pytest
from app.intelligence.reasoning.multi_step.controller import MultiStepReasoningController
from app.intelligence.reasoning.models import (
    ExecutionMode, ExecutionPlan, ExecutionStep,
    GoalType, InferredGoal, ReasoningDepth,
)


@pytest.fixture
def controller():
    return MultiStepReasoningController()


def _make_goal(goal_type=GoalType.BUILD):
    return InferredGoal(
        goal_type=goal_type,
        primary_objective="test",
        sub_objectives=[],
        success_criteria=[],
        raw_message="test",
    )


def _make_plan(depth=ReasoningDepth.SINGLE_PASS, tool_calls=0, needs_retrieval=False):
    step = ExecutionStep(
        step_id="s1",
        task_ids=["t1"],
        mode=ExecutionMode.SEQUENTIAL,
        needs_retrieval=needs_retrieval,
    )
    return ExecutionPlan(
        steps=[step],
        total_steps=1,
        has_parallel_steps=False,
        reasoning_depth=depth,
        estimated_tool_calls=tool_calls,
    )


class TestMultiStepReasoningController:
    def test_simple_complexity_produces_single_pass(self, controller):
        goal = _make_goal(GoalType.UNDERSTAND)
        plan = _make_plan(ReasoningDepth.SINGLE_PASS)
        schedule = controller.schedule(goal, plan, "simple")
        assert schedule.total_passes == 1
        assert schedule.depth == ReasoningDepth.SINGLE_PASS

    def test_complex_goal_type_forces_multi_step(self, controller):
        goal = _make_goal(GoalType.FIND_AND_FIX)
        plan = _make_plan(ReasoningDepth.MULTI_STEP, tool_calls=2)
        schedule = controller.schedule(goal, plan, "complex")
        assert schedule.total_passes >= 2
        assert schedule.depth == ReasoningDepth.MULTI_STEP

    def test_build_goal_forces_at_least_2_passes(self, controller):
        goal = _make_goal(GoalType.BUILD)
        plan = _make_plan(ReasoningDepth.SINGLE_PASS)
        schedule = controller.schedule(goal, plan, "simple")
        assert schedule.total_passes >= 2

    def test_final_pass_is_marked_final(self, controller):
        goal = _make_goal(GoalType.FIND_AND_FIX)
        plan = _make_plan(ReasoningDepth.MULTI_STEP, tool_calls=2)
        schedule = controller.schedule(goal, plan, "complex")
        assert schedule.passes[-1].is_final is True

    def test_first_pass_is_not_final_in_multi_step(self, controller):
        goal = _make_goal(GoalType.BUILD)
        plan = _make_plan(ReasoningDepth.MULTI_STEP, tool_calls=2)
        schedule = controller.schedule(goal, plan, "complex")
        if schedule.total_passes > 1:
            assert schedule.passes[0].is_final is False

    def test_single_pass_is_final(self, controller):
        goal = _make_goal(GoalType.UNDERSTAND)
        plan = _make_plan(ReasoningDepth.SINGLE_PASS)
        schedule = controller.schedule(goal, plan, "simple")
        assert schedule.passes[0].is_final is True

    def test_very_complex_allows_up_to_4_passes(self, controller):
        goal = _make_goal(GoalType.FIND_AND_FIX)
        plan = _make_plan(ReasoningDepth.MULTI_STEP, tool_calls=4)
        schedule = controller.schedule(goal, plan, "very_complex")
        assert schedule.total_passes <= 4

    def test_rationale_populated(self, controller):
        goal = _make_goal(GoalType.BUILD)
        plan = _make_plan(ReasoningDepth.MULTI_STEP)
        schedule = controller.schedule(goal, plan, "complex")
        assert len(schedule.rationale) > 0

    def test_pass_numbers_are_sequential(self, controller):
        goal = _make_goal(GoalType.FIND_AND_FIX)
        plan = _make_plan(ReasoningDepth.MULTI_STEP, tool_calls=3)
        schedule = controller.schedule(goal, plan, "complex")
        for i, p in enumerate(schedule.passes, start=1):
            assert p.pass_number == i

    def test_single_pass_purpose_is_direct_response(self, controller):
        goal = _make_goal(GoalType.UNDERSTAND)
        plan = _make_plan(ReasoningDepth.SINGLE_PASS)
        schedule = controller.schedule(goal, plan, "simple")
        assert schedule.passes[0].purpose == "direct_response"
