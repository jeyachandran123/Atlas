"""
Embedding Registry (Objective 6) — the source of truth for every embedding
vector's metadata. Owns EmbeddingRecord lifecycle transitions and their
audit trail; the orchestrator never writes embedding_records directly.
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from app.db.models import EmbeddingRecord
from app.document_platform.semantic.events import (
    SemanticEvent,
    SemanticEventPublisher,
    SemanticEventType,
)
from app.document_platform.semantic.lifecycle import EmbeddingLifecycle, validate_transition
from app.document_platform.semantic.providers import EmbeddingResult
from app.document_platform.semantic.repository import SemanticRepository


def vector_checksum(vector: list[float]) -> str:
    """Deterministic fingerprint of a vector — used for dedup/integrity, not the vector itself."""
    payload = json.dumps([round(x, 8) for x in vector])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class EmbeddingRegistry:
    def __init__(self, repo: SemanticRepository, events: SemanticEventPublisher) -> None:
        self._repo = repo
        self._events = events

    async def register(
        self,
        *,
        job_id: str,
        knowledge_id: str,
        chunk_id: str,
        result: EmbeddingResult,
        provider_name: str,
        provider_version: str,
        model_name: str,
        model_version: str,
        embedding_version: str,
        correlation_id: str,
    ) -> EmbeddingRecord:
        record = EmbeddingRecord(
            knowledge_id=knowledge_id,
            chunk_id=chunk_id,
            embedding_version=embedding_version,
            provider_name=provider_name,
            provider_version=provider_version,
            model_name=model_name,
            model_version=model_version,
            dimension=len(result.vector),
            vector_checksum=vector_checksum(result.vector),
            status=EmbeddingLifecycle.QUEUED.value,
            latency_ms=result.latency_ms,
            correlation_id=correlation_id,
        )
        await self._repo.create_embedding_record(record)
        await self._events.publish(job_id, SemanticEvent(
            event_type=SemanticEventType.EMBEDDING_REGISTERED,
            knowledge_id=knowledge_id, correlation_id=correlation_id,
            embedding_id=record.id, provider=provider_name, version=embedding_version,
            latency_ms=result.latency_ms,
        ))

        await self.transition(job_id, record, EmbeddingLifecycle.GENERATING, SemanticEventType.EMBEDDING_STARTED, correlation_id)
        await self.transition(job_id, record, EmbeddingLifecycle.VALIDATING, SemanticEventType.EMBEDDING_VALIDATED, correlation_id)
        return record

    async def mark_indexed(self, job_id: str, record: EmbeddingRecord, correlation_id: str) -> None:
        await self.transition(job_id, record, EmbeddingLifecycle.INDEXED, SemanticEventType.EMBEDDING_INDEXED, correlation_id)
        await self.transition(job_id, record, EmbeddingLifecycle.VERIFIED, SemanticEventType.EMBEDDING_VERIFIED, correlation_id)

    async def transition(
        self, job_id: str, record: EmbeddingRecord, target: EmbeddingLifecycle,
        event_type: SemanticEventType, correlation_id: str,
    ) -> None:
        current = EmbeddingLifecycle(record.status)
        validate_transition(current, target)
        record.status = target.value
        await self._repo.db.flush()
        await self._events.publish(job_id, SemanticEvent(
            event_type=event_type, knowledge_id=record.knowledge_id, correlation_id=correlation_id,
            embedding_id=record.id, provider=record.provider_name, version=record.embedding_version,
            previous_state=current, current_state=target,
        ))

    async def find_duplicate(self, chunk_id: str, embedding_version: str) -> Optional[EmbeddingRecord]:
        return await self._repo.find_duplicate(chunk_id, embedding_version)
