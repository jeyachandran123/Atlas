"""
Processing persistence — all SQL for Phase 2 entities (jobs, events,
knowledge objects, chunks, metadata, images). Keeps the pipeline free of
queries, per the one-responsibility rule.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Document,
    DocumentChunk,
    DocumentImage,
    DocumentMetadataRow,
    DocumentProcessingEvent,
    DocumentProcessingJob,
    KnowledgeObject,
)
from app.document_platform.processing.chunker import Chunk
from app.document_platform.processing.images import StoredImage
from app.document_platform.processing.knowledge import BuiltKnowledgeObject
from app.document_platform.processing.metadata import ExtractedMetadata


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProcessingRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    @property
    def db(self) -> AsyncSession:
        """The underlying session — shared with sibling services (e.g. KnowledgeRegistry)."""
        return self._db

    # ── Documents (worker scope — unscoped by user) ──────────────────────────

    async def get_document(self, document_id: str) -> Optional[Document]:
        return (
            await self._db.execute(select(Document).where(Document.id == document_id))
        ).scalar_one_or_none()

    async def set_processing_status(self, doc: Document, status: str) -> None:
        doc.processing_status = status
        await self._db.flush()

    # ── Jobs ─────────────────────────────────────────────────────────────────

    async def create_job(
        self, document_id: str, attempt: int = 1, profile: str = "standard"
    ) -> DocumentProcessingJob:
        job = DocumentProcessingJob(document_id=document_id, attempt=attempt, profile=profile)
        self._db.add(job)
        await self._db.flush()
        return job

    async def get_job(self, job_id: str) -> Optional[DocumentProcessingJob]:
        return (
            await self._db.execute(
                select(DocumentProcessingJob).where(DocumentProcessingJob.id == job_id)
            )
        ).scalar_one_or_none()

    async def latest_job_for(self, document_id: str) -> Optional[DocumentProcessingJob]:
        return (
            await self._db.execute(
                select(DocumentProcessingJob)
                .where(DocumentProcessingJob.document_id == document_id)
                .order_by(DocumentProcessingJob.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def job_started(self, job: DocumentProcessingJob) -> None:
        job.status = "processing"
        job.started_at = _now()
        await self._db.flush()

    async def job_stage(self, job: DocumentProcessingJob, stage: str) -> None:
        job.current_stage = stage
        await self._db.flush()

    async def job_finished(
        self,
        job: DocumentProcessingJob,
        status: str,
        error: str | None = None,
        dead_lettered: bool = False,
    ) -> None:
        job.status = status
        job.error = error
        job.dead_lettered = dead_lettered
        job.finished_at = _now()
        await self._db.flush()

    # ── Events ───────────────────────────────────────────────────────────────

    async def add_event(
        self,
        job_id: str,
        document_id: str,
        stage: str,
        status: str,
        duration_ms: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._db.add(
            DocumentProcessingEvent(
                job_id=job_id,
                document_id=document_id,
                stage=stage,
                status=status,
                duration_ms=duration_ms,
                detail_json=json.dumps(detail) if detail else None,
            )
        )
        await self._db.flush()

    async def events_for_job(self, job_id: str) -> list[DocumentProcessingEvent]:
        rows = (
            await self._db.execute(
                select(DocumentProcessingEvent)
                .where(DocumentProcessingEvent.job_id == job_id)
                .order_by(DocumentProcessingEvent.created_at)
            )
        ).scalars().all()
        return list(rows)

    # ── Derived data (idempotent replace) ────────────────────────────────────

    async def wipe_derived(self, document_id: str) -> None:
        """Remove prior processing output so reprocessing is idempotent."""
        await self._db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        await self._db.execute(
            delete(KnowledgeObject).where(KnowledgeObject.document_id == document_id)
        )
        await self._db.execute(
            delete(DocumentMetadataRow).where(DocumentMetadataRow.document_id == document_id)
        )
        await self._db.execute(
            delete(DocumentImage).where(DocumentImage.document_id == document_id)
        )
        await self._db.flush()

    async def persist_knowledge(
        self,
        document_id: str,
        built: BuiltKnowledgeObject,
        metadata: ExtractedMetadata,
        language: str,
        stored_images: list[StoredImage],
        chunks: list[Chunk],
        *,
        parser_version: str = "1.0.0",
        chunk_version: str = "1.0.0",
        processing_version: str = "1.0.0",
        schema_version: str = "1.0.0",
    ) -> KnowledgeObject:
        ko = KnowledgeObject(
            document_id=document_id,
            title=built.title[:500],
            doc_type=built.doc_type,
            language=built.language,
            confidence=built.confidence,
            word_count=built.word_count,
            char_count=built.char_count,
            chunk_count=len(chunks),
            table_count=built.table_count,
            image_count=built.image_count,
            section_count=built.section_count,
            structure_json=json.dumps(built.structure),
            parser_version=parser_version,
            chunk_version=chunk_version,
            processing_version=processing_version,
            schema_version=schema_version,
        )
        self._db.add(ko)
        await self._db.flush()

        for c in chunks:
            self._db.add(
                DocumentChunk(
                    document_id=document_id,
                    knowledge_object_id=ko.id,
                    seq=c.seq,
                    content=c.content,
                    token_count=c.token_count,
                    node_type=c.node_type,
                    section_path=c.section_path[:1000],
                    page=c.page,
                    meta_json=json.dumps(c.meta) if c.meta else None,
                )
            )

        self._db.add(
            DocumentMetadataRow(
                document_id=document_id,
                title=metadata.title[:500],
                author=metadata.author[:255],
                source_created=metadata.source_created[:50],
                source_modified=metadata.source_modified[:50],
                language=language,
                page_count=metadata.page_count,
                sheet_count=metadata.sheet_count,
                slide_count=metadata.slide_count,
                word_count=metadata.word_count,
                char_count=metadata.char_count,
                encoding=metadata.encoding[:30],
                custom_json=json.dumps(metadata.custom) if metadata.custom else None,
            )
        )

        for img in stored_images:
            self._db.add(
                DocumentImage(
                    document_id=document_id,
                    storage_key=img.storage_key,
                    name=img.name[:255],
                    format=img.format[:10],
                    page=img.page,
                    width=img.width,
                    height=img.height,
                    size_bytes=img.size_bytes,
                )
            )

        await self._db.flush()
        return ko

    # ── Read APIs ────────────────────────────────────────────────────────────

    async def knowledge_for(self, document_id: str) -> Optional[KnowledgeObject]:
        return (
            await self._db.execute(
                select(KnowledgeObject).where(KnowledgeObject.document_id == document_id)
            )
        ).scalar_one_or_none()

    async def metadata_for(self, document_id: str) -> Optional[DocumentMetadataRow]:
        return (
            await self._db.execute(
                select(DocumentMetadataRow).where(DocumentMetadataRow.document_id == document_id)
            )
        ).scalar_one_or_none()

    async def images_for(self, document_id: str) -> list[DocumentImage]:
        rows = (
            await self._db.execute(
                select(DocumentImage).where(DocumentImage.document_id == document_id)
            )
        ).scalars().all()
        return list(rows)

    async def chunks_for(
        self, document_id: str, limit: int, offset: int
    ) -> tuple[list[DocumentChunk], int]:
        from sqlalchemy import func
        total = (
            await self._db.execute(
                select(func.count()).select_from(DocumentChunk).where(
                    DocumentChunk.document_id == document_id
                )
            )
        ).scalar_one()
        rows = (
            await self._db.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.seq)
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return list(rows), int(total)
