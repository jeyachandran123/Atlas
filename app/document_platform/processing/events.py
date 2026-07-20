"""
Processing Events (Objective 3).

Typed domain events, published through an EventPublisher interface. The
default publisher persists to the existing document_processing_events table
(zero schema change) — the interface exists so a future subscriber (Redis
pub/sub for dashboards, notifications, analytics) can attach without the
orchestrator changing at all.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class ProcessingEventType(str, Enum):
    DOCUMENT_QUEUED = "DocumentQueued"
    PROCESSING_STARTED = "DocumentProcessingStarted"
    STAGE_STARTED = "StageStarted"
    STAGE_COMPLETED = "StageCompleted"
    STAGE_SKIPPED = "StageSkipped"
    STAGE_FAILED = "StageFailed"
    STAGE_RETRYING = "StageRetrying"
    PARSER_STARTED = "ParserStarted"
    PARSER_COMPLETED = "ParserCompleted"
    OCR_STARTED = "OCRStarted"
    OCR_COMPLETED = "OCRCompleted"
    NORMALIZATION_COMPLETED = "NormalizationCompleted"
    CHUNKING_COMPLETED = "ChunkingCompleted"
    KNOWLEDGE_BUILT = "KnowledgeBuilt"
    KNOWLEDGE_VALIDATED = "KnowledgeValidated"
    KNOWLEDGE_REGISTERED = "KnowledgeRegistered"
    PROCESSING_COMPLETED = "ProcessingCompleted"
    PROCESSING_FAILED = "ProcessingFailed"
    DEAD_LETTERED = "DeadLettered"


@dataclass(frozen=True)
class ProcessingEvent:
    event_type: ProcessingEventType
    document_id: str
    correlation_id: str
    stage: str = ""
    status: str = "completed"          # completed|failed|skipped|started
    duration_ms: Optional[int] = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventPublisher(ABC):
    @abstractmethod
    async def publish(self, job_id: str, event: ProcessingEvent) -> None: ...


class PersistingEventPublisher(EventPublisher):
    """Writes every event to document_processing_events — today's storage,
    unchanged. Swap or wrap this to fan events out elsewhere later."""

    def __init__(self, repo) -> None:  # ProcessingRepository — avoid import cycle
        self._repo = repo

    async def publish(self, job_id: str, event: ProcessingEvent) -> None:
        detail = dict(event.detail)
        if event.warnings:
            detail["warnings"] = event.warnings
        if event.errors:
            detail["errors"] = event.errors
        await self._repo.add_event(
            job_id=job_id,
            document_id=event.document_id,
            stage=event.stage or event.event_type.value,
            status=event.status,
            duration_ms=event.duration_ms,
            detail=detail or None,
        )
