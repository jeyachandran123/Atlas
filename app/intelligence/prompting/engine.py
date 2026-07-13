"""
Prompt Intelligence Engine.

The core of Atlas's prompting system.

This engine replaces the old template-based enhancer.py approach.
It does NOT fill templates. It reasons about the request and builds
the optimal internal instruction for the LLM.

Pipeline:
    Raw user message
        → PromptUnderstandingAnalyzer   (what does the user actually want?)
        → ConversationContextResolver   (which history is relevant?)
        → PromptExpander                (enrich incomplete objectives)
        → ResponseDepthPlanner          (how deep should the response be?)
        → PromptQualityEvaluator        (is the prompt ready?)
        → PromptPlan                    (final structured output)

The PromptPlan is consumed by the DynamicPromptComposer to build
the system prompt and user prompt sent to the LLM.

Design principles:
  - No static templates
  - Every decision is based on analysis of the actual request
  - Two identical messages in different contexts produce different prompts
  - The engine is the intelligence; the LLM is the generator
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.intelligence.models import (
    Complexity,
    ConversationTurn,
    IntelligenceContext,
)
from app.intelligence.prompting.context_resolver import (
    ConversationContextResolver,
    ResolvedContext,
    get_context_resolver,
)
from app.intelligence.prompting.depth_planner import (
    DepthPlan,
    ResponseDepthPlanner,
    get_depth_planner,
)
from app.intelligence.prompting.expander import (
    ExpandedPrompt,
    PromptExpander,
    get_prompt_expander,
)
from app.intelligence.prompting.quality_evaluator import (
    PromptQualityEvaluator,
    QualityReport,
    get_quality_evaluator,
)
from app.intelligence.prompting.understanding import (
    PromptUnderstanding,
    PromptUnderstandingAnalyzer,
    get_understanding_analyser,
)


@dataclass
class PromptPlan:
    """
    The complete output of the Prompt Intelligence Engine.
    Consumed by DynamicPromptComposer to build the final prompts.
    """
    # What the user actually wants
    understanding: PromptUnderstanding

    # The enriched internal objective (may differ from raw message)
    objective: str

    # Conversation context to inject (filtered, not raw history)
    resolved_context: ResolvedContext

    # How deep the response should be
    depth: DepthPlan

    # Quality check result
    quality: QualityReport

    # Personality / behavioural instructions (not scripted phrases)
    personality_principles: list[str] = field(default_factory=list)

    # Whether expansion was applied
    was_expanded: bool = False

    # The strategy selected for this request
    strategy: str = "direct_answer"

    # Modules used (for observability)
    modules_applied: list[str] = field(default_factory=list)


# ── Personality principles ────────────────────────────────────────────────────
# These are BEHAVIOURAL, not scripted. They define how Atlas speaks,
# not what words it uses.

_BASE_PRINCIPLES = [
    "Speak naturally, like a knowledgeable colleague — not like documentation.",
    "Vary your sentence structure. Avoid repetitive openings.",
    "Adapt your tone to match the user's level and style.",
    "Explain only as deeply as the question requires.",
    "Never pad responses. Every sentence should add value.",
    "If you are uncertain, say so explicitly.",
]

_TEACHING_PRINCIPLES = [
    "Build understanding progressively — foundations before depth.",
    "Use concrete examples and real-world analogies.",
    "Anticipate what the reader will wonder next and answer it.",
    "Connect each concept naturally to the next.",
]

_CODING_PRINCIPLES = [
    "Provide complete, working code — no placeholders.",
    "Explain design decisions, not just the code itself.",
    "Handle edge cases and errors explicitly.",
]

_CONVERSATIONAL_PRINCIPLES = [
    "Keep it conversational. No rigid structure unless the question needs it.",
    "Match the brevity of the question.",
]


def _select_personality_principles(intent: str, depth_label: str) -> list[str]:
    principles = list(_BASE_PRINCIPLES)

    if intent in ("learning", "deep_teaching"):
        principles.extend(_TEACHING_PRINCIPLES)
    elif intent in ("coding", "debugging", "refactoring", "testing"):
        principles.extend(_CODING_PRINCIPLES)
    elif intent == "general_chat" or depth_label == "brief":
        principles.extend(_CONVERSATIONAL_PRINCIPLES)

    return principles


class PromptIntelligenceEngine:
    """
    Orchestrates all prompting intelligence modules.

    Input:  IntelligenceContext (from ConversationIntelligenceEngine)
    Output: PromptPlan (consumed by DynamicPromptComposer)
    """

    def __init__(
        self,
        understanding_analyser: Optional[PromptUnderstandingAnalyzer] = None,
        context_resolver: Optional[ConversationContextResolver] = None,
        expander: Optional[PromptExpander] = None,
        depth_planner: Optional[ResponseDepthPlanner] = None,
        quality_evaluator: Optional[PromptQualityEvaluator] = None,
    ) -> None:
        self._understanding = understanding_analyser or get_understanding_analyser()
        self._context_resolver = context_resolver or get_context_resolver()
        self._expander = expander or get_prompt_expander()
        self._depth_planner = depth_planner or get_depth_planner()
        self._quality_evaluator = quality_evaluator or get_quality_evaluator()

    def plan(self, context: IntelligenceContext) -> PromptPlan:
        """
        Run the full prompt intelligence pipeline.

        Every decision is based on the actual request — no static templates.
        """
        message = context.user_message
        intent = context.intent_analysis.primary.intent.value
        strategy = context.strategy.value if context.strategy else "direct_answer"
        turn_type = context.conversation.turn_type
        complexity = context.complexity.level
        session_messages = context.session_messages or []
        modules: list[str] = []

        # ── 1. Understand the request ─────────────────────────────────────────
        understanding = self._understanding.analyse(message, intent, session_messages)
        modules.append("understanding")

        # ── 2. Resolve conversation context ───────────────────────────────────
        resolved_context = self._context_resolver.resolve(
            message=message,
            session_messages=session_messages,
            turn_type=turn_type,
            active_topic=understanding.topic,
        )
        modules.append("context_resolver")

        # ── 3. Expand the prompt if needed ────────────────────────────────────
        expanded = self._expander.expand(
            message=message,
            intent=intent,
            topic=understanding.topic,
            audience_level=understanding.audience_level,
            turn_type=turn_type,
        )
        modules.append("expander")

        # Use expanded objective if expansion was applied, else use understanding's objective
        objective = expanded.expanded if expanded.expansion_applied else understanding.real_objective

        # ── 4. Plan response depth ────────────────────────────────────────────
        has_prior_answer = bool(resolved_context.messages)
        depth = self._depth_planner.plan(
            message=message,
            intent=intent,
            complexity=complexity,
            turn_type=turn_type,
            has_prior_answer=has_prior_answer,
            use_code=intent in ("coding", "debugging", "refactoring", "testing"),
        )
        modules.append("depth_planner")

        # ── 5. Select personality principles ─────────────────────────────────
        personality_principles = _select_personality_principles(intent, depth.depth_label)

        # ── 6. Evaluate prompt quality ────────────────────────────────────────
        # Build a preview of the full prompt for verbosity check
        prompt_preview = f"{objective} {depth.depth_instruction}"
        quality = self._quality_evaluator.evaluate(
            objective=objective,
            full_prompt=prompt_preview,
            intent=intent,
            strategy=strategy,
            has_context=bool(resolved_context.messages),
        )
        modules.append("quality_evaluator")

        # Apply quality improvement if suggested
        if quality.improved_objective:
            objective = quality.improved_objective

        plan = PromptPlan(
            understanding=understanding,
            objective=objective,
            resolved_context=resolved_context,
            depth=depth,
            quality=quality,
            personality_principles=personality_principles,
            was_expanded=expanded.expansion_applied,
            strategy=strategy,
            modules_applied=modules,
        )
        self._trace(message, plan)
        return plan

    def _trace(self, message: str, plan: PromptPlan) -> None:
        from loguru import logger
        sep = "-" * 72
        lines = [
            f"\n{sep}",
            f"  PROMPT INTELLIGENCE ENGINE",
            sep,
            f"  Raw message  : {message[:70]}",
            f"  Topic        : {plan.understanding.topic}",
            f"  Audience     : {plan.understanding.audience_level}",
            f"  Objective    : {plan.objective[:100]}",
            f"  Expanded     : {plan.was_expanded}  ({plan.understanding.real_objective[:60]})",
            f"  Depth        : {plan.depth.depth_label}  ->  {plan.depth.target_length}",
            f"  Strategy     : {plan.strategy}",
            f"  Inject hist  : {plan.resolved_context.inject_history}"
            + (f"  ({len(plan.resolved_context.messages)} msgs)" if plan.resolved_context.inject_history else ""),
            f"  Continuity   : {plan.resolved_context.continuity_note[:80] if plan.resolved_context.continuity_note else 'none'}",
            f"  Quality OK   : {plan.quality.passed}"
            + (f"  issues={plan.quality.issues}" if not plan.quality.passed else ""),
            f"  Prior know.  : {plan.understanding.prior_knowledge or 'none'}",
            sep,
        ]
        output = "\n".join(lines)
        print(output, flush=True)
        logger.debug(output)


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: PromptIntelligenceEngine | None = None


def get_prompt_intelligence_engine() -> PromptIntelligenceEngine:
    global _engine
    if _engine is None:
        _engine = PromptIntelligenceEngine()
    return _engine
