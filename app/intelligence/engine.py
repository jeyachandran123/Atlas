"""
Conversation Intelligence Engine.

The brain of Atlas. Sits between the user and the LLM.

Pipeline:
    User Message
        → IntentDetector          (what does the user want?)
        → ComplexityAnalyzer      (how hard is this?)
        → ConversationAnalyzer    (what is the context?)
        → PolicyEngine            (is this allowed?)
        → PersonaEngine           (who should answer?)
        → ResponseStrategyPlanner (how should we answer?)
        → UserContextBuilder      (assemble all context)
        → IntelligenceToolPlanner (which tools are needed?)
        → DynamicPromptComposer   (build the prompt)
        → [LLM — called by orchestrator]
        → ResponseReviewer        (is the answer good?)
        → ResponseFormatter       (polish the output)
        → User

The engine does NOT call the LLM. It prepares everything the LLM needs
and reviews everything the LLM produces. The LLM is one component.
The intelligence is Atlas.

Dependency injection:
    Every module is injected via constructor.
    Every module can be replaced independently.
    Every module is independently testable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from app.intelligence.complexity.analyzer import ComplexityAnalyzer, get_complexity_analyzer
from app.intelligence.context.builder import UserContextBuilder, get_context_builder
from app.intelligence.conversation.analyzer import ConversationAnalyzer, get_conversation_analyzer
from app.intelligence.format.formatter import ResponseFormatter, get_response_formatter
from app.intelligence.intent.detector import IntentDetector, get_intent_detector
from app.intelligence.models import (
    IntelligenceContext,
    IntelligenceTrace,
    PolicyDecision,
    ReviewDecision,
)
from app.intelligence.observability.observer import IntelligenceObserver
from app.intelligence.persona.engine import PersonaEngine, get_persona_engine
from app.intelligence.policy.engine import PolicyEngine, get_policy_engine
from app.intelligence.prompt.composer import DynamicPromptComposer, get_dynamic_prompt_composer
from app.intelligence.review.reviewer import ResponseReviewer, get_response_reviewer
from app.intelligence.strategy.planner import ResponseStrategyPlanner, get_strategy_planner
from app.intelligence.tools.planner import IntelligenceToolPlanner, get_intelligence_tool_planner


def _get_reasoning_engine():
    """Lazy import — reasoning package has no heavy dependencies."""
    from app.intelligence.reasoning.engine import ReasoningEngine, get_reasoning_engine
    return get_reasoning_engine()


@dataclass
class EngineResult:
    """
    Output of the intelligence engine's pre-LLM pipeline.
    Passed to the orchestrator which calls the LLM.
    """
    context: IntelligenceContext
    system_prompt: str
    prompt_modules: list[str]
    is_blocked: bool = False
    block_response: Optional[str] = None
    trace: Optional[IntelligenceTrace] = None
    reasoning_result: Optional[object] = None  # ReasoningResult — typed loosely to avoid import


@dataclass
class ReviewedResult:
    """Output of the intelligence engine's post-LLM pipeline."""
    response: str
    should_regenerate: bool
    review_issues: list[str]
    trace: Optional[IntelligenceTrace] = None


class ConversationIntelligenceEngine:
    """
    Orchestrates all intelligence modules.

    Pre-LLM: analyze → plan → compose
    Post-LLM: review → format
    """

    def __init__(
        self,
        intent_detector: Optional[IntentDetector] = None,
        complexity_analyzer: Optional[ComplexityAnalyzer] = None,
        conversation_analyzer: Optional[ConversationAnalyzer] = None,
        policy_engine: Optional[PolicyEngine] = None,
        persona_engine: Optional[PersonaEngine] = None,
        strategy_planner: Optional[ResponseStrategyPlanner] = None,
        context_builder: Optional[UserContextBuilder] = None,
        tool_planner: Optional[IntelligenceToolPlanner] = None,
        prompt_composer: Optional[DynamicPromptComposer] = None,
        response_reviewer: Optional[ResponseReviewer] = None,
        response_formatter: Optional[ResponseFormatter] = None,
        memory_port=None,  # AbstractMemoryPort — lazy to avoid import chain
    ) -> None:
        self._intent = intent_detector or get_intent_detector()
        self._complexity = complexity_analyzer or get_complexity_analyzer()
        self._conversation = conversation_analyzer or get_conversation_analyzer()
        self._policy = policy_engine or get_policy_engine()
        self._persona = persona_engine or get_persona_engine()
        self._strategy = strategy_planner or get_strategy_planner()
        self._context_builder = context_builder or get_context_builder()
        self._tool_planner = tool_planner or get_intelligence_tool_planner()
        self._composer = prompt_composer or get_dynamic_prompt_composer()
        self._reviewer = response_reviewer or get_response_reviewer()
        self._formatter = response_formatter or get_response_formatter()
        self._memory = memory_port  # resolved lazily on first use
        self._reasoning = None      # ReasoningEngine — resolved lazily

    def _get_reasoning(self):
        if self._reasoning is None:
            self._reasoning = _get_reasoning_engine()
        return self._reasoning

    def _get_memory(self):
        if self._memory is None:
            from app.intelligence.memory.port import get_memory_port
            self._memory = get_memory_port()
        return self._memory

    async def prepare(self, state: dict) -> EngineResult:
        """
        Run the full pre-LLM intelligence pipeline.

        Input: AgentState dict (from the existing orchestrator)
        Output: EngineResult with system_prompt and IntelligenceContext

        The orchestrator calls this, then calls the LLM with the system_prompt,
        then calls review() with the LLM response.
        """
        request_id = state.get("request_id") or str(uuid.uuid4())
        message = state.get("user_message", "")
        observer = IntelligenceObserver(request_id, message)

        # ── Load session messages ─────────────────────────────────────────────
        session_messages = state.get("session_messages") or []
        if not session_messages:
            try:
                session_messages = await self._get_memory().get_session(
                    user_id=state.get("user_id", ""),
                    conversation_id=state.get("conversation_id", ""),
                    limit=10,
                )
            except Exception:
                session_messages = []

        agent_mode = state.get("agent_mode", "auto")

        # ── 1. Intent Detection ───────────────────────────────────────────────
        # Repository Mode: an active repo changes how ambiguous messages route.
        with observer.measure("intent"):
            intent_analysis = self._intent.detect(
                message,
                session_messages,
                agent_mode,
                repo_active=bool(state.get("repo_id")),
            )

        observer.record_intent(
            [i.value for i in intent_analysis.all_intents],
            intent_analysis.primary.confidence,
        )

        # ── 2. Complexity Analysis ────────────────────────────────────────────
        with observer.measure("complexity"):
            complexity = self._complexity.analyze(message, intent_analysis, session_messages)

        observer.record_complexity(complexity.level.value)

        # ── 3. Conversation Analysis ──────────────────────────────────────────
        with observer.measure("conversation"):
            conversation = self._conversation.analyze(message, session_messages, intent_analysis)

        observer.record_conversation(conversation.turn_type.value)

        # ── 4. Policy Evaluation ──────────────────────────────────────────────
        with observer.measure("policy"):
            policy = self._policy.evaluate(
                message,
                intent_analysis,
                state.get("user_id", ""),
                state.get("org_id", ""),
            )

        observer.record_policy(policy.decision.value)

        # Short-circuit on BLOCK
        if policy.decision == PolicyDecision.BLOCK:
            trace = observer.finalize()
            return EngineResult(
                context=IntelligenceContext(
                    user_message=message,
                    conversation_id=state.get("conversation_id", ""),
                    user_id=state.get("user_id", ""),
                    org_id=state.get("org_id", ""),
                    repo_id=state.get("repo_id"),
                    agent_mode=agent_mode,
                    intent_analysis=intent_analysis,
                    complexity=complexity,
                    conversation=conversation,
                    policy=policy,
                    persona=self._persona.select(intent_analysis, agent_mode, complexity),
                    strategy=self._strategy.plan(intent_analysis, complexity, conversation),
                    request_id=request_id,
                ),
                system_prompt="",
                prompt_modules=[],
                is_blocked=True,
                block_response=policy.safe_response or "I cannot help with that request.",
                trace=trace,
            )

        # ── 5. Persona Selection ──────────────────────────────────────────────
        persona = self._persona.select(intent_analysis, agent_mode, complexity)
        observer.record_persona(persona.value)

        # ── 6. Response Strategy ──────────────────────────────────────────────
        strategy = self._strategy.plan(intent_analysis, complexity, conversation)
        observer.record_strategy(strategy.value)

        # ── 7. Assemble Context ───────────────────────────────────────────────
        with observer.measure("context"):
            # Build partial context (tool plan added after)
            intel_context = self._context_builder.build_from_parts(
                state=state,
                intent_analysis=intent_analysis,
                complexity=complexity,
                conversation=conversation,
                policy=policy,
                persona=persona,
                strategy=strategy,
            )

        # ── 8. Tool Planning ──────────────────────────────────────────────────
        tool_plan = self._tool_planner.plan(intel_context)
        intel_context.tool_plan = tool_plan
        observer.record_tool_plan(tool_plan)

        # ── 9. Reasoning Engine ───────────────────────────────────────────────
        reasoning_result = None
        try:
            reasoning_result = self._get_reasoning().think(intel_context, request_id)
            # Apply corrected strategy if reasoning detected a mismatch
            if reasoning_result.corrected_strategy:
                from app.intelligence.models import ResponseStrategy
                try:
                    intel_context.strategy = ResponseStrategy(reasoning_result.corrected_strategy)
                except ValueError:
                    pass
            # Inject rewritten query into context for prompt composer
            if reasoning_result.rewritten_query.enrichments_applied:
                intel_context.extra["rewritten_query"] = reasoning_result.rewritten_query.rewritten
                intel_context.extra["reasoning_goal"] = reasoning_result.goal.primary_objective
        except Exception as e:
            from loguru import logger
            logger.warning(f"ReasoningEngine failed (non-blocking): {e}")

        # ── 10. Prompt Composition ────────────────────────────────────────────
        with observer.measure("prompt"):
            system_prompt, modules_used = self._composer.compose(intel_context)

        token_estimate = len(system_prompt) // 4
        observer.record_prompt_modules(modules_used, token_estimate)

        trace = observer.finalize()

        return EngineResult(
            context=intel_context,
            system_prompt=system_prompt,
            prompt_modules=modules_used,
            is_blocked=False,
            trace=trace,
            reasoning_result=reasoning_result,
        )

    def review(
        self,
        response: str,
        context: IntelligenceContext,
        reasoning_result=None,
    ) -> ReviewedResult:
        """
        Run the post-LLM review, reflection, and formatting pipeline.

        Input: raw LLM response + IntelligenceContext + optional ReasoningResult
        Output: ReviewedResult with polished response
        """
        # ── Reasoning reflection (post-generation) ────────────────────────────
        if reasoning_result is not None:
            try:
                post = self._get_reasoning().reflect(response, context, reasoning_result)
                # If full regeneration needed, signal upstream
                if post.needs_full_regeneration:
                    return ReviewedResult(
                        response=response,
                        should_regenerate=True,
                        review_issues=["Reasoning reflection: " + post.reflection.reflection_notes],
                    )
            except Exception as e:
                from loguru import logger
                logger.warning(f"Post-generation reflection failed (non-blocking): {e}")

        # ── Response quality review ───────────────────────────────────────────
        review_result = self._reviewer.review(response, context)

        # ── Format ────────────────────────────────────────────────────────────
        if review_result.decision != ReviewDecision.REGENERATE:
            response = self._formatter.format(response, context)

        return ReviewedResult(
            response=response,
            should_regenerate=review_result.decision == ReviewDecision.REGENERATE,
            review_issues=review_result.issues,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: ConversationIntelligenceEngine | None = None


def get_engine() -> ConversationIntelligenceEngine:
    global _engine
    if _engine is None:
        _engine = ConversationIntelligenceEngine()
    return _engine
