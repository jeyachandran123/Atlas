"""
Conversation Planner (Objective 3) — pure decision layer: intent in, plan
out. No I/O. The gateway executes the plan; keeping decisions and execution
separate is what lets future strategies change one without the other.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.document_platform.conversation.intent import IntentType


@dataclass(frozen=True)
class ConversationPlan:
    intent: IntentType
    retrieval_strategy: str = "semantic"
    top_k: int = 8
    scope: str = "org"                    # "org" | "document"
    require_citations: bool = True
    reasoning_strategy: str = "grounded_answer"
    response_format: str = "markdown"
    retrieve: bool = True


class ConversationPlanner:
    def __init__(self, default_top_k: int) -> None:
        self._default_top_k = default_top_k

    def plan(self, intent: IntentType, document_id: str | None = None) -> ConversationPlan:
        scope = "document" if document_id else "org"
        if intent is IntentType.UNSUPPORTED:
            return ConversationPlan(
                intent=intent, retrieve=False, require_citations=False,
                reasoning_strategy="refuse", top_k=0, scope=scope,
            )
        if intent is IntentType.SUMMARIZATION:
            # Summaries need broader coverage of the source material.
            return ConversationPlan(intent=intent, top_k=self._default_top_k * 2, scope=scope)
        if intent is IntentType.COMPARISON:
            return ConversationPlan(intent=intent, top_k=int(self._default_top_k * 1.5), scope=scope)
        return ConversationPlan(intent=intent, top_k=self._default_top_k, scope=scope)
