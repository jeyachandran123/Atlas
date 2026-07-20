"""
Knowledge Domain Events (Objective 2) — distinct from Phase 2's
ProcessingEvent. ProcessingEvent records what a PIPELINE STAGE did
(load/parse/chunk/...); KnowledgeEvent records what happened to a piece of
KNOWLEDGE as a content entity (created, activated, deprecated, superseded).
Different domain, different audience (analytics/automation/dashboards vs.
pipeline debugging) — kept separate rather than overloading one event type.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from app.document_platform.knowledge.lifecycle import KnowledgeLifecycle


class KnowledgeEventType(str, Enum):
    CREATED = "KnowledgeCreated"
    UPDATED = "KnowledgeUpdated"
    VALIDATED = "KnowledgeValidated"
    ACTIVATED = "KnowledgeActivated"
    VERSION_CREATED = "KnowledgeVersionCreated"
    EMBEDDED = "KnowledgeEmbedded"
    INDEXED = "KnowledgeIndexed"
    DEPRECATED = "KnowledgeDeprecated"
    SUPERSEDED = "KnowledgeSuperseded"
    ARCHIVED = "KnowledgeArchived"
    DELETED = "KnowledgeDeleted"
    RECOVERED = "KnowledgeRecovered"


@dataclass(frozen=True)
class KnowledgeEvent:
    event_type: KnowledgeEventType
    knowledge_id: str
    document_id: str
    correlation_id: str
    previous_state: Optional[KnowledgeLifecycle] = None
    current_state: Optional[KnowledgeLifecycle] = None
    version: str = "1.0.0"
    source: str = "system"
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class KnowledgeEventPublisher(ABC):
    @abstractmethod
    async def publish(self, event: KnowledgeEvent) -> None: ...


class PersistingKnowledgeEventPublisher(KnowledgeEventPublisher):
    """Writes to the knowledge_events table (Objective 2's dedicated store)."""

    def __init__(self, repo) -> None:  # KnowledgeManifestRepository — avoid import cycle
        self._repo = repo

    async def publish(self, event: KnowledgeEvent) -> None:
        await self._repo.add_knowledge_event(event)
