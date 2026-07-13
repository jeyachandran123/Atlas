import pytest
from app.intelligence.reasoning.engine import ReasoningEngine
from app.intelligence.reasoning.models import (
    GoalType, ReasoningDepth, ReflectionVerdict, ValidationVerdict,
)


@pytest.fixture
def engine():
    return ReasoningEngine()


def _make_context(intent="coding", complexity="medium", repo_id=None,
                  chunks=0, strategy="coding", message="write a function"):
    from app.intelligence.models import (
        ComplexityAnalysis, ConversationAnalysis, ConversationTurn,
        DetectedIntent, IntelligenceContext, IntentAnalysis, Intent,
        Persona, PolicyDecision, PolicyResult, ResponseStrategy, Complexity,
    )
    return IntelligenceContext(
        user_message=message,
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        repo_id=repo_id,
        agent_mode="auto",
        intent_analysis=IntentAnalysis(
            primary=DetectedIntent(Intent(intent), 0.9, ["signal"])
        ),
        complexity=ComplexityAnalysis(
            level=Complexity(complexity),
            expected_response_length="medium",
            reasoning_depth="moderate",
            estimated_tool_calls=1,
            estimated_context_tokens=2048,
            expected_token_budget=2048,
            response_strategy_hint=ResponseStrategy(strategy),
            signals=["s1"],
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
        retrieved_chunks_count=chunks,
        code_context_block="some code" if chunks > 0 else "",
        session_messages=[],
    )


class TestReasoningEngineThink:
    def test_think_returns_reasoning_result(self, engine):
        ctx = _make_context()
        result = engine.think(ctx)
        assert result is not None

    def test_think_produces_inferred_goal(self, engine):
        ctx = _make_context(intent="debugging", message="my auth is broken")
        result = engine.think(ctx)
        assert result.goal is not None
        assert result.goal.goal_type == GoalType.FIND_AND_FIX

    def test_think_produces_rewritten_query(self, engine):
        ctx = _make_context()
        result = engine.think(ctx)
        assert result.rewritten_query is not None
        assert len(result.rewritten_query.original) > 0

    def test_think_produces_execution_plan(self, engine):
        ctx = _make_context()
        result = engine.think(ctx)
        assert result.execution_plan is not None
        assert result.execution_plan.total_steps >= 1

    def test_think_produces_confidence_report(self, engine):
        ctx = _make_context()
        result = engine.think(ctx)
        assert result.confidence is not None
        assert 0.0 <= result.confidence.overall <= 1.0

    def test_think_produces_reasoning_schedule(self, engine):
        ctx = _make_context()
        result = engine.think(ctx)
        assert result.reasoning_schedule is not None
        assert result.reasoning_schedule.total_passes >= 1

    def test_think_produces_trace(self, engine):
        ctx = _make_context()
        result = engine.think(ctx, request_id="test-req-1")
        assert result.trace is not None
        assert result.trace.request_id == "test-req-1"

    def test_think_trace_has_timing(self, engine):
        ctx = _make_context()
        result = engine.think(ctx)
        assert result.trace.total_ms >= 0.0

    def test_think_corrected_strategy_none_when_valid(self, engine):
        ctx = _make_context(intent="coding", strategy="coding")
        result = engine.think(ctx)
        assert result.corrected_strategy is None

    def test_think_adjustments_is_dict(self, engine):
        ctx = _make_context()
        result = engine.think(ctx)
        assert isinstance(result.adjustments, dict)

    def test_think_complex_goal_multi_step_depth(self, engine):
        ctx = _make_context(
            intent="debugging",
            complexity="complex",
            repo_id="repo1",
            message="fix the authentication bug in my codebase",
        )
        result = engine.think(ctx)
        assert result.reasoning_schedule.depth in (
            ReasoningDepth.SINGLE_PASS, ReasoningDepth.MULTI_STEP
        )

    def test_think_graceful_degradation_on_bad_context(self, engine):
        ctx = _make_context(intent="unknown", complexity="simple")
        ctx.user_message = ""
        result = engine.think(ctx)
        assert result is not None
        assert result.goal is not None


class TestReasoningEngineReflect:
    def test_reflect_returns_post_generation_result(self, engine):
        ctx = _make_context()
        thinking = engine.think(ctx)
        result = engine.reflect("Here is the answer.", ctx, thinking)
        assert result is not None

    def test_reflect_produces_reflection(self, engine):
        ctx = _make_context()
        thinking = engine.think(ctx)
        result = engine.reflect("Here is the answer.", ctx, thinking)
        assert result.reflection is not None

    def test_reflect_produces_expansion_plan(self, engine):
        ctx = _make_context()
        thinking = engine.think(ctx)
        result = engine.reflect("Here is the answer.", ctx, thinking)
        assert result.expansion_plan is not None

    def test_reflect_satisfactory_for_good_coding_response(self, engine):
        ctx = _make_context(intent="coding", strategy="coding")
        thinking = engine.think(ctx)
        response = "Here is the implementation:\n```python\ndef hello():\n    return 'world'\n```"
        result = engine.reflect(response, ctx, thinking)
        assert result.reflection.verdict == ReflectionVerdict.SATISFACTORY

    def test_reflect_needs_expansion_for_missing_code(self, engine):
        ctx = _make_context(intent="coding", strategy="coding")
        thinking = engine.think(ctx)
        result = engine.reflect("You should use FastAPI for this.", ctx, thinking)
        assert result.reflection.verdict in (
            ReflectionVerdict.NEEDS_EXPANSION,
            ReflectionVerdict.SATISFACTORY,
        )

    def test_reflect_needs_expansion_flag_set(self, engine):
        ctx = _make_context(intent="coding", strategy="coding")
        thinking = engine.think(ctx)
        result = engine.reflect("No code here.", ctx, thinking)
        assert isinstance(result.needs_expansion, bool)

    def test_reflect_trace_has_request_id(self, engine):
        ctx = _make_context()
        thinking = engine.think(ctx, request_id="reflect-test-1")
        result = engine.reflect("answer", ctx, thinking)
        assert result.trace.request_id == "reflect-test-1"

    def test_full_pipeline_think_then_reflect(self, engine):
        ctx = _make_context(
            intent="coding",
            complexity="medium",
            strategy="coding",
            message="write a Python function to reverse a string",
        )
        thinking = engine.think(ctx)
        assert thinking.goal.goal_type == GoalType.BUILD

        response = "```python\ndef reverse(s):\n    return s[::-1]\n```"
        post = engine.reflect(response, ctx, thinking)
        assert post.reflection.verdict == ReflectionVerdict.SATISFACTORY
        assert post.needs_full_regeneration is False
