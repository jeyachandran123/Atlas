"""
Response Strategy Planner.

Decides HOW Atlas should answer — not what to say, but how to structure it.
Each strategy defines the response shape: ordering, depth, use of examples,
code blocks, tables, step-by-step guidance, trade-off discussions, etc.

Design:
- Each strategy is a StrategyDefinition (data, not logic)
- Adding a new strategy = adding one StrategyDefinition to the registry
- The planner selects a strategy; the prompt composer uses it
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.intelligence.interfaces import AbstractResponseStrategyPlanner
from app.intelligence.models import (
    ComplexityAnalysis,
    ConversationAnalysis,
    ConversationTurn,
    Intent,
    IntentAnalysis,
    ResponseStrategy,
)


@dataclass
class StrategyDefinition:
    strategy: ResponseStrategy
    prompt_fragment: str
    use_code_blocks: bool = False
    use_tables: bool = False
    use_bullet_points: bool = True
    use_step_by_step: bool = False
    use_examples: bool = True
    use_analogies: bool = False
    discuss_tradeoffs: bool = False
    include_summary: bool = False
    response_order: list[str] = field(default_factory=list)


# ── Strategy Definitions ──────────────────────────────────────────────────────

STRATEGY_REGISTRY: dict[ResponseStrategy, StrategyDefinition] = {
    ResponseStrategy.DIRECT_ANSWER: StrategyDefinition(
        strategy=ResponseStrategy.DIRECT_ANSWER,
        prompt_fragment=(
            "Answer directly and concisely. No preamble. "
            "If the answer is short, keep it short."
        ),
        use_bullet_points=False,
        use_examples=False,
        response_order=["answer"],
    ),
    ResponseStrategy.TEACHING: StrategyDefinition(
        strategy=ResponseStrategy.TEACHING,
        prompt_fragment=(
            "Structure your response as a progressive lesson: "
            "1) Concept overview, 2) Core principles, 3) Practical examples, "
            "4) Common pitfalls, 5) Summary. "
            "Use analogies to build intuition before introducing technical detail."
        ),
        use_code_blocks=True,
        use_examples=True,
        use_analogies=True,
        use_step_by_step=True,
        include_summary=True,
        response_order=["overview", "principles", "examples", "pitfalls", "summary"],
    ),
    ResponseStrategy.CODING: StrategyDefinition(
        strategy=ResponseStrategy.CODING,
        prompt_fragment=(
            "Provide working, production-quality code. "
            "Structure: 1) Brief explanation of approach, 2) Complete code, "
            "3) Key design decisions explained. "
            "Include error handling. Do not truncate code."
        ),
        use_code_blocks=True,
        use_examples=True,
        use_step_by_step=False,
        response_order=["approach", "code", "explanation"],
    ),
    ResponseStrategy.ARCHITECTURE: StrategyDefinition(
        strategy=ResponseStrategy.ARCHITECTURE,
        prompt_fragment=(
            "Structure your response as an architecture document: "
            "1) Problem statement, 2) Proposed architecture with components, "
            "3) Data flow, 4) Trade-offs and alternatives considered, "
            "5) Implementation guidance. Use ASCII diagrams where helpful."
        ),
        use_tables=True,
        use_bullet_points=True,
        discuss_tradeoffs=True,
        include_summary=True,
        response_order=["problem", "architecture", "data_flow", "tradeoffs", "implementation"],
    ),
    ResponseStrategy.RECOMMENDATION: StrategyDefinition(
        strategy=ResponseStrategy.RECOMMENDATION,
        prompt_fragment=(
            "Give a clear recommendation with reasoning: "
            "1) Your recommendation (be direct), 2) Why this is the best choice for this context, "
            "3) When you would choose differently, 4) Getting started."
        ),
        use_bullet_points=True,
        discuss_tradeoffs=True,
        response_order=["recommendation", "reasoning", "alternatives", "getting_started"],
    ),
    ResponseStrategy.COMPARISON: StrategyDefinition(
        strategy=ResponseStrategy.COMPARISON,
        prompt_fragment=(
            "Compare systematically: "
            "1) Summary table of key differences, "
            "2) Detailed analysis of each option, "
            "3) When to choose each, "
            "4) Final recommendation for the user's context."
        ),
        use_tables=True,
        use_bullet_points=True,
        discuss_tradeoffs=True,
        response_order=["summary_table", "detailed_analysis", "when_to_choose", "recommendation"],
    ),
    ResponseStrategy.TROUBLESHOOTING: StrategyDefinition(
        strategy=ResponseStrategy.TROUBLESHOOTING,
        prompt_fragment=(
            "Debug systematically: "
            "1) Identify the root cause (not just symptoms), "
            "2) Explain why this causes the problem, "
            "3) Provide the fix with complete code, "
            "4) Explain how to prevent this in future."
        ),
        use_code_blocks=True,
        use_step_by_step=True,
        response_order=["root_cause", "explanation", "fix", "prevention"],
    ),
    ResponseStrategy.BRAINSTORMING: StrategyDefinition(
        strategy=ResponseStrategy.BRAINSTORMING,
        prompt_fragment=(
            "Generate diverse ideas: "
            "1) Conventional approaches, 2) Creative alternatives, "
            "3) Unconventional ideas worth exploring, "
            "4) Quick evaluation of each. "
            "Quantity and diversity over perfection."
        ),
        use_bullet_points=True,
        use_examples=True,
        response_order=["conventional", "creative", "unconventional", "evaluation"],
    ),
    ResponseStrategy.RESEARCH: StrategyDefinition(
        strategy=ResponseStrategy.RESEARCH,
        prompt_fragment=(
            "Present a structured research summary: "
            "1) Current state of the topic, 2) Key concepts and terminology, "
            "3) Major approaches or schools of thought, "
            "4) Practical implications, 5) Knowledge limitations."
        ),
        use_tables=True,
        use_bullet_points=True,
        include_summary=True,
        response_order=["current_state", "concepts", "approaches", "implications", "limitations"],
    ),
    ResponseStrategy.STEP_BY_STEP: StrategyDefinition(
        strategy=ResponseStrategy.STEP_BY_STEP,
        prompt_fragment=(
            "Walk through this step by step. "
            "Number each step. Explain what each step does and why. "
            "Include code where relevant."
        ),
        use_code_blocks=True,
        use_step_by_step=True,
        use_examples=True,
        response_order=["steps"],
    ),
}


class ResponseStrategyPlanner(AbstractResponseStrategyPlanner):
    """
    Selects the response strategy based on intent, complexity, and conversation context.
    """

    # Intent → preferred strategy
    _INTENT_STRATEGY: dict[Intent, ResponseStrategy] = {
        Intent.CODING:              ResponseStrategy.CODING,
        Intent.DEBUGGING:           ResponseStrategy.TROUBLESHOOTING,
        Intent.ARCHITECTURE:        ResponseStrategy.ARCHITECTURE,
        Intent.LEARNING:            ResponseStrategy.TEACHING,
        Intent.DEEP_TEACHING:       ResponseStrategy.TEACHING,
        Intent.RECOMMENDATION:      ResponseStrategy.RECOMMENDATION,
        Intent.COMPARISON:          ResponseStrategy.COMPARISON,
        Intent.RESEARCH:            ResponseStrategy.RESEARCH,
        Intent.BRAINSTORMING:       ResponseStrategy.BRAINSTORMING,
        Intent.PLANNING:            ResponseStrategy.STEP_BY_STEP,
        Intent.REFACTORING:         ResponseStrategy.CODING,
        Intent.TESTING:             ResponseStrategy.CODING,
        Intent.DOCUMENTATION:       ResponseStrategy.STEP_BY_STEP,
        Intent.REPOSITORY_QUESTION: ResponseStrategy.DIRECT_ANSWER,
        Intent.GIT_OPERATIONS:      ResponseStrategy.STEP_BY_STEP,
        Intent.TOOL_EXECUTION:      ResponseStrategy.DIRECT_ANSWER,
        Intent.GENERAL_CHAT:        ResponseStrategy.DIRECT_ANSWER,
        Intent.UNKNOWN:             ResponseStrategy.DIRECT_ANSWER,
        Intent.DOCUMENT_ANALYSIS:   ResponseStrategy.RESEARCH,
    }

    def plan(
        self,
        intent_analysis: IntentAnalysis,
        complexity: ComplexityAnalysis,
        conversation: ConversationAnalysis,
    ) -> ResponseStrategy:
        # Use complexity hint if it's more specific than the intent default
        strategy = self._INTENT_STRATEGY.get(
            intent_analysis.primary.intent,
            complexity.response_strategy_hint,
        )

        # Corrections and clarifications always get direct answers
        if conversation.turn_type in (
            ConversationTurn.CORRECTION,
            ConversationTurn.CLARIFICATION,
        ):
            strategy = ResponseStrategy.DIRECT_ANSWER

        return strategy

    def get_definition(self, strategy: ResponseStrategy) -> StrategyDefinition:
        return STRATEGY_REGISTRY.get(strategy, STRATEGY_REGISTRY[ResponseStrategy.DIRECT_ANSWER])


# ── Singleton ─────────────────────────────────────────────────────────────────

_planner: ResponseStrategyPlanner | None = None


def get_strategy_planner() -> ResponseStrategyPlanner:
    global _planner
    if _planner is None:
        _planner = ResponseStrategyPlanner()
    return _planner
