"""Conversation Events (Objective 14) — typed domain events for analytics
and monitoring, persisted append-only like every other event stream in the
platform (processing, knowledge, embedding)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from app.document_platform.conversation.repository import ConversationRepository


class ConversationEventType(str, Enum):
    CONVERSATION_STARTED = "conversation_started"
    INTENT_DETECTED = "intent_detected"
    RETRIEVAL_COMPLETED = "retrieval_completed"
    RANKING_COMPLETED = "ranking_completed"
    CONTEXT_BUILT = "context_built"
    PROMPT_GENERATED = "prompt_generated"
    REASONING_COMPLETED = "reasoning_completed"
    RESPONSE_VALIDATED = "response_validated"
    RESPONSE_STREAM_STARTED = "response_stream_started"
    RESPONSE_COMPLETED = "response_completed"
    RESPONSE_FAILED = "response_failed"


@dataclass(frozen=True)
class ConversationEvent:
    event_type: ConversationEventType
    conversation_id: str
    correlation_id: str
    turn_id: Optional[str] = None
    status: str = "completed"
    duration_ms: Optional[int] = None
    detail: dict[str, Any] = field(default_factory=dict)


class ConversationEventPublisher(ABC):
    @abstractmethod
    async def publish(self, event: ConversationEvent) -> None: ...


class PersistingConversationEventPublisher(ConversationEventPublisher):
    def __init__(self, repository: "ConversationRepository") -> None:
        self._repo = repository

    async def publish(self, event: ConversationEvent) -> None:
        await self._repo.add_event(event)
