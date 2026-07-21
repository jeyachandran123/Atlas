"""All SQL for the Generation layer (Generation Registry, Objective 14)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GenerationArtifact, GenerationEventRecord
from app.document_platform.generation.events import GenerationEvent
from app.document_platform.generation.lifecycle import (
    GenerationLifecycle,
    validate_transition,
)
from app.document_platform.generation.metrics import GenerationMetrics


def _now() -> datetime:
    return datetime.now(timezone.utc)


class GenerationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_artifact(
        self, user_id: str, org_id: str, prompt: str, format_name: str,
        source_document_id: str | None = None,
    ) -> GenerationArtifact:
        artifact = GenerationArtifact(
            user_id=user_id, org_id=org_id, prompt=prompt, format=format_name,
            source_document_id=source_document_id,
        )
        self._db.add(artifact)
        await self._db.flush()
        return artifact

    async def get_artifact(
        self, artifact_id: str, user_id: str,
    ) -> Optional[GenerationArtifact]:
        return (
            await self._db.execute(
                select(GenerationArtifact).where(
                    GenerationArtifact.id == artifact_id,
                    GenerationArtifact.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    async def list_artifacts(
        self, user_id: str, limit: int = 50,
    ) -> list[GenerationArtifact]:
        rows = (
            await self._db.execute(
                select(GenerationArtifact)
                .where(GenerationArtifact.user_id == user_id)
                .order_by(GenerationArtifact.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def transition(
        self, artifact: GenerationArtifact, new_state: GenerationLifecycle,
    ) -> None:
        validate_transition(GenerationLifecycle(artifact.status), new_state)
        artifact.status = new_state.value
        await self._db.flush()

    async def finish_artifact(
        self, artifact: GenerationArtifact, *, metrics: GenerationMetrics,
        title: str = "", filename: str = "", storage_key: str = "",
        content_type: str = "", checksum: str = "", size_bytes: int = 0,
        builder_name: str = "", builder_version: str = "",
        grounded: bool = False, source_knowledge_ids: list[str] | None = None,
        llm_provider: str = "", llm_model: str = "", error: str | None = None,
    ) -> None:
        artifact.title = title[:300]
        artifact.filename = filename[:255]
        artifact.storage_key = storage_key
        artifact.content_type = content_type
        artifact.checksum = checksum
        artifact.size_bytes = size_bytes
        artifact.builder_name = builder_name
        artifact.builder_version = builder_version
        artifact.grounded = grounded
        artifact.source_knowledge_ids_json = (
            json.dumps(source_knowledge_ids) if source_knowledge_ids else None
        )
        artifact.planning_ms = metrics.planning_ms
        artifact.transform_ms = metrics.transform_ms
        artifact.build_ms = metrics.build_ms
        artifact.store_ms = metrics.store_ms
        artifact.total_ms = metrics.total_ms
        artifact.prompt_tokens = metrics.prompt_tokens
        artifact.completion_tokens = metrics.completion_tokens
        artifact.llm_provider = llm_provider
        artifact.llm_model = llm_model
        artifact.error = error
        artifact.finished_at = _now()
        await self._db.flush()

    async def add_event(self, event: GenerationEvent) -> None:
        self._db.add(GenerationEventRecord(
            artifact_id=event.artifact_id,
            event_type=event.event_type.value,
            status=event.status,
            duration_ms=event.duration_ms,
            detail_json=json.dumps(event.detail) if event.detail else None,
            correlation_id=event.correlation_id,
        ))
        await self._db.flush()

    async def events_for_artifact(self, artifact_id: str) -> list[GenerationEventRecord]:
        rows = (
            await self._db.execute(
                select(GenerationEventRecord)
                .where(GenerationEventRecord.artifact_id == artifact_id)
                .order_by(GenerationEventRecord.created_at)
            )
        ).scalars().all()
        return list(rows)
