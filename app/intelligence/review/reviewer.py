"""
Response Reviewer.

Reviews LLM output after generation and decides:
- APPROVED: response is good, send to user
- NEEDS_FORMATTING: content is correct but formatting can improve
- REGENERATE: response is inadequate, trigger regeneration

Checks:
- Did it answer the question?
- Is it too short for the complexity?
- Is it repetitive?
- Is it missing code when code was expected?
- Does it contradict retrieved context?
- Does it contain refusal language when it shouldn't?
"""

from __future__ import annotations

from app.intelligence.interfaces import AbstractResponseReviewer
from app.intelligence.models import (
    Complexity,
    IntelligenceContext,
    Intent,
    ReviewDecision,
    ReviewResult,
    ResponseStrategy,
)

# Minimum word counts by complexity
_MIN_WORDS: dict[Complexity, int] = {
    Complexity.SIMPLE:      8,
    Complexity.MEDIUM:      50,
    Complexity.COMPLEX:     150,
    Complexity.VERY_COMPLEX: 300,
}

# Intents that require code blocks
_CODE_REQUIRED_INTENTS = {
    Intent.CODING,
    Intent.DEBUGGING,
    Intent.REFACTORING,
    Intent.TESTING,
}

_REFUSAL_PHRASES = [
    "i cannot", "i can't", "i am unable", "i'm unable",
    "i don't have the ability", "as an ai",
]

_REPETITION_THRESHOLD = 0.4  # if >40% of sentences repeat, flag it


class ResponseReviewer(AbstractResponseReviewer):
    """
    Heuristic response reviewer. No LLM call required.
    Fast enough to run on every response.
    """

    def review(self, response: str, context: IntelligenceContext) -> ReviewResult:
        issues: list[str] = []
        suggestions: list[str] = []
        score = 1.0

        if not response or not response.strip():
            return ReviewResult(
                decision=ReviewDecision.REGENERATE,
                issues=["Empty response"],
                score=0.0,
            )

        words = response.split()
        word_count = len(words)
        lower = response.lower()

        # ── Check 1: Minimum length ───────────────────────────────────────────
        min_words = _MIN_WORDS.get(context.complexity.level, 10)
        if word_count < min_words:
            issues.append(f"Response too short ({word_count} words, expected ≥{min_words})")
            score -= 0.3

        # ── Check 2: Code block presence ─────────────────────────────────────
        intent = context.intent_analysis.primary.intent
        if intent in _CODE_REQUIRED_INTENTS and "```" not in response:
            issues.append("Code block expected but not found")
            suggestions.append("Include a complete code example")
            score -= 0.2

        # ── Check 3: Refusal language ─────────────────────────────────────────
        for phrase in _REFUSAL_PHRASES:
            if phrase in lower:
                issues.append(f"Response contains refusal language: '{phrase}'")
                score -= 0.4
                break

        # ── Check 4: Repetition detection ────────────────────────────────────
        sentences = [s.strip() for s in response.split(".") if len(s.strip()) > 20]
        if len(sentences) > 4:
            unique = set(sentences)
            repetition_ratio = 1.0 - (len(unique) / len(sentences))
            if repetition_ratio > _REPETITION_THRESHOLD:
                issues.append(f"Response is repetitive ({repetition_ratio:.0%} duplicate sentences)")
                score -= 0.2

        # ── Check 5: Context contradiction ───────────────────────────────────
        if context.code_context_block:
            # Simple check: if response says "not found" but context has content
            if "not found" in lower and len(context.code_context_block) > 100:
                issues.append("Response says 'not found' but code context was retrieved")
                suggestions.append("Review the retrieved context and reference it")
                score -= 0.2

        # ── Check 6: Teaching strategy completeness ───────────────────────────
        if context.strategy == ResponseStrategy.TEACHING and word_count < 200:
            issues.append("Teaching response is too brief for the selected strategy")
            suggestions.append("Expand with examples and step-by-step explanation")
            score -= 0.15

        # ── Decision ─────────────────────────────────────────────────────────
        score = max(0.0, score)

        if score < 0.4:
            decision = ReviewDecision.REGENERATE
        elif issues and score < 0.8:
            decision = ReviewDecision.NEEDS_FORMATTING
        else:
            decision = ReviewDecision.APPROVED

        return ReviewResult(
            decision=decision,
            issues=issues,
            suggestions=suggestions,
            score=score,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_reviewer: ResponseReviewer | None = None


def get_response_reviewer() -> ResponseReviewer:
    global _reviewer
    if _reviewer is None:
        _reviewer = ResponseReviewer()
    return _reviewer
