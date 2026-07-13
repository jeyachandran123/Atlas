"""
Query Rewriter.

Enriches incomplete user queries with missing context before they reach the LLM.
Never changes the user's meaning — only adds what is implied but unstated.

"How humans evolved?"
→ "The user wants a comprehensive educational explanation of human evolution,
   suitable for a general audience. Cover chronologically: early life, mammals,
   primates, hominins, Homo species, migration, agriculture, modern civilization.
   Use storytelling, timelines and concrete examples."

No LLM call. Rule-based enrichment from goal + context signals.
"""

from __future__ import annotations

from app.intelligence.reasoning.interfaces import AbstractQueryRewriter
from app.intelligence.reasoning.models import (
    GoalType,
    InferredGoal,
    RewrittenQuery,
)

# ── Enrichment rules ──────────────────────────────────────────────────────────
# Each rule adds a specific type of context when conditions are met.


def _enrich_audience(message: str, context) -> tuple[str, str]:
    """Infer the audience level from conversation history."""
    session = context.session_messages or []
    all_content = " ".join(m.get("content", "") for m in session[-4:]).lower()

    if any(w in all_content for w in ["beginner", "new to", "just started", "learning"]):
        return "suitable for a beginner audience", "audience:beginner"
    if any(w in all_content for w in ["senior", "expert", "advanced", "production"]):
        return "suitable for an experienced engineer", "audience:expert"
    if any(w in all_content for w in ["team", "company", "organization", "enterprise"]):
        return "suitable for a professional engineering team", "audience:professional"
    return "", ""


def _enrich_domain(message: str, context) -> tuple[str, str]:
    """Add domain context from conversation assumptions."""
    assumptions = (context.conversation.assumptions or []) if context.conversation else []
    if not assumptions:
        return "", ""
    domain_parts = assumptions[:2]
    return "Context: " + "; ".join(domain_parts), "domain:from_history"


def _enrich_goal_context(goal: InferredGoal) -> tuple[str, str]:
    """Add the inferred goal's sub-objectives as context."""
    if not goal.sub_objectives:
        return "", ""
    steps = "; ".join(goal.sub_objectives[:3])
    return f"The response should address: {steps}", "goal:sub_objectives"


def _enrich_format_hint(goal: InferredGoal, context) -> tuple[str, str]:
    """Add format hints based on goal type and strategy."""
    strategy = context.strategy.value if context.strategy else ""
    hints = {
        "teaching":        "Use progressive explanation with examples and analogies.",
        "coding":          "Provide complete, working code with explanations.",
        "architecture":    "Use structured sections with trade-off analysis.",
        "troubleshooting": "Identify root cause first, then provide the fix.",
        "comparison":      "Use a systematic comparison with a summary table.",
        "research":        "Survey options objectively with practical implications.",
        "recommendation":  "Give a direct recommendation with clear reasoning.",
    }
    hint = hints.get(strategy, "")
    if hint:
        return hint, f"format:{strategy}"
    return "", ""


def _enrich_repo_context(goal: InferredGoal, context) -> tuple[str, str]:
    """Add repository context hint when relevant."""
    if goal.requires_repo and context.code_context_block:
        return (
            f"Relevant code has been retrieved ({context.retrieved_chunks_count} chunks). "
            "Base your response on the actual implementation.",
            "context:repo_retrieved",
        )
    return "", ""


def _enrich_continuation(context) -> tuple[str, str]:
    """Add continuity context for follow-up messages."""
    conv = context.conversation
    if not conv or not conv.is_continuation:
        return "", ""
    if conv.turn_type.value == "correction":
        return "The user is correcting a previous response. Address the correction directly.", "turn:correction"
    if conv.turn_type.value == "follow_up":
        return "This is a follow-up to the previous response. Build on what was already explained.", "turn:follow_up"
    return "", ""


class QueryRewriter(AbstractQueryRewriter):
    """
    Enriches user queries with missing context.
    Applies independent enrichment rules in sequence.
    Adding a new enrichment = adding one function above.
    """

    def rewrite(
        self,
        message: str,
        goal: InferredGoal,
        context,
    ) -> RewrittenQuery:
        enrichments: list[str] = []
        additions: list[str] = []

        def apply(text: str, tag: str) -> None:
            if text:
                additions.append(text)
                enrichments.append(tag)

        # Apply all enrichment rules
        apply(*_enrich_audience(message, context))
        apply(*_enrich_domain(message, context))
        apply(*_enrich_goal_context(goal))
        apply(*_enrich_format_hint(goal, context))
        apply(*_enrich_repo_context(goal, context))
        apply(*_enrich_continuation(context))

        # Build rewritten query
        if not additions:
            return RewrittenQuery(
                original=message,
                rewritten=message,
                enrichments_applied=[],
            )

        # Compose: original intent + enrichments
        rewritten_parts = [f"User request: {message}"]
        rewritten_parts.extend(additions)
        rewritten = " ".join(rewritten_parts)

        # Infer persona and domain hints
        persona_hint = next(
            (e.split(":")[1] for e in enrichments if e.startswith("audience:")), ""
        )
        domain_hint = next(
            (e.split(":")[1] for e in enrichments if e.startswith("domain:")), ""
        )

        return RewrittenQuery(
            original=message,
            rewritten=rewritten,
            enrichments_applied=enrichments,
            persona_hint=persona_hint,
            domain_hint=domain_hint,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_rewriter: QueryRewriter | None = None


def get_query_rewriter() -> QueryRewriter:
    global _rewriter
    if _rewriter is None:
        _rewriter = QueryRewriter()
    return _rewriter
