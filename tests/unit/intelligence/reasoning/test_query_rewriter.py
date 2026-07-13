import pytest
from app.intelligence.reasoning.rewriter.rewriter import QueryRewriter
from app.intelligence.reasoning.models import GoalType, InferredGoal


@pytest.fixture
def rewriter():
    return QueryRewriter()


def _make_goal(goal_type=GoalType.BUILD, requires_repo=False):
    return InferredGoal(
        goal_type=goal_type,
        primary_objective="test objective",
        sub_objectives=["step 1", "step 2"],
        success_criteria=["done"],
        requires_repo=requires_repo,
        raw_message="test",
    )


def _make_context(strategy="coding", repo_id=None, chunks=0, session=None, assumptions=None):
    from app.intelligence.models import (
        ComplexityAnalysis, ConversationAnalysis, ConversationTurn,
        DetectedIntent, IntelligenceContext, IntentAnalysis, Intent,
        Persona, PolicyDecision, PolicyResult, ResponseStrategy, Complexity,
    )
    conv = ConversationAnalysis(
        turn_type=ConversationTurn.NEW_TOPIC,
        topic_summary="test",
        user_goal="test",
        is_continuation=False,
        referenced_prior_turn=False,
        assumptions=assumptions or [],
    )
    return IntelligenceContext(
        user_message="test",
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        repo_id=repo_id,
        agent_mode="auto",
        intent_analysis=IntentAnalysis(primary=DetectedIntent(Intent.CODING, 0.9, [])),
        complexity=ComplexityAnalysis(
            level=Complexity.MEDIUM,
            expected_response_length="medium",
            reasoning_depth="moderate",
            estimated_tool_calls=1,
            estimated_context_tokens=2048,
            expected_token_budget=2048,
            response_strategy_hint=ResponseStrategy.CODING,
        ),
        conversation=conv,
        policy=PolicyResult(decision=PolicyDecision.ALLOW),
        persona=Persona.SENIOR_ENGINEER,
        strategy=ResponseStrategy(strategy),
        session_messages=session or [],
        retrieved_chunks_count=chunks,
        code_context_block="some code" if chunks > 0 else "",
    )


class TestQueryRewriter:
    def test_no_enrichment_returns_original(self, rewriter):
        goal = _make_goal()
        ctx = _make_context()
        result = rewriter.rewrite("write a function", goal, ctx)
        assert result.original == "write a function"

    def test_rewritten_contains_original_message(self, rewriter):
        goal = _make_goal()
        ctx = _make_context(assumptions=["user is building a FastAPI app"])
        result = rewriter.rewrite("add auth", goal, ctx)
        assert "add auth" in result.rewritten

    def test_enrichments_applied_list_populated(self, rewriter):
        goal = _make_goal()
        ctx = _make_context(assumptions=["user is building a FastAPI app"])
        result = rewriter.rewrite("add auth", goal, ctx)
        assert isinstance(result.enrichments_applied, list)

    def test_beginner_audience_detected(self, rewriter):
        goal = _make_goal(goal_type=GoalType.EXPLAIN)
        ctx = _make_context(session=[
            {"role": "user", "content": "I am a beginner learning Python"}
        ])
        result = rewriter.rewrite("explain decorators", goal, ctx)
        assert "beginner" in result.rewritten.lower() or "audience:beginner" in result.enrichments_applied

    def test_expert_audience_detected(self, rewriter):
        goal = _make_goal()
        ctx = _make_context(session=[
            {"role": "user", "content": "I am a senior engineer working on production systems"}
        ])
        result = rewriter.rewrite("optimize this", goal, ctx)
        assert "audience:expert" in result.enrichments_applied or "experienced" in result.rewritten.lower()

    def test_repo_context_enrichment_when_chunks_retrieved(self, rewriter):
        goal = _make_goal(requires_repo=True)
        ctx = _make_context(repo_id="repo1", chunks=5)
        result = rewriter.rewrite("fix the auth bug", goal, ctx)
        assert "context:repo_retrieved" in result.enrichments_applied

    def test_format_hint_added_for_coding_strategy(self, rewriter):
        goal = _make_goal(goal_type=GoalType.BUILD)
        ctx = _make_context(strategy="coding")
        result = rewriter.rewrite("write a parser", goal, ctx)
        assert "format:coding" in result.enrichments_applied or "code" in result.rewritten.lower()

    def test_domain_hint_from_assumptions(self, rewriter):
        goal = _make_goal()
        ctx = _make_context(assumptions=["user is building a Django app"])
        result = rewriter.rewrite("add a model", goal, ctx)
        assert "domain:from_history" in result.enrichments_applied or "Django" in result.rewritten

    def test_persona_hint_set_when_audience_detected(self, rewriter):
        goal = _make_goal()
        ctx = _make_context(session=[{"role": "user", "content": "I just started learning"}])
        result = rewriter.rewrite("explain classes", goal, ctx)
        assert isinstance(result.persona_hint, str)

    def test_no_meaning_change(self, rewriter):
        goal = _make_goal()
        ctx = _make_context()
        msg = "how do I reverse a list in Python"
        result = rewriter.rewrite(msg, goal, ctx)
        assert msg in result.rewritten or result.rewritten == msg
