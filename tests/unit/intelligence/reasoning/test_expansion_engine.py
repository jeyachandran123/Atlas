import pytest
from app.intelligence.reasoning.expansion.engine import ExpansionEngine
from app.intelligence.reasoning.models import (
    ReflectionResult, ReflectionVerdict, WeakSection,
)


@pytest.fixture
def expansion_engine():
    return ExpansionEngine()


def _make_context():
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
        strategy=ResponseStrategy.CODING,
    )


def _reflection(verdict, weak_sections=None, missed=None):
    return ReflectionResult(
        verdict=verdict,
        goal_achieved=verdict == ReflectionVerdict.SATISFACTORY,
        missed_objectives=missed or [],
        weak_sections=weak_sections or [],
        alternative_strategy=None,
    )


class TestExpansionEngine:
    def test_satisfactory_produces_no_targets(self, expansion_engine):
        reflection = _reflection(ReflectionVerdict.SATISFACTORY)
        ctx = _make_context()
        plan = expansion_engine.plan_expansion("good response", reflection, ctx)
        assert len(plan.targets) == 0
        assert plan.full_regeneration_needed is False

    def test_missed_goal_triggers_full_regeneration(self, expansion_engine):
        reflection = _reflection(ReflectionVerdict.MISSED_GOAL)
        ctx = _make_context()
        plan = expansion_engine.plan_expansion("bad response", reflection, ctx)
        assert plan.full_regeneration_needed is True

    def test_strategy_mismatch_triggers_full_regeneration(self, expansion_engine):
        reflection = _reflection(ReflectionVerdict.STRATEGY_MISMATCH)
        ctx = _make_context()
        plan = expansion_engine.plan_expansion("wrong strategy response", reflection, ctx)
        assert plan.full_regeneration_needed is True

    def test_needs_expansion_produces_targets(self, expansion_engine):
        weak = [WeakSection(
            section_id="code",
            description="Code block",
            weakness_reason="No code found",
            expansion_hint="Add code",
        )]
        reflection = _reflection(ReflectionVerdict.NEEDS_EXPANSION, weak_sections=weak)
        ctx = _make_context()
        plan = expansion_engine.plan_expansion("no code here", reflection, ctx)
        assert len(plan.targets) == 1

    def test_target_section_id_matches_weak_section(self, expansion_engine):
        weak = [WeakSection(
            section_id="example",
            description="Examples",
            weakness_reason="No examples",
            expansion_hint="Add examples",
        )]
        reflection = _reflection(ReflectionVerdict.NEEDS_EXPANSION, weak_sections=weak)
        ctx = _make_context()
        plan = expansion_engine.plan_expansion("response without examples", reflection, ctx)
        assert plan.targets[0].section_id == "example"

    def test_expansion_instruction_populated(self, expansion_engine):
        weak = [WeakSection(
            section_id="code",
            description="Code",
            weakness_reason="Missing",
            expansion_hint="Add code",
        )]
        reflection = _reflection(ReflectionVerdict.NEEDS_EXPANSION, weak_sections=weak)
        ctx = _make_context()
        plan = expansion_engine.plan_expansion("response", reflection, ctx)
        assert len(plan.targets[0].expansion_instruction) > 0

    def test_priority_assigned_to_targets(self, expansion_engine):
        weak = [
            WeakSection("code", "Code", "Missing", "Add code"),
            WeakSection("example", "Example", "Missing", "Add example"),
        ]
        reflection = _reflection(ReflectionVerdict.NEEDS_EXPANSION, weak_sections=weak)
        ctx = _make_context()
        plan = expansion_engine.plan_expansion("response", reflection, ctx)
        priorities = [t.priority for t in plan.targets]
        assert sorted(priorities) == priorities

    def test_highest_priority_returns_first_target(self, expansion_engine):
        weak = [
            WeakSection("code", "Code", "Missing", "Add code"),
            WeakSection("example", "Example", "Missing", "Add example"),
        ]
        reflection = _reflection(ReflectionVerdict.NEEDS_EXPANSION, weak_sections=weak)
        ctx = _make_context()
        plan = expansion_engine.plan_expansion("response", reflection, ctx)
        hp = plan.highest_priority()
        assert hp is not None
        assert hp.priority == min(t.priority for t in plan.targets)

    def test_rationale_populated(self, expansion_engine):
        weak = [WeakSection("summary", "Summary", "Missing", "Add summary")]
        reflection = _reflection(ReflectionVerdict.NEEDS_EXPANSION, weak_sections=weak)
        ctx = _make_context()
        plan = expansion_engine.plan_expansion("response", reflection, ctx)
        assert len(plan.rationale) > 0

    def test_current_content_extracted_from_response(self, expansion_engine):
        weak = [WeakSection("code", "Code", "Missing", "Add code")]
        reflection = _reflection(ReflectionVerdict.NEEDS_EXPANSION, weak_sections=weak)
        ctx = _make_context()
        response = "This is a long response " * 20
        plan = expansion_engine.plan_expansion(response, reflection, ctx)
        assert len(plan.targets[0].current_content) > 0
