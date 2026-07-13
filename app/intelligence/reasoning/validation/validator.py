"""
Strategy Validator.

Verifies that the selected response strategy actually matches the inferred goal.
Detects mismatches before generation — not after.

"Education strategy chosen. User actually requested recommendation."
→ Detected before LLM call → corrected strategy applied.
"""

from __future__ import annotations

from app.intelligence.reasoning.interfaces import AbstractStrategyValidator
from app.intelligence.reasoning.models import (
    GoalType,
    InferredGoal,
    ValidationResult,
    ValidationVerdict,
)

# GoalType → acceptable strategies (first = preferred)
_GOAL_ACCEPTABLE_STRATEGIES: dict[GoalType, list[str]] = {
    GoalType.FIND_AND_FIX:  ["troubleshooting", "coding", "step_by_step"],
    GoalType.BUILD:         ["coding", "step_by_step"],
    GoalType.IMPROVE:       ["coding", "step_by_step"],
    GoalType.VALIDATE:      ["coding", "step_by_step"],
    GoalType.UNDERSTAND:    ["teaching", "direct_answer", "step_by_step"],
    GoalType.EXPLAIN:       ["teaching", "step_by_step", "direct_answer"],
    GoalType.RESEARCH:      ["research", "comparison", "teaching"],
    GoalType.DECIDE:        ["recommendation", "comparison"],
    GoalType.COMPARE:       ["comparison", "recommendation"],
    GoalType.PLAN:          ["step_by_step", "architecture"],
    GoalType.UNKNOWN:       ["direct_answer"],
}

# Mismatches severe enough to correct
_SEVERE_MISMATCHES: set[tuple[str, str]] = {
    ("direct_answer", "teaching"),      # teaching needed, got direct
    ("direct_answer", "coding"),        # code needed, got direct
    ("direct_answer", "troubleshooting"),
    ("teaching", "troubleshooting"),    # debugging, got lecture
    ("teaching", "recommendation"),     # recommendation needed, got lecture
    ("coding", "research"),             # research needed, got code
}


class StrategyValidator(AbstractStrategyValidator):
    """
    Validates the selected strategy against the inferred goal.
    Returns a corrected strategy if a severe mismatch is detected.
    """

    def validate(self, goal: InferredGoal, context) -> ValidationResult:
        selected = context.strategy.value if context.strategy else "direct_answer"
        acceptable = _GOAL_ACCEPTABLE_STRATEGIES.get(goal.goal_type, ["direct_answer"])
        preferred = acceptable[0]

        # Valid: selected strategy is in the acceptable list
        if selected in acceptable:
            return ValidationResult(
                verdict=ValidationVerdict.VALID,
                selected_strategy=selected,
                expected_strategy=preferred,
            )

        # Check severity
        is_severe = (selected, preferred) in _SEVERE_MISMATCHES

        if is_severe:
            return ValidationResult(
                verdict=ValidationVerdict.MISMATCH,
                selected_strategy=selected,
                expected_strategy=preferred,
                mismatch_reason=(
                    f"Goal '{goal.goal_type.value}' expects '{preferred}' "
                    f"but '{selected}' was selected"
                ),
                corrected_strategy=preferred,
            )

        # Minor mismatch — flag but don't correct
        return ValidationResult(
            verdict=ValidationVerdict.AMBIGUOUS,
            selected_strategy=selected,
            expected_strategy=preferred,
            mismatch_reason=(
                f"Strategy '{selected}' is not ideal for goal '{goal.goal_type.value}', "
                f"but acceptable"
            ),
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_validator: StrategyValidator | None = None


def get_strategy_validator() -> StrategyValidator:
    global _validator
    if _validator is None:
        _validator = StrategyValidator()
    return _validator
