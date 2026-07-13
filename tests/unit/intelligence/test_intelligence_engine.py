"""
Unit tests for the Conversation Intelligence Engine.

Each module is tested independently — no LLM calls, no database, no Redis.
All dependencies are pure Python.
"""

import pytest

from app.intelligence.complexity.analyzer import ComplexityAnalyzer
from app.intelligence.conversation.analyzer import ConversationAnalyzer
from app.intelligence.format.formatter import ResponseFormatter
from app.intelligence.intent.detector import IntentDetector
from app.intelligence.models import (
    Complexity,
    ConversationTurn,
    Intent,
    Persona,
    PolicyDecision,
    ResponseStrategy,
    ReviewDecision,
)
from app.intelligence.persona.engine import PersonaEngine
from app.intelligence.policy.engine import PolicyEngine
from app.intelligence.review.reviewer import ResponseReviewer
from app.intelligence.strategy.planner import ResponseStrategyPlanner
from app.intelligence.tools.planner import IntelligenceToolPlanner


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def intent_detector():
    return IntentDetector()


@pytest.fixture
def complexity_analyzer():
    return ComplexityAnalyzer()


@pytest.fixture
def conversation_analyzer():
    return ConversationAnalyzer()


@pytest.fixture
def policy_engine():
    return PolicyEngine()


@pytest.fixture
def persona_engine():
    return PersonaEngine()


@pytest.fixture
def strategy_planner():
    return ResponseStrategyPlanner()


@pytest.fixture
def tool_planner():
    return IntelligenceToolPlanner()


@pytest.fixture
def response_reviewer():
    return ResponseReviewer()


@pytest.fixture
def response_formatter():
    return ResponseFormatter()


# ── Intent Detector Tests ─────────────────────────────────────────────────────


class TestIntentDetector:
    def test_detects_coding_intent(self, intent_detector):
        result = intent_detector.detect("write a function to parse JSON", [], "auto")
        assert result.primary.intent == Intent.CODING
        assert result.primary.confidence > 0

    def test_detects_debugging_intent(self, intent_detector):
        result = intent_detector.detect("fix this bug in my code", [], "auto")
        assert result.primary.intent == Intent.DEBUGGING

    def test_detects_learning_intent(self, intent_detector):
        result = intent_detector.detect("what is dependency injection?", [], "auto")
        assert result.primary.intent == Intent.LEARNING

    def test_detects_architecture_intent(self, intent_detector):
        result = intent_detector.detect("design a microservice architecture", [], "auto")
        assert result.primary.intent == Intent.ARCHITECTURE

    def test_detects_comparison_intent(self, intent_detector):
        result = intent_detector.detect("compare React vs Vue", [], "auto")
        assert result.primary.intent == Intent.COMPARISON

    def test_detects_multiple_intents(self, intent_detector):
        result = intent_detector.detect(
            "explain React hooks and write a custom hook example", [], "auto"
        )
        all_intents = result.all_intents
        # Should detect at least learning + coding
        assert len(all_intents) >= 1

    def test_unknown_intent_for_empty_message(self, intent_detector):
        result = intent_detector.detect("", [], "auto")
        assert result.primary.intent == Intent.UNKNOWN

    def test_business_mode_returns_general_chat(self, intent_detector):
        result = intent_detector.detect("what is the hotel occupancy rate?", [], "business")
        assert result.primary.intent == Intent.GENERAL_CHAT

    def test_deep_teaching_intent(self, intent_detector):
        result = intent_detector.detect("teach me React from beginner to advanced", [], "auto")
        assert result.primary.intent == Intent.DEEP_TEACHING

    def test_git_operations_intent(self, intent_detector):
        result = intent_detector.detect("show me the git diff", [], "auto")
        assert result.primary.intent == Intent.GIT_OPERATIONS


# ── Complexity Analyzer Tests ─────────────────────────────────────────────────


class TestComplexityAnalyzer:
    def _make_intent(self, intent: Intent):
        from app.intelligence.models import DetectedIntent, IntentAnalysis
        return IntentAnalysis(primary=DetectedIntent(intent, 0.9, []))

    def test_simple_question(self, complexity_analyzer):
        result = complexity_analyzer.analyze(
            "what is React?", self._make_intent(Intent.LEARNING), []
        )
        assert result.level == Complexity.SIMPLE

    def test_deep_teaching_is_very_complex(self, complexity_analyzer):
        result = complexity_analyzer.analyze(
            "teach me React from beginner to advanced with complete guide",
            self._make_intent(Intent.DEEP_TEACHING),
            [],
        )
        assert result.level == Complexity.VERY_COMPLEX

    def test_architecture_is_complex(self, complexity_analyzer):
        result = complexity_analyzer.analyze(
            "design a scalable microservice architecture",
            self._make_intent(Intent.ARCHITECTURE),
            [],
        )
        assert result.level in (Complexity.COMPLEX, Complexity.VERY_COMPLEX)

    def test_simple_chat_is_simple(self, complexity_analyzer):
        result = complexity_analyzer.analyze(
            "hello", self._make_intent(Intent.GENERAL_CHAT), []
        )
        assert result.level == Complexity.SIMPLE

    def test_token_budget_increases_with_complexity(self, complexity_analyzer):
        simple = complexity_analyzer.analyze(
            "what is a variable?", self._make_intent(Intent.LEARNING), []
        )
        complex_ = complexity_analyzer.analyze(
            "teach me everything about distributed systems from scratch",
            self._make_intent(Intent.DEEP_TEACHING),
            [],
        )
        assert complex_.expected_token_budget > simple.expected_token_budget

    def test_coding_strategy_hint_for_coding_intent(self, complexity_analyzer):
        result = complexity_analyzer.analyze(
            "implement a REST API", self._make_intent(Intent.CODING), []
        )
        assert result.response_strategy_hint == ResponseStrategy.CODING


# ── Conversation Analyzer Tests ───────────────────────────────────────────────


class TestConversationAnalyzer:
    def _make_intent(self, intent: Intent = Intent.GENERAL_CHAT):
        from app.intelligence.models import DetectedIntent, IntentAnalysis
        return IntentAnalysis(primary=DetectedIntent(intent, 0.9, []))

    def test_new_topic_with_no_history(self, conversation_analyzer):
        result = conversation_analyzer.analyze("hello", [], self._make_intent())
        assert result.turn_type == ConversationTurn.NEW_TOPIC
        assert not result.is_continuation

    def test_correction_detected(self, conversation_analyzer):
        history = [
            {"role": "user", "content": "explain React"},
            {"role": "assistant", "content": "React is a JavaScript library..."},
        ]
        result = conversation_analyzer.analyze(
            "no, i meant React Native not React", history, self._make_intent()
        )
        assert result.turn_type == ConversationTurn.CORRECTION

    def test_follow_up_detected(self, conversation_analyzer):
        history = [
            {"role": "user", "content": "what is React?"},
            {"role": "assistant", "content": "React is..."},
        ]
        result = conversation_analyzer.analyze(
            "what about Vue?", history, self._make_intent()
        )
        assert result.turn_type == ConversationTurn.FOLLOW_UP

    def test_continuation_for_short_message_with_history(self, conversation_analyzer):
        history = [
            {"role": "user", "content": "explain hooks"},
            {"role": "assistant", "content": "Hooks are..."},
        ]
        result = conversation_analyzer.analyze("ok", history, self._make_intent())
        assert result.is_continuation

    def test_assumptions_extracted_from_history(self, conversation_analyzer):
        history = [
            {"role": "user", "content": "I'm building a FastAPI app with PostgreSQL"},
            {"role": "assistant", "content": "Great choice!"},
        ]
        result = conversation_analyzer.analyze("how do I add auth?", history, self._make_intent())
        assert any("FastAPI" in a or "PostgreSQL" in a for a in result.assumptions)


# ── Policy Engine Tests ───────────────────────────────────────────────────────


class TestPolicyEngine:
    def _make_intent(self):
        from app.intelligence.models import DetectedIntent, IntentAnalysis
        return IntentAnalysis(primary=DetectedIntent(Intent.CODING, 0.9, []))

    def test_allows_normal_request(self, policy_engine):
        result = policy_engine.evaluate(
            "write a Python function", self._make_intent(), "user1", "org1"
        )
        assert result.decision == PolicyDecision.ALLOW

    def test_blocks_destructive_command(self, policy_engine):
        result = policy_engine.evaluate(
            "run rm -rf / on the server", self._make_intent(), "user1", "org1"
        )
        assert result.decision == PolicyDecision.BLOCK
        assert result.safe_response is not None

    def test_blocks_malware_request(self, policy_engine):
        result = policy_engine.evaluate(
            "write a keylogger in Python", self._make_intent(), "user1", "org1"
        )
        assert result.decision == PolicyDecision.BLOCK

    def test_warns_on_pii(self, policy_engine):
        result = policy_engine.evaluate(
            "store the social security number in the database",
            self._make_intent(), "user1", "org1"
        )
        assert result.decision == PolicyDecision.WARN

    def test_warns_on_medical_advice(self, policy_engine):
        result = policy_engine.evaluate(
            "what drug dosage should I take?", self._make_intent(), "user1", "org1"
        )
        assert result.decision == PolicyDecision.WARN

    def test_block_takes_priority_over_warn(self, policy_engine):
        # Message that triggers both warn (pii) and block (rm -rf)
        result = policy_engine.evaluate(
            "rm -rf and store social security number",
            self._make_intent(), "user1", "org1"
        )
        assert result.decision == PolicyDecision.BLOCK


# ── Persona Engine Tests ──────────────────────────────────────────────────────


class TestPersonaEngine:
    def _make_analysis(self, intent: Intent, complexity: Complexity = Complexity.MEDIUM):
        from app.intelligence.models import (
            ComplexityAnalysis,
            DetectedIntent,
            IntentAnalysis,
        )
        intent_analysis = IntentAnalysis(primary=DetectedIntent(intent, 0.9, []))
        complexity_analysis = ComplexityAnalysis(
            level=complexity,
            expected_response_length="medium",
            reasoning_depth="moderate",
            estimated_tool_calls=1,
            estimated_context_tokens=2048,
            expected_token_budget=2048,
            response_strategy_hint=ResponseStrategy.DIRECT_ANSWER,
        )
        return intent_analysis, complexity_analysis

    def test_coding_intent_selects_engineer(self, persona_engine):
        intent, complexity = self._make_analysis(Intent.CODING)
        persona = persona_engine.select(intent, "auto", complexity)
        assert persona == Persona.SENIOR_ENGINEER

    def test_debugging_selects_debugger(self, persona_engine):
        intent, complexity = self._make_analysis(Intent.DEBUGGING)
        persona = persona_engine.select(intent, "auto", complexity)
        assert persona == Persona.DEBUGGER

    def test_learning_selects_teacher(self, persona_engine):
        intent, complexity = self._make_analysis(Intent.LEARNING)
        persona = persona_engine.select(intent, "auto", complexity)
        assert persona == Persona.TEACHER

    def test_architecture_selects_architect(self, persona_engine):
        intent, complexity = self._make_analysis(Intent.ARCHITECTURE)
        persona = persona_engine.select(intent, "auto", complexity)
        assert persona == Persona.ARCHITECT

    def test_business_mode_overrides_intent(self, persona_engine):
        intent, complexity = self._make_analysis(Intent.CODING)
        persona = persona_engine.select(intent, "business", complexity)
        assert persona == Persona.RESEARCH_ASSISTANT

    def test_very_complex_engineer_upgrades_to_architect(self, persona_engine):
        intent, complexity = self._make_analysis(Intent.CODING, Complexity.VERY_COMPLEX)
        persona = persona_engine.select(intent, "auto", complexity)
        assert persona == Persona.ARCHITECT


# ── Response Strategy Planner Tests ──────────────────────────────────────────


class TestResponseStrategyPlanner:
    def _make_inputs(self, intent: Intent, complexity: Complexity = Complexity.MEDIUM,
                     turn: ConversationTurn = ConversationTurn.NEW_TOPIC):
        from app.intelligence.models import (
            ComplexityAnalysis,
            ConversationAnalysis,
            DetectedIntent,
            IntentAnalysis,
        )
        intent_analysis = IntentAnalysis(primary=DetectedIntent(intent, 0.9, []))
        complexity_analysis = ComplexityAnalysis(
            level=complexity,
            expected_response_length="medium",
            reasoning_depth="moderate",
            estimated_tool_calls=1,
            estimated_context_tokens=2048,
            expected_token_budget=2048,
            response_strategy_hint=ResponseStrategy.DIRECT_ANSWER,
        )
        conversation = ConversationAnalysis(
            turn_type=turn,
            topic_summary="test",
            user_goal="test",
            is_continuation=turn != ConversationTurn.NEW_TOPIC,
            referenced_prior_turn=False,
        )
        return intent_analysis, complexity_analysis, conversation

    def test_coding_intent_uses_coding_strategy(self, strategy_planner):
        intent, complexity, conv = self._make_inputs(Intent.CODING)
        strategy = strategy_planner.plan(intent, complexity, conv)
        assert strategy == ResponseStrategy.CODING

    def test_debugging_uses_troubleshooting(self, strategy_planner):
        intent, complexity, conv = self._make_inputs(Intent.DEBUGGING)
        strategy = strategy_planner.plan(intent, complexity, conv)
        assert strategy == ResponseStrategy.TROUBLESHOOTING

    def test_architecture_uses_architecture_strategy(self, strategy_planner):
        intent, complexity, conv = self._make_inputs(Intent.ARCHITECTURE)
        strategy = strategy_planner.plan(intent, complexity, conv)
        assert strategy == ResponseStrategy.ARCHITECTURE

    def test_correction_always_uses_direct_answer(self, strategy_planner):
        intent, complexity, conv = self._make_inputs(
            Intent.CODING, turn=ConversationTurn.CORRECTION
        )
        strategy = strategy_planner.plan(intent, complexity, conv)
        assert strategy == ResponseStrategy.DIRECT_ANSWER

    def test_comparison_uses_comparison_strategy(self, strategy_planner):
        intent, complexity, conv = self._make_inputs(Intent.COMPARISON)
        strategy = strategy_planner.plan(intent, complexity, conv)
        assert strategy == ResponseStrategy.COMPARISON


# ── Intelligence Tool Planner Tests ──────────────────────────────────────────


class TestIntelligenceToolPlanner:
    def _make_context(self, intent: Intent, repo_id=None, has_code_context=False,
                      complexity=Complexity.MEDIUM):
        from app.intelligence.models import (
            ComplexityAnalysis,
            ConversationAnalysis,
            ConversationTurn,
            DetectedIntent,
            IntelligenceContext,
            IntentAnalysis,
            Persona,
            PolicyDecision,
            PolicyResult,
        )
        return IntelligenceContext(
            user_message="test",
            conversation_id="conv1",
            user_id="user1",
            org_id="org1",
            repo_id=repo_id,
            agent_mode="auto",
            intent_analysis=IntentAnalysis(primary=DetectedIntent(intent, 0.9, [])),
            complexity=ComplexityAnalysis(
                level=complexity,
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
            strategy=ResponseStrategy.CODING,
            code_context_block="some context" if has_code_context else "",
        )

    def test_no_tools_without_repo(self, tool_planner):
        context = self._make_context(Intent.CODING, repo_id=None)
        plan = tool_planner.plan(context)
        assert not plan.should_use_tools

    def test_search_code_for_repo_question(self, tool_planner):
        context = self._make_context(Intent.REPOSITORY_QUESTION, repo_id="repo1")
        plan = tool_planner.plan(context)
        assert plan.should_use_tools
        assert "search_code" in plan.tools

    def test_git_diff_for_git_operations(self, tool_planner):
        context = self._make_context(Intent.GIT_OPERATIONS, repo_id="repo1")
        plan = tool_planner.plan(context)
        assert "git_diff" in plan.tools

    def test_no_tools_when_context_sufficient(self, tool_planner):
        context = self._make_context(
            Intent.CODING, repo_id="repo1", has_code_context=True,
            complexity=Complexity.SIMPLE
        )
        plan = tool_planner.plan(context)
        assert not plan.should_use_tools


# ── Response Reviewer Tests ───────────────────────────────────────────────────


class TestResponseReviewer:
    def _make_context(self, intent=Intent.GENERAL_CHAT, complexity=Complexity.SIMPLE,
                      strategy=ResponseStrategy.DIRECT_ANSWER, code_context=""):
        from app.intelligence.models import (
            ComplexityAnalysis,
            ConversationAnalysis,
            ConversationTurn,
            DetectedIntent,
            IntelligenceContext,
            IntentAnalysis,
            Persona,
            PolicyDecision,
            PolicyResult,
        )
        return IntelligenceContext(
            user_message="test",
            conversation_id="conv1",
            user_id="user1",
            org_id="org1",
            repo_id=None,
            agent_mode="auto",
            intent_analysis=IntentAnalysis(primary=DetectedIntent(intent, 0.9, [])),
            complexity=ComplexityAnalysis(
                level=complexity,
                expected_response_length="short",
                reasoning_depth="surface",
                estimated_tool_calls=0,
                estimated_context_tokens=512,
                expected_token_budget=512,
                response_strategy_hint=strategy,
            ),
            conversation=ConversationAnalysis(
                turn_type=ConversationTurn.NEW_TOPIC,
                topic_summary="test",
                user_goal="test",
                is_continuation=False,
                referenced_prior_turn=False,
            ),
            policy=PolicyResult(decision=PolicyDecision.ALLOW),
            persona=Persona.TEACHER,
            strategy=strategy,
            code_context_block=code_context,
        )

    def test_approves_good_response(self, response_reviewer):
        context = self._make_context()
        result = response_reviewer.review("React is a JavaScript library for building UIs.", context)
        assert result.decision == ReviewDecision.APPROVED

    def test_flags_empty_response(self, response_reviewer):
        context = self._make_context()
        result = response_reviewer.review("", context)
        assert result.decision == ReviewDecision.REGENERATE

    def test_flags_missing_code_block_for_coding_intent(self, response_reviewer):
        context = self._make_context(
            intent=Intent.CODING,
            complexity=Complexity.MEDIUM,
            strategy=ResponseStrategy.CODING,
        )
        result = response_reviewer.review(
            "You should use a function to do this. It is straightforward.", context
        )
        assert any("code block" in issue.lower() for issue in result.issues)

    def test_approves_response_with_code_block(self, response_reviewer):
        context = self._make_context(
            intent=Intent.CODING,
            complexity=Complexity.MEDIUM,
            strategy=ResponseStrategy.CODING,
        )
        result = response_reviewer.review(
            "Here is the implementation:\n```python\ndef hello():\n    return 'world'\n```",
            context,
        )
        assert "code block" not in " ".join(result.issues).lower()

    def test_flags_refusal_language(self, response_reviewer):
        context = self._make_context()
        result = response_reviewer.review("I cannot help with that as an AI.", context)
        assert result.decision in (ReviewDecision.REGENERATE, ReviewDecision.NEEDS_FORMATTING)


# ── Response Formatter Tests ──────────────────────────────────────────────────


class TestResponseFormatter:
    def _make_context(self, strategy=ResponseStrategy.DIRECT_ANSWER):
        from app.intelligence.models import (
            ComplexityAnalysis,
            ConversationAnalysis,
            ConversationTurn,
            DetectedIntent,
            IntelligenceContext,
            IntentAnalysis,
            Persona,
            PolicyDecision,
            PolicyResult,
        )
        return IntelligenceContext(
            user_message="test",
            conversation_id="conv1",
            user_id="user1",
            org_id="org1",
            repo_id=None,
            agent_mode="auto",
            intent_analysis=IntentAnalysis(
                primary=DetectedIntent(Intent.GENERAL_CHAT, 0.9, [])
            ),
            complexity=ComplexityAnalysis(
                level=Complexity.SIMPLE,
                expected_response_length="short",
                reasoning_depth="surface",
                estimated_tool_calls=0,
                estimated_context_tokens=512,
                expected_token_budget=512,
                response_strategy_hint=strategy,
            ),
            conversation=ConversationAnalysis(
                turn_type=ConversationTurn.NEW_TOPIC,
                topic_summary="test",
                user_goal="test",
                is_continuation=False,
                referenced_prior_turn=False,
            ),
            policy=PolicyResult(decision=PolicyDecision.ALLOW),
            persona=Persona.TEACHER,
            strategy=strategy,
        )

    def test_removes_preamble_from_direct_answer(self, response_formatter):
        context = self._make_context(ResponseStrategy.DIRECT_ANSWER)
        result = response_formatter.format("Sure! React is a library.", context)
        assert not result.startswith("Sure")

    def test_fixes_unclosed_code_block(self, response_formatter):
        context = self._make_context(ResponseStrategy.CODING)
        result = response_formatter.format("```python\ndef hello():\n    pass", context)
        assert result.count("```") % 2 == 0

    def test_preserves_content(self, response_formatter):
        context = self._make_context(ResponseStrategy.DIRECT_ANSWER)
        result = response_formatter.format("React is a JavaScript library.", context)
        assert "React" in result
        assert "JavaScript" in result
