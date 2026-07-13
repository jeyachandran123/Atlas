"""
Prompt Quality Evaluator.

Before the prompt is sent to the LLM, evaluate it.
Catch problems before they produce bad responses.

Checks:
  - Is important context missing?
  - Is irrelevant history included?
  - Is the instruction ambiguous?
  - Is the selected strategy appropriate for the goal?
  - Is the prompt unnecessarily verbose?
  - Could the model misunderstand the objective?

Output: a QualityReport with issues and an improved prompt if needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QualityReport:
    passed: bool
    issues: list[str] = field(default_factory=list)
    improved_objective: str = ""   # non-empty if the objective was rewritten


_AMBIGUITY_SIGNALS = [
    " it ", " this ", " that thing", " they ", " them ",
    "the thing", "the stuff",
]

_VERBOSITY_THRESHOLD = 800   # chars — prompts longer than this get a verbosity check


def _check_ambiguity(objective: str, has_context: bool) -> list[str]:
    """Flag objectives that use pronouns without referents."""
    issues = []
    lower = objective.lower()
    if not has_context:
        for sig in _AMBIGUITY_SIGNALS:
            if f" {sig} " in f" {lower} ":
                issues.append(
                    f"Objective uses '{sig}' without clear referent and no conversation context."
                )
                break
    return issues


def _check_strategy_fit(intent: str, strategy: str) -> list[str]:
    """Flag obvious strategy mismatches."""
    issues = []
    bad_pairs = {
        ("general_chat", "coding"),
        ("general_chat", "architecture"),
        ("debugging", "teaching"),
        ("git_operations", "teaching"),
    }
    if (intent, strategy) in bad_pairs:
        issues.append(
            f"Strategy '{strategy}' is likely wrong for intent '{intent}'."
        )
    return issues


def _check_verbosity(prompt: str) -> list[str]:
    """Flag prompts that are unnecessarily long."""
    if len(prompt) > _VERBOSITY_THRESHOLD:
        return [f"Prompt is {len(prompt)} chars — consider trimming redundant instructions."]
    return []


def _improve_objective(objective: str, issues: list[str]) -> str:
    """Attempt a light improvement if issues were found."""
    if not issues:
        return ""
    # For ambiguity: strip the ambiguous pronoun reference
    improved = objective
    for sig in _AMBIGUITY_SIGNALS:
        improved = improved.replace(f" {sig} ", " the subject ")
    return improved if improved != objective else ""


class PromptQualityEvaluator:
    """
    Evaluates prompt quality before it reaches the LLM.
    Catches issues that would produce poor responses.
    """

    def evaluate(
        self,
        objective: str,
        full_prompt: str,
        intent: str,
        strategy: str,
        has_context: bool,
    ) -> QualityReport:
        issues: list[str] = []

        issues.extend(_check_ambiguity(objective, has_context))
        issues.extend(_check_strategy_fit(intent, strategy))
        issues.extend(_check_verbosity(full_prompt))

        improved = _improve_objective(objective, issues) if issues else ""

        return QualityReport(
            passed=len(issues) == 0,
            issues=issues,
            improved_objective=improved,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_evaluator: PromptQualityEvaluator | None = None


def get_quality_evaluator() -> PromptQualityEvaluator:
    global _evaluator
    if _evaluator is None:
        _evaluator = PromptQualityEvaluator()
    return _evaluator
