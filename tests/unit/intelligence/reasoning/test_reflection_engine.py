import pytest
from app.intelligence.reasoning.reflection.engine import ReflectionEngine
from app.intelligence.reasoning.models import GoalType, InferredGoal, ReflectionVerdict


@pytest.fixture
def reflection_engine():
    return ReflectionEngine()


def _make_goal(goal_type=GoalType.BUILD):
    return InferredGoal(
        goal_type=goal_type,
        primary_objective="Build a REST API",
        sub_objectives=[
            "Understand requirements from context",
            "Design the implementation",
            "Write the complete implementation",
        ],
        success_criteria=["Implementation is complete"],
        raw_message="build a REST API",
    )


def _make_context(strategy="coding"):
    from app.intelligence.models import (
        ComplexityAnalysis, ConversationAnalysis, ConversationTurn,
        DetectedIntent, IntelligenceContext, IntentAnalysis, Intent,
        Persona, PolicyDecision, PolicyResult, ResponseStrategy, Complexity,
    )
    return IntelligenceContext(
        user_message="build a REST API",
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        repo_id=None,
        agent_mode="auto",
        intent_analysis=IntentAnalysis(primary=DetectedIntent(Intent.CODING, 0.9, [])),
        complexity=ComplexityAnalysis(
            level=Complexity.MEDIUM,
            expected_response_length="medium",
            reasoning_depth="moderate",
            estimated_tool_calls=0,
            estimated_context_tokens=2048,
            expected_token_budget=2048,
            response_strategy_hint=ResponseStrategy.CODING,
        ),
        conversation=ConversationAnalysis(
            turn_type=ConversationTurn.NEW_TOPIC,
            topic_summary="coding",
            user_goal="build api",
            is_continuation=False,
            referenced_prior_turn=False,
        ),
        policy=PolicyResult(decision=PolicyDecision.ALLOW),
        persona=Persona.SENIOR_ENGINEER,
        strategy=ResponseStrategy(strategy),
    )


class TestReflectionEngine:
    def test_satisfactory_for_complete_coding_response(self, reflection_engine):
        goal = _make_goal()
        ctx = _make_context(strategy="coding")
        response = "Here is the implementation:\n```python\ndef create_app():\n    pass\n```\nThis creates a FastAPI app."
        result = reflection_engine.reflect(response, goal, ctx)
        assert result.verdict == ReflectionVerdict.SATISFACTORY

    def test_needs_expansion_when_no_code_block(self, reflection_engine):
        goal = _make_goal()
        ctx = _make_context(strategy="coding")
        response = "You should create a FastAPI application with routes and models."
        result = reflection_engine.reflect(response, goal, ctx)
        assert result.verdict == ReflectionVerdict.NEEDS_EXPANSION

    def test_weak_sections_identified_for_missing_code(self, reflection_engine):
        goal = _make_goal()
        ctx = _make_context(strategy="coding")
        response = "Use FastAPI to build the API."
        result = reflection_engine.reflect(response, goal, ctx)
        section_ids = [s.section_id for s in result.weak_sections]
        assert "code" in section_ids

    def test_teaching_response_needs_example(self, reflection_engine):
        goal = _make_goal(goal_type=GoalType.EXPLAIN)
        ctx = _make_context(strategy="teaching")
        response = "Dependency injection is a design pattern where dependencies are provided externally."
        result = reflection_engine.reflect(response, goal, ctx)
        section_ids = [s.section_id for s in result.weak_sections]
        assert "example" in section_ids or "summary" in section_ids

    def test_strategy_mismatch_detected(self, reflection_engine):
        goal = _make_goal(goal_type=GoalType.FIND_AND_FIX)
        ctx = _make_context(strategy="teaching")
        response = "Let me teach you about authentication systems in detail."
        result = reflection_engine.reflect(response, goal, ctx)
        assert result.verdict == ReflectionVerdict.STRATEGY_MISMATCH
        assert result.alternative_strategy is not None

    def test_goal_achieved_true_for_satisfactory(self, reflection_engine):
        goal = _make_goal()
        ctx = _make_context(strategy="coding")
        response = "```python\ndef api():\n    pass\n```"
        result = reflection_engine.reflect(response, goal, ctx)
        if result.verdict == ReflectionVerdict.SATISFACTORY:
            assert result.goal_achieved is True

    def test_missed_objectives_list_returned(self, reflection_engine):
        goal = _make_goal()
        ctx = _make_context(strategy="coding")
        result = reflection_engine.reflect("short answer", goal, ctx)
        assert isinstance(result.missed_objectives, list)

    def test_reflection_notes_populated_on_issues(self, reflection_engine):
        goal = _make_goal()
        ctx = _make_context(strategy="coding")
        result = reflection_engine.reflect("no code here", goal, ctx)
        if result.verdict != ReflectionVerdict.SATISFACTORY:
            assert len(result.reflection_notes) > 0

    def test_comparison_response_needs_table(self, reflection_engine):
        goal = _make_goal(goal_type=GoalType.COMPARE)
        ctx = _make_context(strategy="comparison")
        response = "React and Vue are both JavaScript frameworks."
        result = reflection_engine.reflect(response, goal, ctx)
        section_ids = [s.section_id for s in result.weak_sections]
        assert "comparison" in section_ids or "summary" in section_ids

    def test_step_by_step_needs_numbered_steps(self, reflection_engine):
        goal = _make_goal(goal_type=GoalType.PLAN)
        ctx = _make_context(strategy="step_by_step")
        response = "First do this, then do that, finally finish."
        result = reflection_engine.reflect(response, goal, ctx)
        section_ids = [s.section_id for s in result.weak_sections]
        assert "steps" in section_ids
