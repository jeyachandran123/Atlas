"""
Reflection Engine.

After the LLM generates a response, reflect on whether it actually
achieved the user's goal. Not grammar — goal achievement.

Questions:
- Did this solve the user's objective?
- Were any sub-objectives missed?
- Is any section too weak?
- Would a different strategy have been better?

No LLM call. Heuristic analysis of response against goal.
"""

from __future__ import annotations

import re

from app.intelligence.reasoning.interfaces import AbstractReflectionEngine
from app.intelligence.reasoning.models import (
    GoalType,
    InferredGoal,
    ReflectionResult,
    ReflectionVerdict,
    WeakSection,
)

# Minimum word counts per section type — reserved for future length-based checks
_SECTION_MIN_WORDS = {
    "explanation":  30,
    "example":      20,
    "code":         10,
    "steps":        15,
    "summary":      15,
    "comparison":   40,
}

# Strategy → expected response elements — reserved for future completeness checks
_STRATEGY_EXPECTED: dict[str, list[str]] = {
    "teaching":        ["example", "explanation", "summary"],
    "coding":          ["code"],
    "architecture":    ["explanation", "comparison"],
    "troubleshooting": ["explanation", "code"],
    "comparison":      ["comparison", "summary"],
    "research":        ["explanation", "summary"],
    "recommendation":  ["explanation", "summary"],
    "step_by_step":    ["steps"],
}

# GoalType → strategy that should have been used
_GOAL_EXPECTED_STRATEGY: dict[GoalType, str] = {
    GoalType.FIND_AND_FIX:  "troubleshooting",
    GoalType.BUILD:         "coding",
    GoalType.IMPROVE:       "coding",
    GoalType.VALIDATE:      "coding",
    GoalType.UNDERSTAND:    "teaching",
    GoalType.EXPLAIN:       "teaching",
    GoalType.RESEARCH:      "research",
    GoalType.DECIDE:        "recommendation",
    GoalType.COMPARE:       "comparison",
    GoalType.PLAN:          "step_by_step",
}


def _detect_weak_sections(response: str, strategy: str) -> list[WeakSection]:
    """Identify sections that are present but too thin."""
    weak: list[WeakSection] = []
    lower = response.lower()

    # Check for code blocks
    code_blocks = re.findall(r"```[\s\S]*?```", response)
    if strategy in ("coding", "troubleshooting") and not code_blocks:
        weak.append(WeakSection(
            section_id="code",
            description="Code implementation",
            weakness_reason="No code block found in a coding/troubleshooting response",
            expansion_hint="Add a complete, working code example",
        ))

    # Check for examples
    has_example = "example" in lower or "for instance" in lower or "e.g." in lower
    if strategy in ("teaching", "research") and not has_example:
        weak.append(WeakSection(
            section_id="example",
            description="Concrete examples",
            weakness_reason="No examples found in a teaching/research response",
            expansion_hint="Add at least one concrete, practical example",
        ))

    # Check for summary
    has_summary = any(w in lower for w in ["summary", "in conclusion", "to summarize", "key takeaway"])
    if strategy in ("teaching", "research", "comparison") and not has_summary:
        weak.append(WeakSection(
            section_id="summary",
            description="Summary or conclusion",
            weakness_reason="No summary found",
            expansion_hint="Add a brief summary of key points",
        ))

    # Check for comparison table
    if strategy == "comparison" and "|" not in response and "vs" not in lower:
        weak.append(WeakSection(
            section_id="comparison",
            description="Comparison table or structured comparison",
            weakness_reason="No structured comparison found",
            expansion_hint="Add a comparison table or structured side-by-side analysis",
        ))

    # Check for step-by-step structure
    has_steps = bool(re.search(r"^\s*\d+[\.\)]\s", response, re.MULTILINE))
    if strategy == "step_by_step" and not has_steps:
        weak.append(WeakSection(
            section_id="steps",
            description="Step-by-step structure",
            weakness_reason="No numbered steps found in a step-by-step response",
            expansion_hint="Structure the response as numbered steps",
        ))

    return weak


def _check_missed_objectives(response: str, goal: InferredGoal) -> list[str]:
    """Check which sub-objectives appear unaddressed in the response."""
    missed: list[str] = []
    lower = response.lower()

    objective_keywords: dict[str, list[str]] = {
        "identify the root cause": ["root cause", "cause", "reason", "why"],
        "design and apply the fix": ["fix", "solution", "patch", "resolve"],
        "validate the fix":        ["test", "verify", "validate", "confirm"],
        "provide examples":        ["example", "for instance", "e.g.", "such as"],
        "summarize key takeaways": ["summary", "key", "takeaway", "conclusion"],
        "make recommendation":     ["recommend", "suggest", "best", "should"],
        "identify dependencies":   ["depend", "prerequisite", "require", "before"],
    }

    for objective in goal.sub_objectives:
        obj_lower = objective.lower()
        for pattern, keywords in objective_keywords.items():
            if pattern in obj_lower:
                if not any(kw in lower for kw in keywords):
                    missed.append(objective)
                break

    return missed[:3]  # cap at 3 to avoid noise


def _detect_strategy_mismatch(goal: InferredGoal, actual_strategy: str) -> str | None:
    """Detect if the wrong strategy was used for this goal."""
    expected = _GOAL_EXPECTED_STRATEGY.get(goal.goal_type)
    if expected and expected != actual_strategy:
        significant_mismatches = {
            ("teaching", "direct_answer"),
            ("coding", "direct_answer"),
            ("troubleshooting", "teaching"),
            ("comparison", "direct_answer"),
        }
        if (expected, actual_strategy) in significant_mismatches:
            return expected
    return None


class ReflectionEngine(AbstractReflectionEngine):
    """
    Reflects on whether the generated response achieved the goal.
    Produces a structured verdict with specific weak sections identified.
    """

    def reflect(
        self,
        response: str,
        goal: InferredGoal,
        context,
    ) -> ReflectionResult:
        strategy = context.strategy.value if context.strategy else "direct_answer"

        # Detect weak sections
        weak_sections = _detect_weak_sections(response, strategy)

        # Check missed objectives
        missed = _check_missed_objectives(response, goal)

        # Detect strategy mismatch
        alt_strategy = _detect_strategy_mismatch(goal, strategy)

        # Determine verdict
        if alt_strategy:
            verdict = ReflectionVerdict.STRATEGY_MISMATCH
            goal_achieved = False
        elif missed and len(missed) >= 2:
            verdict = ReflectionVerdict.MISSED_GOAL
            goal_achieved = False
        elif weak_sections:
            verdict = ReflectionVerdict.NEEDS_EXPANSION
            goal_achieved = len(weak_sections) <= 1  # minor weakness is acceptable
        else:
            verdict = ReflectionVerdict.SATISFACTORY
            goal_achieved = True

        notes_parts = []
        if missed:
            notes_parts.append(f"Missed: {'; '.join(missed[:2])}")
        if weak_sections:
            notes_parts.append(f"Weak: {'; '.join(s.section_id for s in weak_sections)}")
        if alt_strategy:
            notes_parts.append(f"Expected strategy: {alt_strategy}")

        return ReflectionResult(
            verdict=verdict,
            goal_achieved=goal_achieved,
            missed_objectives=missed,
            weak_sections=weak_sections,
            alternative_strategy=alt_strategy,
            reflection_notes="; ".join(notes_parts),
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: ReflectionEngine | None = None


def get_reflection_engine() -> ReflectionEngine:
    global _engine
    if _engine is None:
        _engine = ReflectionEngine()
    return _engine
