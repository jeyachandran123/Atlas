import pytest
from app.intelligence.reasoning.validation.validator import StrategyValidator
from app.intelligence.reasoning.models import GoalType, InferredGoal, ValidationVerdict


@pytest.fixture
def validator():
    return StrategyValidator()


def _make_goal(goal_type=GoalType.BUILD):
    return InferredGoal(
        goal_type=goal_type,
        primary_objective="test",
        sub_objectives=[],
        success_criteria=[],
        raw_message="test",
    )


def _make_context(strategy="coding"):
    from app.intelligence.models import (
        ComplexityAnalysis, ConversationAnalysis, ConversationTurn,
        DetectedIntent, IntelligenceContext, IntentAnalysis, Intent,
        Persona, PolicyDecision, PolicyResult, ResponseStrategy, Complexity,
    )
    return IntelligenceContext(
        user_message="test",
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
            topic_summary="test",
            user_goal="test",
            is_continuation=False,
            referenced_prior_turn=False,
        ),
        policy=PolicyResult(decision=PolicyDecision.ALLOW),
        persona=Persona.SENIOR_ENGINEER,
        strategy=ResponseStrategy(strategy),
    )


class TestStrategyValidator:
    def test_valid_when_strategy_matches_goal(self, validator):
        goal = _make_goal(GoalType.BUILD)
        ctx = _make_context(strategy="coding")
        result = validator.validate(goal, ctx)
        assert result.verdict == ValidationVerdict.VALID

    def test_valid_for_find_and_fix_with_troubleshooting(self, validator):
        goal = _make_goal(GoalType.FIND_AND_FIX)
        ctx = _make_context(strategy="troubleshooting")
        result = validator.validate(goal, ctx)
        assert result.verdict == ValidationVerdict.VALID

    def test_mismatch_for_teaching_when_coding_needed(self, validator):
        goal = _make_goal(GoalType.BUILD)
        ctx = _make_context(strategy="direct_answer")
        result = validator.validate(goal, ctx)
        assert result.verdict in (ValidationVerdict.MISMATCH, ValidationVerdict.AMBIGUOUS)

    def test_severe_mismatch_provides_corrected_strategy(self, validator):
        goal = _make_goal(GoalType.FIND_AND_FIX)
        ctx = _make_context(strategy="teaching")
        result = validator.validate(goal, ctx)
        if result.verdict == ValidationVerdict.MISMATCH:
            assert result.corrected_strategy is not None

    def test_mismatch_reason_populated_on_mismatch(self, validator):
        goal = _make_goal(GoalType.DECIDE)
        ctx = _make_context(strategy="coding")
        result = validator.validate(goal, ctx)
        if result.verdict in (ValidationVerdict.MISMATCH, ValidationVerdict.AMBIGUOUS):
            assert len(result.mismatch_reason) > 0

    def test_selected_strategy_preserved_in_result(self, validator):
        goal = _make_goal(GoalType.BUILD)
        ctx = _make_context(strategy="coding")
        result = validator.validate(goal, ctx)
        assert result.selected_strategy == "coding"

    def test_expected_strategy_set_in_result(self, validator):
        goal = _make_goal(GoalType.BUILD)
        ctx = _make_context(strategy="coding")
        result = validator.validate(goal, ctx)
        assert len(result.expected_strategy) > 0

    def test_valid_for_understand_with_teaching(self, validator):
        goal = _make_goal(GoalType.UNDERSTAND)
        ctx = _make_context(strategy="teaching")
        result = validator.validate(goal, ctx)
        assert result.verdict == ValidationVerdict.VALID

    def test_valid_for_compare_with_comparison(self, validator):
        goal = _make_goal(GoalType.COMPARE)
        ctx = _make_context(strategy="comparison")
        result = validator.validate(goal, ctx)
        assert result.verdict == ValidationVerdict.VALID

    def test_valid_for_plan_with_step_by_step(self, validator):
        goal = _make_goal(GoalType.PLAN)
        ctx = _make_context(strategy="step_by_step")
        result = validator.validate(goal, ctx)
        assert result.verdict == ValidationVerdict.VALID
