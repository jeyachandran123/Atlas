"""
Confidence Evaluator.

Scores every reasoning dimension and drives decisions:
- Should Atlas ask a clarifying question?
- Should Atlas retrieve more context?
- Is the goal clear enough to proceed?

Confidence influences decisions — it does not just log.
No LLM call. Pure heuristic scoring.
"""

from __future__ import annotations

from app.intelligence.reasoning.interfaces import AbstractConfidenceEvaluator
from app.intelligence.reasoning.models import (
    ConfidenceLevel,
    ConfidenceReport,
    ConfidenceScore,
    GoalType,
    InferredGoal,
)

# Thresholds
_HIGH_THRESHOLD    = 0.75
_MEDIUM_THRESHOLD  = 0.50
_LOW_THRESHOLD     = 0.25

# Minimum overall confidence to proceed without clarification
_CLARIFY_THRESHOLD = 0.30

# Minimum repo-match confidence before requesting more retrieval
_RETRIEVAL_THRESHOLD = 0.40


def _level(score: float) -> ConfidenceLevel:
    if score >= _HIGH_THRESHOLD:
        return ConfidenceLevel.HIGH
    if score >= _MEDIUM_THRESHOLD:
        return ConfidenceLevel.MEDIUM
    if score >= _LOW_THRESHOLD:
        return ConfidenceLevel.LOW
    return ConfidenceLevel.VERY_LOW


def _score_intent(context) -> ConfidenceScore:
    raw = context.intent_analysis.primary.confidence
    return ConfidenceScore(
        dimension="intent",
        score=raw,
        level=_level(raw),
        reason=f"Intent '{context.intent_analysis.primary.intent.value}' detected with {raw:.2f}",
    )


def _score_goal(goal: InferredGoal) -> ConfidenceScore:
    score = goal.confidence
    # Penalise UNKNOWN goal type
    if goal.goal_type == GoalType.UNKNOWN:
        score = min(score, 0.20)
    return ConfidenceScore(
        dimension="goal",
        score=score,
        level=_level(score),
        reason=f"Goal type '{goal.goal_type.value}' with confidence {score:.2f}",
    )


def _score_complexity(context) -> ConfidenceScore:
    # Complexity confidence is high when signals are clear
    signals = context.complexity.signals
    score = min(0.5 + len(signals) * 0.1, 1.0) if signals else 0.5
    return ConfidenceScore(
        dimension="complexity",
        score=score,
        level=_level(score),
        reason=f"Complexity '{context.complexity.level.value}' with {len(signals)} signals",
    )


def _score_repo_match(context) -> ConfidenceScore:
    """How confident are we that retrieved context matches the request?"""
    if not context.repo_id:
        return ConfidenceScore(
            dimension="repo_match",
            score=1.0,
            level=ConfidenceLevel.HIGH,
            reason="No repository — repo match not applicable",
        )
    if context.retrieved_chunks_count == 0:
        # Reasoning runs BEFORE the retrieval node, so zero chunks here is the
        # normal pre-retrieval state — not evidence of a mismatch. Penalising
        # it made an active repository *lower* overall confidence and trigger
        # spurious clarification questions (the anti-Repository-Mode bug).
        return ConfidenceScore(
            dimension="repo_match",
            score=0.60,
            level=ConfidenceLevel.MEDIUM,
            reason="Repository active — retrieval pending (runs after reasoning)",
        )
    # More chunks = higher confidence (capped at 8)
    score = min(0.4 + context.retrieved_chunks_count * 0.075, 1.0)
    return ConfidenceScore(
        dimension="repo_match",
        score=score,
        level=_level(score),
        reason=f"{context.retrieved_chunks_count} chunks retrieved",
    )


def _score_tool_selection(goal: InferredGoal, context) -> ConfidenceScore:
    """Confidence that the tool plan matches the goal's requirements."""
    tool_plan = context.tool_plan
    if not goal.requires_tools:
        return ConfidenceScore(
            dimension="tool_selection",
            score=1.0,
            level=ConfidenceLevel.HIGH,
            reason="No tools required for this goal",
        )
    if tool_plan is None or not tool_plan.should_use_tools:
        score = 0.30
        return ConfidenceScore(
            dimension="tool_selection",
            score=score,
            level=_level(score),
            reason="Goal requires tools but none planned",
        )
    score = min(0.6 + len(tool_plan.tools) * 0.1, 1.0)
    return ConfidenceScore(
        dimension="tool_selection",
        score=score,
        level=_level(score),
        reason=f"Tools planned: {', '.join(tool_plan.tools)}",
    )


def _build_clarification_question(scores: list[ConfidenceScore], goal: InferredGoal) -> str:
    """Build a targeted clarification question for the weakest dimension."""
    weakest = min(scores, key=lambda s: s.score)

    questions = {
        "intent": (
            "I want to make sure I understand what you need. "
            "Could you clarify what you're trying to achieve?"
        ),
        "goal": (
            f"Your message could mean a few different things. "
            f"Are you trying to {goal.primary_objective.lower()}?"
        ),
        "repo_match": (
            "I couldn't find relevant code in your repository. "
            "Could you point me to the specific file or module you're referring to?"
        ),
        "tool_selection": (
            "I need to access your codebase to help with this. "
            "Could you confirm which repository or file you're working with?"
        ),
    }
    return questions.get(
        weakest.dimension,
        "Could you provide more details about what you're trying to accomplish?",
    )


class ConfidenceEvaluator(AbstractConfidenceEvaluator):
    """
    Evaluates confidence across all reasoning dimensions.
    Drives decisions: clarify, retrieve more, or proceed.
    """

    def evaluate(self, goal: InferredGoal, context) -> ConfidenceReport:
        scores = [
            _score_intent(context),
            _score_goal(goal),
            _score_complexity(context),
            _score_repo_match(context),
            _score_tool_selection(goal, context),
        ]

        overall = sum(s.score for s in scores) / len(scores)
        overall_level = _level(overall)

        should_clarify = overall < _CLARIFY_THRESHOLD
        should_retrieve = (
            bool(context.repo_id)
            and context.retrieved_chunks_count == 0
        )

        # ── Repository Mode doctrine ──────────────────────────────────────────
        # Never ask a clarification question that a repository search could
        # answer. With an active repo and any tool/retrieval path available,
        # the correct behaviour is: search first, read second, answer — the
        # assistant is an engineer inside the repo, not a chatbot asking
        # "which file do you mean?".
        if should_clarify and context.repo_id:
            can_search = (
                context.retrieved_chunks_count > 0
                or bool(context.tool_plan and context.tool_plan.should_use_tools)
                or should_retrieve
            )
            if can_search:
                should_clarify = False

        clarification_question = ""
        if should_clarify:
            clarification_question = _build_clarification_question(scores, goal)

        return ConfidenceReport(
            scores=scores,
            overall=overall,
            overall_level=overall_level,
            should_clarify=should_clarify,
            should_retrieve_more=should_retrieve,
            clarification_question=clarification_question,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_evaluator: ConfidenceEvaluator | None = None


def get_confidence_evaluator() -> ConfidenceEvaluator:
    global _evaluator
    if _evaluator is None:
        _evaluator = ConfidenceEvaluator()
    return _evaluator
