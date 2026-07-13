"""
Complexity Analyzer.

Estimates the complexity of a request and produces a resource plan:
- Complexity level (Simple → Very Complex)
- Expected response length
- Reasoning depth required
- Estimated tool calls
- Token budget
- Response strategy hint

The user never configures this. Atlas infers it automatically.
"""

from __future__ import annotations

from app.intelligence.interfaces import AbstractComplexityAnalyzer
from app.intelligence.models import (
    Complexity,
    ComplexityAnalysis,
    Intent,
    IntentAnalysis,
    ResponseStrategy,
)

# ── Complexity signals ────────────────────────────────────────────────────────

_SIMPLE_SIGNALS = [
    "what is", "define", "what does", "how do i", "quick question",
    "simple", "basic", "just", "only",
]

_COMPLEX_SIGNALS = [
    "from scratch", "full implementation", "complete", "entire", "all of",
    "production", "enterprise", "scalable", "architecture", "system design",
    "step by step", "comprehensive", "in depth",
]

_VERY_COMPLEX_SIGNALS = [
    "beginner to advanced", "teach me everything", "full tutorial",
    "complete guide", "master", "deep dive", "from zero to hero",
    "full stack", "end to end", "e2e implementation",
]

# Intent → base complexity
_INTENT_BASE_COMPLEXITY: dict[Intent, Complexity] = {
    Intent.GENERAL_CHAT:        Complexity.SIMPLE,
    Intent.LEARNING:            Complexity.MEDIUM,
    Intent.DEEP_TEACHING:       Complexity.VERY_COMPLEX,
    Intent.CODING:              Complexity.MEDIUM,
    Intent.DEBUGGING:           Complexity.MEDIUM,
    Intent.ARCHITECTURE:        Complexity.COMPLEX,
    Intent.REPOSITORY_QUESTION: Complexity.MEDIUM,
    Intent.DOCUMENTATION:       Complexity.MEDIUM,
    Intent.RECOMMENDATION:      Complexity.MEDIUM,
    Intent.COMPARISON:          Complexity.MEDIUM,
    Intent.RESEARCH:            Complexity.COMPLEX,
    Intent.BRAINSTORMING:       Complexity.MEDIUM,
    Intent.PLANNING:            Complexity.COMPLEX,
    Intent.REFACTORING:         Complexity.COMPLEX,
    Intent.TESTING:             Complexity.MEDIUM,
    Intent.GIT_OPERATIONS:      Complexity.SIMPLE,
    Intent.TOOL_EXECUTION:      Complexity.SIMPLE,
    Intent.UNKNOWN:             Complexity.SIMPLE,
    Intent.DOCUMENT_ANALYSIS:   Complexity.MEDIUM,
}

# Complexity → response profile
_COMPLEXITY_PROFILES: dict[Complexity, dict] = {
    Complexity.SIMPLE: {
        "response_length": "short",
        "reasoning_depth": "surface",
        "tool_calls": 0,
        "context_tokens": 512,
        "token_budget": 512,
        "strategy": ResponseStrategy.DIRECT_ANSWER,
    },
    Complexity.MEDIUM: {
        "response_length": "medium",
        "reasoning_depth": "moderate",
        "tool_calls": 1,
        "context_tokens": 2048,
        "token_budget": 2048,
        "strategy": ResponseStrategy.STEP_BY_STEP,
    },
    Complexity.COMPLEX: {
        "response_length": "long",
        "reasoning_depth": "deep",
        "tool_calls": 3,
        "context_tokens": 4096,
        "token_budget": 4096,
        "strategy": ResponseStrategy.TEACHING,
    },
    Complexity.VERY_COMPLEX: {
        "response_length": "very_long",
        "reasoning_depth": "exhaustive",
        "tool_calls": 5,
        "context_tokens": 8192,
        "token_budget": 8192,
        "strategy": ResponseStrategy.TEACHING,
    },
}

# Intent → preferred strategy override
_INTENT_STRATEGY_OVERRIDE: dict[Intent, ResponseStrategy] = {
    Intent.ARCHITECTURE:    ResponseStrategy.ARCHITECTURE,
    Intent.RECOMMENDATION:  ResponseStrategy.RECOMMENDATION,
    Intent.COMPARISON:      ResponseStrategy.COMPARISON,
    Intent.DEBUGGING:       ResponseStrategy.TROUBLESHOOTING,
    Intent.BRAINSTORMING:   ResponseStrategy.BRAINSTORMING,
    Intent.RESEARCH:        ResponseStrategy.RESEARCH,
    Intent.CODING:          ResponseStrategy.CODING,
    Intent.REFACTORING:     ResponseStrategy.CODING,
    Intent.TESTING:         ResponseStrategy.CODING,
}


class ComplexityAnalyzer(AbstractComplexityAnalyzer):
    """
    Analyzes request complexity from message content and intent signals.
    No LLM call required — pure heuristic analysis.
    """

    def analyze(
        self,
        message: str,
        intent_analysis: IntentAnalysis,
        session_messages: list[dict],
    ) -> ComplexityAnalysis:
        lower = message.lower()
        signals: list[str] = []

        # Start from intent base
        base = _INTENT_BASE_COMPLEXITY.get(intent_analysis.primary.intent, Complexity.SIMPLE)
        level = base

        # Upgrade based on message signals
        for sig in _VERY_COMPLEX_SIGNALS:
            if sig in lower:
                level = Complexity.VERY_COMPLEX
                signals.append(sig)
                break

        if level != Complexity.VERY_COMPLEX:
            for sig in _COMPLEX_SIGNALS:
                if sig in lower:
                    if level.value < Complexity.COMPLEX.value:
                        level = Complexity.COMPLEX
                    signals.append(sig)

        # Downgrade if simple signals present
        if not signals:
            for sig in _SIMPLE_SIGNALS:
                if sig in lower:
                    if level == Complexity.MEDIUM:
                        level = Complexity.SIMPLE
                    signals.append(sig)
                    break

        # Upgrade if multiple secondary intents (multi-intent = more work)
        if len(intent_analysis.secondary) >= 2 and level == Complexity.SIMPLE:
            level = Complexity.MEDIUM
            signals.append("multi_intent")

        # Message length heuristic
        word_count = len(message.split())
        if word_count > 100 and level == Complexity.SIMPLE:
            level = Complexity.MEDIUM
            signals.append("long_message")

        profile = _COMPLEXITY_PROFILES[level]

        # Strategy: use intent override if available, else profile default
        strategy = _INTENT_STRATEGY_OVERRIDE.get(
            intent_analysis.primary.intent,
            profile["strategy"],
        )

        return ComplexityAnalysis(
            level=level,
            expected_response_length=profile["response_length"],
            reasoning_depth=profile["reasoning_depth"],
            estimated_tool_calls=profile["tool_calls"],
            estimated_context_tokens=profile["context_tokens"],
            expected_token_budget=profile["token_budget"],
            response_strategy_hint=strategy,
            signals=signals,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_analyzer: ComplexityAnalyzer | None = None


def get_complexity_analyzer() -> ComplexityAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = ComplexityAnalyzer()
    return _analyzer
