"""
All SQL for the Semantic layer lives here — the orchestrator and registries
never issue queries themselves. Read-only access into the frozen Knowledge
Platform tables (knowledge_objects, document_chunks) is also centralized
here so nothing else needs to import Phase 2 models directly.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Document,
    DocumentChunk,
    EmbeddingEventRecord,
    EmbeddingJob,
    EmbeddingRecord,
    KnowledgeObject,
    SemanticIndex,
    SemanticManifest,
)
from app.document_platform.semantic.events import SemanticEvent


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SemanticRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    @property
    def db(self) -> AsyncSession:
        return self._db

    # ── Read-only access into the frozen Knowledge Platform ─────────────────

    async def get_knowledge(self, knowledge_id: str) -> Optional[KnowledgeObject]:
        return (
            await self._db.execute(select(KnowledgeObject).where(KnowledgeObject.id == knowledge_id))
        ).scalar_one_or_none()

    async def get_document(self, document_id: str) -> Optional[Document]:
        return (
            await self._db.execute(select(Document).where(Document.id == document_id))
        ).scalar_one_or_none()

    async def update_knowledge_embedding_status(self, knowledge_id: str, status: str) -> None:
        """
        Writes to KnowledgeObject.embedding_status — a column Phase 2.5
        added specifically as a placeholder for this phase to populate
        ("Future Embedding Status... nothing writes non-default values to
        them yet"). This is using existing, documented scaffolding, not a
        modification to Knowledge Platform business logic.
        """
        ko = await self.get_knowledge(knowledge_id)
        if ko is not None:
            ko.embedding_status = status
            await self._db.flush()

    async def get_chunks(self, knowledge_id: str) -> list[DocumentChunk]:
        rows = (
            await self._db.execute(
                select(DocumentChunk)
                .where(DocumentChunk.knowledge_object_id == knowledge_id)
                .order_by(DocumentChunk.seq)
            )
        ).scalars().all()
        return list(rows)

    # ── Jobs ─────────────────────────────────────────────────────────────────

    async def create_job(
        self, knowledge_id: str, attempt: int = 1, correlation_id: str | None = None,
    ) -> EmbeddingJob:
        job = EmbeddingJob(knowledge_id=knowledge_id, attempt=attempt)
        if correlation_id:
            job.correlation_id = correlation_id
        self._db.add(job)
        await self._db.flush()
        return job

    async def get_job(self, job_id: str) -> Optional[EmbeddingJob]:
        return (
            await self._db.execute(select(EmbeddingJob).where(EmbeddingJob.id == job_id))
        ).scalar_one_or_none()

    async def latest_job_for(self, knowledge_id: str) -> Optional[EmbeddingJob]:
        return (
            await self._db.execute(
                select(EmbeddingJob)
                .where(EmbeddingJob.knowledge_id == knowledge_id)
                .order_by(EmbeddingJob.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def job_started(self, job: EmbeddingJob) -> None:
        job.status = "generating"
        job.started_at = _now()
        await self._db.flush()

    async def job_stage(self, job: EmbeddingJob, stage: str) -> None:
        job.current_stage = stage
        await self._db.flush()

    async def job_finished(
        self, job: EmbeddingJob, status: str, error: str | None = None, dead_lettered: bool = False,
    ) -> None:
        job.status = status
        job.error = error
        job.dead_lettered = dead_lettered
        job.finished_at = _now()
        await self._db.flush()

    # ── Events ───────────────────────────────────────────────────────────────

    async def add_semantic_event(self, job_id: str, event: SemanticEvent) -> None:
        detail = dict(event.detail)
        if event.warnings:
            detail["warnings"] = event.warnings
        if event.errors:
            detail["errors"] = event.errors
        if event.provider:
            detail["provider"] = event.provider
        self._db.add(EmbeddingEventRecord(
            job_id=job_id,
            knowledge_id=event.knowledge_id,
            embedding_id=event.embedding_id,
            event_type=event.event_type.value,
            status="failed" if event.errors else "completed",
            duration_ms=event.latency_ms,
            detail_json=json.dumps(detail) if detail else None,
        ))
        await self._db.flush()

    async def events_for_job(self, job_id: str) -> list[EmbeddingEventRecord]:
        rows = (
            await self._db.execute(
                select(EmbeddingEventRecord)
                .where(EmbeddingEventRecord.job_id == job_id)
                .order_by(EmbeddingEventRecord.created_at)
            )
        ).scalars().all()
        return list(rows)

    # ── Embedding records (Embedding Registry, Objective 6) ──────────────────

    async def wipe_embeddings_for_knowledge(self, knowledge_id: str) -> None:
        """
        Idempotent re-embedding support, called by EmbeddingOrchestrator at
        the start of its OWN run — deliberately leaves embedding_jobs alone,
        since the CURRENT job (the one this run is executing under) already
        exists as a row when this runs; bulk-deleting it out from under the
        orchestrator would break later job_finished()/job_stage() updates.
        """
        await self._db.execute(delete(EmbeddingRecord).where(EmbeddingRecord.knowledge_id == knowledge_id))
        await self._db.execute(delete(SemanticManifest).where(SemanticManifest.knowledge_id == knowledge_id))
        await self._db.flush()

    async def wipe_all_semantic_for_document_reprocess(self, knowledge_id: str) -> None:
        """
        Used ONLY by document_worker.py before a document reprocess replaces
        this knowledge_id entirely (the frozen ProcessingOrchestrator is
        about to delete the knowledge_objects row itself). Unlike
        wipe_embeddings_for_knowledge, this also clears embedding_jobs —
        safe here because the knowledge_id is about to stop existing
        regardless, superseding anything still referencing it.

        embedding_events cascades automatically at the database level
        (ON DELETE CASCADE — see migration 0011): a two-statement
        delete-events-then-delete-jobs from application code left a real
        window where a concurrently running embedding worker (a different
        process) could commit a new event for the very job being deleted,
        between the two statements. Letting Postgres cascade it as part of
        one DELETE closes that race entirely; if the other worker's insert
        loses the race, IT fails safely (caught by its own try/except) —
        an acceptable outcome for a job whose knowledge_id no longer exists.
        """
        await self._db.execute(delete(EmbeddingRecord).where(EmbeddingRecord.knowledge_id == knowledge_id))
        await self._db.execute(delete(EmbeddingJob).where(EmbeddingJob.knowledge_id == knowledge_id))
        await self._db.execute(delete(SemanticManifest).where(SemanticManifest.knowledge_id == knowledge_id))
        await self._db.flush()

    async def create_embedding_record(self, record: EmbeddingRecord) -> EmbeddingRecord:
        self._db.add(record)
        await self._db.flush()
        return record

    async def find_duplicate(self, chunk_id: str, embedding_version: str) -> Optional[EmbeddingRecord]:
        return (
            await self._db.execute(
                select(EmbeddingRecord).where(
                    EmbeddingRecord.chunk_id == chunk_id,
                    EmbeddingRecord.embedding_version == embedding_version,
                )
            )
        ).scalar_one_or_none()

    async def list_embeddings_for_knowledge(
        self, knowledge_id: str, limit: int, offset: int,
    ) -> tuple[list[EmbeddingRecord], int]:
        total = (
            await self._db.execute(
                select(func.count()).select_from(EmbeddingRecord)
                .where(EmbeddingRecord.knowledge_id == knowledge_id)
            )
        ).scalar_one()
        rows = (
            await self._db.execute(
                select(EmbeddingRecord)
                .where(EmbeddingRecord.knowledge_id == knowledge_id)
                .order_by(EmbeddingRecord.created_at)
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return list(rows), int(total)

    # ── Semantic manifest (Semantic Registry, Objective 8) ───────────────────

    async def create_semantic_manifest(self, manifest: SemanticManifest) -> SemanticManifest:
        self._db.add(manifest)
        await self._db.flush()
        return manifest

    async def get_semantic_manifest(self, knowledge_id: str) -> Optional[SemanticManifest]:
        return (
            await self._db.execute(
                select(SemanticManifest).where(SemanticManifest.knowledge_id == knowledge_id)
            )
        ).scalar_one_or_none()

    # ── Semantic index (Objective 9) ──────────────────────────────────────────

    async def get_index(self, collection_name: str, embedding_version: str) -> Optional[SemanticIndex]:
        return (
            await self._db.execute(
                select(SemanticIndex).where(
                    SemanticIndex.collection_name == collection_name,
                    SemanticIndex.embedding_version == embedding_version,
                )
            )
        ).scalar_one_or_none()

    async def create_index(self, index: SemanticIndex) -> SemanticIndex:
        self._db.add(index)
        await self._db.flush()
        return index

    async def update_index_stats(self, index: SemanticIndex, vector_count: int, status: str) -> None:
        index.vector_count = vector_count
        index.status = status
        await self._db.flush()
