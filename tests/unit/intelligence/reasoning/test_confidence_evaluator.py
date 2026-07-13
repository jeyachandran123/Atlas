import pytest
from app.intelligence.reasoning.confidence.evaluator import ConfidenceEvaluator
from app.intelligence.reasoning.models import ConfidenceLevel, GoalType, InferredGoal


@pytest.fixture
def evaluator():
    return ConfidenceEvaluator()


def _make_goal(goal_type=GoalType.BUILD, confidence=0.9, requires_tools=False):
    return InferredGoal(
        goal_type=goal_type,
        primary_objective="test",
        sub_objectives=[],
        success_criteria=[],
        requires_tools=requires_tools,
        confidence=confidence,
        raw_message="test",
    )


def _make_context(intent="coding", intent_conf=0.9, repo_id=None, chunks=0,
                  complexity="medium", tool_plan=None):
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
        repo_id=repo_id,
        agent_mode="auto",
        intent_analysis=IntentAnalysis(
            primary=DetectedIntent(Intent(intent), intent_conf, ["signal"])
        ),
        complexity=ComplexityAnalysis(
            level=Complexity(complexity),
            expected_response_length="medium",
            reasoning_depth="moderate",
            estimated_tool_calls=1,
            estimated_context_tokens=2048,
            expected_token_budget=2048,
            response_strategy_hint=ResponseStrategy.DIRECT_ANSWER,
            signals=["s1", "s2"],
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
        strategy=ResponseStrategy.CODING,
        retrieved_chunks_count=chunks,
        tool_plan=tool_plan,
    )


class TestConfidenceEvaluator:
    def test_returns_confidence_report(self, evaluator):
        goal = _make_goal()
        ctx = _make_context()
        report = evaluator.evaluate(goal, ctx)
        assert report is not None

    def test_scores_list_has_five_dimensions(self, evaluator):
        goal = _make_goal()
        ctx = _make_context()
        report = evaluator.evaluate(goal, ctx)
        assert len(report.scores) == 5

    def test_overall_score_between_0_and_1(self, evaluator):
        goal = _make_goal()
        ctx = _make_context()
        report = evaluator.evaluate(goal, ctx)
        assert 0.0 <= report.overall <= 1.0

    def test_high_confidence_intent_produces_high_intent_score(self, evaluator):
        goal = _make_goal()
        ctx = _make_context(intent_conf=0.95)
        report = evaluator.evaluate(goal, ctx)
        intent_score = report.get("intent")
        assert intent_score.level == ConfidenceLevel.HIGH

    def test_unknown_goal_type_penalises_goal_score(self, evaluator):
        goal = _make_goal(goal_type=GoalType.UNKNOWN, confidence=0.5)
        ctx = _make_context()
        report = evaluator.evaluate(goal, ctx)
        goal_score = report.get("goal")
        assert goal_score.score <= 0.20

    def test_no_repo_gives_high_repo_match(self, evaluator):
        goal = _make_goal()
        ctx = _make_context(repo_id=None)
        report = evaluator.evaluate(goal, ctx)
        repo_score = report.get("repo_match")
        assert repo_score.level == ConfidenceLevel.HIGH

    def test_repo_with_no_chunks_gives_very_low_repo_match(self, evaluator):
        goal = _make_goal()
        ctx = _make_context(repo_id="repo1", chunks=0)
        report = evaluator.evaluate(goal, ctx)
        repo_score = report.get("repo_match")
        assert repo_score.level == ConfidenceLevel.VERY_LOW

    def test_repo_with_chunks_improves_score(self, evaluator):
        goal = _make_goal()
        ctx_no_chunks = _make_context(repo_id="repo1", chunks=0)
        ctx_with_chunks = _make_context(repo_id="repo1", chunks=8)
        r1 = evaluator.evaluate(goal, ctx_no_chunks)
        r2 = evaluator.evaluate(goal, ctx_with_chunks)
        assert r2.get("repo_match").score > r1.get("repo_match").score

    def test_should_clarify_when_overall_very_low(self, evaluator):
        goal = _make_goal(goal_type=GoalType.UNKNOWN, confidence=0.1)
        ctx = _make_context(intent="unknown", intent_conf=0.1, repo_id="repo1", chunks=0)
        report = evaluator.evaluate(goal, ctx)
        if report.overall < 0.30:
            assert report.should_clarify is True

    def test_clarification_question_set_when_should_clarify(self, evaluator):
        goal = _make_goal(goal_type=GoalType.UNKNOWN, confidence=0.1)
        ctx = _make_context(intent="unknown", intent_conf=0.1, repo_id="repo1", chunks=0)
        report = evaluator.evaluate(goal, ctx)
        if report.should_clarify:
            assert len(report.clarification_question) > 0

    def test_should_retrieve_more_when_repo_empty(self, evaluator):
        goal = _make_goal()
        ctx = _make_context(repo_id="repo1", chunks=0)
        report = evaluator.evaluate(goal, ctx)
        assert report.should_retrieve_more is True
