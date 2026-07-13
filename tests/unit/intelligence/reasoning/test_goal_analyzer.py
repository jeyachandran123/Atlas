import pytest
from app.intelligence.reasoning.goal.analyzer import GoalAnalyzer
from app.intelligence.reasoning.models import GoalType, ActiveGoalContext


@pytest.fixture
def analyzer():
    return GoalAnalyzer()


def _make_context(intent="debugging", confidence=0.9, repo_id=None, session=None):
    from app.intelligence.models import (
        ComplexityAnalysis, ConversationAnalysis, ConversationTurn,
        DetectedIntent, IntelligenceContext, IntentAnalysis,
        Persona, PolicyDecision, PolicyResult, ResponseStrategy, Complexity,
    )
    return IntelligenceContext(
        user_message="test",
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        repo_id=repo_id,
        agent_mode="auto",
        intent_analysis=IntentAnalysis(primary=DetectedIntent(
            __import__("app.intelligence.models", fromlist=["Intent"]).Intent(intent),
            confidence, []
        )),
        complexity=ComplexityAnalysis(
            level=Complexity.MEDIUM,
            expected_response_length="medium",
            reasoning_depth="moderate",
            estimated_tool_calls=1,
            estimated_context_tokens=2048,
            expected_token_budget=2048,
            response_strategy_hint=ResponseStrategy.DIRECT_ANSWER,
        ),
        conversation=ConversationAnalysis(
            turn_type=ConversationTurn.NEW_TOPIC,
            topic_summary="test",
            user_goal="test",
            is_continuation=False,
            referenced_prior_turn=False,
        ),
        policy=PolicyResult(decision=PolicyDecision.ALLOW),
        persona=Persona.SENIOR_ENGINEER,
        strategy=ResponseStrategy.DIRECT_ANSWER,
        session_messages=session or [],
    )


def _no_active_goal():
    return ActiveGoalContext(current_goal=None, prior_goals=[], goal_continuity=False)


class TestGoalAnalyzer:
    def test_debugging_intent_maps_to_find_and_fix(self, analyzer):
        ctx = _make_context(intent="debugging")
        ctx.user_message = "my authentication is broken"
        result = analyzer.analyze(ctx.user_message, ctx, _no_active_goal())
        assert result.goal_type == GoalType.FIND_AND_FIX

    def test_coding_intent_maps_to_build(self, analyzer):
        ctx = _make_context(intent="coding")
        ctx.user_message = "create a login endpoint"
        result = analyzer.analyze(ctx.user_message, ctx, _no_active_goal())
        assert result.goal_type == GoalType.BUILD

    def test_refactoring_maps_to_improve(self, analyzer):
        ctx = _make_context(intent="refactoring")
        ctx.user_message = "refactor this service"
        result = analyzer.analyze(ctx.user_message, ctx, _no_active_goal())
        assert result.goal_type == GoalType.IMPROVE

    def test_sub_objectives_populated(self, analyzer):
        ctx = _make_context(intent="debugging")
        ctx.user_message = "fix the bug"
        result = analyzer.analyze(ctx.user_message, ctx, _no_active_goal())
        assert len(result.sub_objectives) > 0

    def test_success_criteria_populated(self, analyzer):
        ctx = _make_context(intent="coding")
        ctx.user_message = "build a REST API"
        result = analyzer.analyze(ctx.user_message, ctx, _no_active_goal())
        assert len(result.success_criteria) > 0

    def test_requires_repo_when_repo_id_set(self, analyzer):
        ctx = _make_context(intent="repository_question", repo_id="repo1")
        ctx.user_message = "find the auth module"
        result = analyzer.analyze(ctx.user_message, ctx, _no_active_goal())
        assert result.requires_repo is True

    def test_no_repo_required_without_repo_id(self, analyzer):
        ctx = _make_context(intent="learning", repo_id=None)
        ctx.user_message = "explain dependency injection"
        result = analyzer.analyze(ctx.user_message, ctx, _no_active_goal())
        assert result.requires_repo is False

    def test_confidence_is_set(self, analyzer):
        ctx = _make_context(intent="coding", confidence=0.8)
        ctx.user_message = "write a function"
        result = analyzer.analyze(ctx.user_message, ctx, _no_active_goal())
        assert 0.0 < result.confidence <= 1.0

    def test_raw_message_preserved(self, analyzer):
        ctx = _make_context(intent="coding")
        ctx.user_message = "build me something"
        result = analyzer.analyze(ctx.user_message, ctx, _no_active_goal())
        assert result.raw_message == "build me something"

    def test_goal_continuity_merges_sub_objectives(self, analyzer):
        from app.intelligence.reasoning.models import InferredGoal
        prior_goal = InferredGoal(
            goal_type=GoalType.BUILD,
            primary_objective="Build Atlas",
            sub_objectives=["Design the API"],
            success_criteria=[],
            raw_message="build atlas",
        )
        active = ActiveGoalContext(
            current_goal=prior_goal,
            prior_goals=[],
            goal_continuity=True,
        )
        ctx = _make_context(intent="coding")
        ctx.user_message = "add authentication to it"
        result = analyzer.analyze(ctx.user_message, ctx, active)
        assert len(result.sub_objectives) > 0
