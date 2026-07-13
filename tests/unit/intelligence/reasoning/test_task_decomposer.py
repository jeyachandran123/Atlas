import pytest
from app.intelligence.reasoning.decomposer.decomposer import TaskDecomposer
from app.intelligence.reasoning.models import GoalType, InferredGoal, TaskStatus


@pytest.fixture
def decomposer():
    return TaskDecomposer()


def _make_goal(goal_type=GoalType.FIND_AND_FIX, requires_tools=True):
    return InferredGoal(
        goal_type=goal_type,
        primary_objective="Fix the authentication bug",
        sub_objectives=["Find it", "Fix it"],
        success_criteria=["Fixed"],
        requires_repo=requires_tools,
        requires_tools=requires_tools,
        raw_message="fix auth bug",
    )


def _make_context(complexity="complex", repo_id="repo1"):
    from app.intelligence.models import (
        ComplexityAnalysis, ConversationAnalysis, ConversationTurn,
        DetectedIntent, IntelligenceContext, IntentAnalysis, Intent,
        Persona, PolicyDecision, PolicyResult, ResponseStrategy, Complexity,
    )
    return IntelligenceContext(
        user_message="fix auth bug",
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        repo_id=repo_id,
        agent_mode="auto",
        intent_analysis=IntentAnalysis(primary=DetectedIntent(Intent.DEBUGGING, 0.9, [])),
        complexity=ComplexityAnalysis(
            level=Complexity(complexity),
            expected_response_length="long",
            reasoning_depth="deep",
            estimated_tool_calls=3,
            estimated_context_tokens=4096,
            expected_token_budget=4096,
            response_strategy_hint=ResponseStrategy.TROUBLESHOOTING,
        ),
        conversation=ConversationAnalysis(
            turn_type=ConversationTurn.NEW_TOPIC,
            topic_summary="debugging",
            user_goal="fix bug",
            is_continuation=False,
            referenced_prior_turn=False,
        ),
        policy=PolicyResult(decision=PolicyDecision.ALLOW),
        persona=Persona.DEBUGGER,
        strategy=ResponseStrategy.TROUBLESHOOTING,
    )


class TestTaskDecomposer:
    def test_complex_goal_produces_multiple_tasks(self, decomposer):
        goal = _make_goal()
        ctx = _make_context(complexity="complex")
        result = decomposer.decompose(goal, ctx)
        assert result.total_tasks > 1

    def test_simple_goal_produces_single_task(self, decomposer):
        goal = _make_goal(requires_tools=False)
        ctx = _make_context(complexity="simple", repo_id=None)
        result = decomposer.decompose(goal, ctx)
        assert result.total_tasks == 1

    def test_tasks_have_unique_ids(self, decomposer):
        goal = _make_goal()
        ctx = _make_context(complexity="complex")
        result = decomposer.decompose(goal, ctx)
        ids = [t.task_id for t in result.tasks]
        assert len(ids) == len(set(ids))

    def test_first_task_has_no_dependencies(self, decomposer):
        goal = _make_goal()
        ctx = _make_context(complexity="complex")
        result = decomposer.decompose(goal, ctx)
        assert result.tasks[0].depends_on == []

    def test_subsequent_tasks_have_dependencies(self, decomposer):
        goal = _make_goal()
        ctx = _make_context(complexity="complex")
        result = decomposer.decompose(goal, ctx)
        if len(result.tasks) > 1:
            assert len(result.tasks[1].depends_on) > 0

    def test_all_tasks_start_as_pending(self, decomposer):
        goal = _make_goal()
        ctx = _make_context(complexity="complex")
        result = decomposer.decompose(goal, ctx)
        assert all(t.status == TaskStatus.PENDING for t in result.tasks)

    def test_ready_tasks_returns_first_task(self, decomposer):
        goal = _make_goal()
        ctx = _make_context(complexity="complex")
        result = decomposer.decompose(goal, ctx)
        ready = result.ready_tasks()
        assert len(ready) >= 1
        assert ready[0].task_id == result.tasks[0].task_id

    def test_requires_tools_set_for_tool_tasks(self, decomposer):
        goal = _make_goal(goal_type=GoalType.FIND_AND_FIX, requires_tools=True)
        ctx = _make_context(complexity="complex")
        result = decomposer.decompose(goal, ctx)
        assert result.requires_tools is True

    def test_decomposition_rationale_populated(self, decomposer):
        goal = _make_goal()
        ctx = _make_context(complexity="complex")
        result = decomposer.decompose(goal, ctx)
        assert len(result.decomposition_rationale) > 0

    def test_build_goal_decomposed_correctly(self, decomposer):
        goal = _make_goal(goal_type=GoalType.BUILD)
        ctx = _make_context(complexity="very_complex")
        result = decomposer.decompose(goal, ctx)
        assert result.total_tasks > 1
