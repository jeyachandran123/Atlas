"""
Semantic Events (Objective 11) — a third event domain, distinct from
ProcessingEvent (pipeline stages) and KnowledgeEvent (content lifecycle).
This one covers what happened to an embedding as a semantic artifact.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from app.document_platform.semantic.lifecycle import EmbeddingLifecycle


class SemanticEventType(str, Enum):
    EMBEDDING_QUEUED = "EmbeddingQueued"
    EMBEDDING_STARTED = "EmbeddingStarted"
    EMBEDDING_GENERATED = "EmbeddingGenerated"
    EMBEDDING_VALIDATED = "EmbeddingValidated"
    EMBEDDING_REGISTERED = "EmbeddingRegistered"
    EMBEDDING_INDEXED = "EmbeddingIndexed"
    EMBEDDING_VERIFIED = "EmbeddingVerified"
    EMBEDDING_DEPRECATED = "EmbeddingDeprecated"
    EMBEDDING_SUPERSEDED = "EmbeddingSuperseded"
    EMBEDDING_ARCHIVED = "EmbeddingArchived"
    EMBEDDING_DELETED = "EmbeddingDeleted"
    STAGE_FAILED = "SemanticStageFailed"
    STAGE_RETRYING = "SemanticStageRetrying"
    DEAD_LETTERED = "EmbeddingDeadLettered"


@dataclass(frozen=True)
class SemanticEvent:
    event_type: SemanticEventType
    knowledge_id: str
    correlation_id: str
    embedding_id: Optional[str] = None
    provider: str = ""
    version: str = "1.0.0"
    latency_ms: Optional[int] = None
    previous_state: Optional[EmbeddingLifecycle] = None
    current_state: Optional[EmbeddingLifecycle] = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SemanticEventPublisher(ABC):
    @abstractmethod
    async def publish(self, job_id: str, event: SemanticEvent) -> None: ...


class PersistingSemanticEventPublisher(SemanticEventPublisher):
    def __init__(self, repo) -> None:  # SemanticRepository — avoid import cycle
        self._repo = repo

    async def publish(self, job_id: str, event: SemanticEvent) -> None:
        await self._repo.add_semantic_event(job_id, event)
