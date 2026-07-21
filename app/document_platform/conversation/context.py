"""Conversation Context (Objective 1) — the typed state object one turn
carries through every layer, mirroring the context-object pattern the
processing and semantic orchestrators established."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.document_platform.conversation.intent import IntentType
    from app.document_platform.conversation.planner import ConversationPlan


@dataclass
class ConversationContext:
    conversation_id: str
    turn_id: str
    user_id: str
    org_id: str
    question: str
    correlation_id: str
    document_id: Optional[str] = None  # optional single-document scope
    intent: Optional["IntentType"] = None
    plan: Optional["ConversationPlan"] = None
    warnings: list[str] = field(default_factory=list)
