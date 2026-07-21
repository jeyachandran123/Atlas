"""Generation Events (Objective 16) — append-only, persisted."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from app.document_platform.generation.repository import GenerationRepository


class GenerationEventType(str, Enum):
    GENERATION_REQUESTED = "generation_requested"
    PLAN_COMPLETED = "plan_completed"
    TRANSFORM_COMPLETED = "transform_completed"
    BUILD_COMPLETED = "build_completed"
    ARTIFACT_STORED = "artifact_stored"
    ARTIFACT_READY = "artifact_ready"
    ARTIFACT_DOWNLOADED = "artifact_downloaded"
    GENERATION_FAILED = "generation_failed"


@dataclass(frozen=True)
class GenerationEvent:
    event_type: GenerationEventType
    artifact_id: str
    correlation_id: str
    status: str = "completed"
    duration_ms: Optional[int] = None
    detail: dict[str, Any] = field(default_factory=dict)


class GenerationEventPublisher(ABC):
    @abstractmethod
    async def publish(self, event: GenerationEvent) -> None: ...


class PersistingGenerationEventPublisher(GenerationEventPublisher):
    def __init__(self, repository: "GenerationRepository") -> None:
        self._repo = repository

    async def publish(self, event: GenerationEvent) -> None:
        await self._repo.add_event(event)
