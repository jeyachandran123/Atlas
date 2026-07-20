"""
DIP service layer — the only place DIP business rules live.

Upload flow:
    validate → UUID → secure name → blob PUT → metadata row → audit → response

Failure semantics: the metadata row is written in status "uploading" BEFORE the
blob PUT and promoted to "completed" after — a crash mid-upload leaves an
inspectable "failed"/"uploading" row instead of an orphaned blob, and later
phases can reconcile. Deletes are soft: metadata is tombstoned, the blob is
retained for recovery/compliance (hard purge is a later lifecycle phase).
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

from loguru import logger

from app.config import get_settings
from app.db.models import Document
from app.document_platform.audit import DocumentAuditLogger
from app.document_platform.constants import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_UPLOADING,
    STORAGE_PREFIX,
)
from app.document_platform.repository import DocumentRepository
from app.document_platform.validation import UploadValidator, ValidatedUpload
from app.storage import get_blob_storage
from app.storage.base import BlobNotFoundError, BlobStorage


class DocumentNotFoundError(Exception):
    """No such document for this user (or it is deleted)."""


class DuplicateDocumentError(Exception):
    """An identical file (same checksum) already exists for this user."""

    def __init__(self, existing_id: str) -> None:
        self.existing_id = existing_id
        super().__init__(f"Duplicate of document {existing_id}")


class DocumentPlatformService:
    """
    Orchestrates DIP operations. All collaborators are injected — swap any of
    them (storage provider, repository, validator) without touching this class.
    """

    def __init__(
        self,
        repository: DocumentRepository,
        audit: DocumentAuditLogger,
        storage: Optional[BlobStorage] = None,
        validator: Optional[UploadValidator] = None,
    ) -> None:
        cfg = get_settings()
        self._repo = repository
        self._audit = audit
        self._storage = storage or get_blob_storage(STORAGE_PREFIX)
        self._validator = validator or UploadValidator(
            max_size_bytes=cfg.dip_max_file_size_mb * 1024 * 1024
        )
        self._provider = cfg.storage_backend
        self._bucket = cfg.aws_s3_bucket if cfg.storage_backend == "s3" else None
        self._signed_ttl = cfg.dip_signed_url_ttl_seconds

    # ── Upload ────────────────────────────────────────────────────────────────

    async def upload(
        self,
        *,
        org_id: str,
        user_id: str,
        filename: str | None,
        content: bytes,
        declared_mime: str | None,
        tags: Optional[list[str]] = None,
        allow_duplicate: bool = False,
        request_id: Optional[str] = None,
    ) -> tuple[Document, Optional[str]]:
        """
        Returns (document, duplicate_of). Raises DocumentValidationError or
        DuplicateDocumentError (when allow_duplicate is False).
        """
        v: ValidatedUpload = self._validator.validate(filename, content, declared_mime)

        existing = await self._repo.find_duplicate(user_id, v.checksum_sha256)
        if existing:
            if not allow_duplicate:
                await self._audit.log(
                    "duplicate_rejected", org_id, user_id, existing.id,
                    {"filename": v.safe_filename, "checksum": v.checksum_sha256},
                    request_id,
                )
                raise DuplicateDocumentError(existing.id)
            duplicate_of: Optional[str] = existing.id
        else:
            duplicate_of = None

        document_id = str(uuid.uuid4())
        stored_filename = f"{document_id}{v.extension}"
        storage_key = f"{user_id}/{stored_filename}"

        doc = Document(
            id=document_id,
            org_id=org_id,
            uploaded_by=user_id,
            original_filename=v.safe_filename,
            stored_filename=stored_filename,
            extension=v.extension,
            mime_type=v.mime_type,
            size_bytes=v.size_bytes,
            checksum_sha256=v.checksum_sha256,
            storage_provider=self._provider,
            storage_bucket=self._bucket,
            storage_key=storage_key,
            upload_status=STATUS_UPLOADING,
            tags_json=json.dumps(tags) if tags else None,
        )
        await self._repo.create(doc)

        try:
            await self._storage.put(storage_key, content, v.mime_type)
        except Exception as e:
            await self._repo.mark_status(doc, STATUS_FAILED)
            await self._audit.log(
                "upload_failed", org_id, user_id, document_id,
                {"filename": v.safe_filename, "error": str(e)}, request_id,
            )
            logger.error(f"DIP upload failed for {document_id}: {e}")
            raise

        await self._repo.mark_status(doc, STATUS_COMPLETED)
        await self._audit.log(
            "upload", org_id, user_id, document_id,
            {
                "filename": v.safe_filename,
                "size_bytes": v.size_bytes,
                "mime": v.mime_type,
                "checksum": v.checksum_sha256,
            },
            request_id,
        )

        # Phase 2 hook: every completed upload enters the processing pipeline.
        # Best-effort — a queue outage must never fail the upload itself.
        try:
            await self._enqueue_processing(doc)
        except Exception as e:
            logger.warning(f"Processing enqueue failed for {document_id} (upload still OK): {e}")

        return doc, duplicate_of

    # ── Phase 2: processing pipeline integration ──────────────────────────────

    async def _enqueue_processing(self, doc: Document, attempt: int = 1) -> str:
        from app.document_platform.processing.persistence import ProcessingRepository
        from app.document_platform.processing.queue import enqueue_processing_job

        proc = ProcessingRepository(self._repo.db)  # same session/transaction
        job = await proc.create_job(doc.id, attempt=attempt)
        await proc.set_processing_status(doc, "queued")
        await enqueue_processing_job(doc.id, job.id, attempt)
        return job.id

    async def reprocess(self, user_id: str, document_id: str) -> str:
        """Re-enqueue a document through the pipeline (idempotent)."""
        doc = await self.get(user_id, document_id)
        from app.document_platform.processing.persistence import ProcessingRepository
        prior = await ProcessingRepository(self._repo.db).latest_job_for(doc.id)
        attempt = (prior.attempt + 1) if prior else 1
        return await self._enqueue_processing(doc, attempt=attempt)

    async def processing_state(self, user_id: str, document_id: str):
        """(document, latest job | None, events) — ownership enforced."""
        doc = await self.get(user_id, document_id)
        from app.document_platform.processing.persistence import ProcessingRepository
        proc = ProcessingRepository(self._repo.db)
        job = await proc.latest_job_for(doc.id)
        events = await proc.events_for_job(job.id) if job else []
        return doc, job, events

    async def knowledge(self, user_id: str, document_id: str):
        """(document, knowledge object | None, metadata | None, images)."""
        doc = await self.get(user_id, document_id)
        from app.document_platform.processing.persistence import ProcessingRepository
        proc = ProcessingRepository(self._repo.db)
        return (
            doc,
            await proc.knowledge_for(doc.id),
            await proc.metadata_for(doc.id),
            await proc.images_for(doc.id),
        )

    async def chunks(self, user_id: str, document_id: str, limit: int, offset: int):
        doc = await self.get(user_id, document_id)
        from app.document_platform.processing.persistence import ProcessingRepository
        return await ProcessingRepository(self._repo.db).chunks_for(doc.id, limit, offset)

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get(self, user_id: str, document_id: str) -> Document:
        doc = await self._repo.get_owned(document_id, user_id)
        if not doc:
            raise DocumentNotFoundError(document_id)
        return doc

    async def list(
        self,
        user_id: str,
        limit: int,
        offset: int,
        search: Optional[str] = None,
        extension: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[list[Document], int]:
        return await self._repo.list_owned(
            user_id, limit=limit, offset=offset,
            search=search, extension=extension, status=status,
        )

    # ── Download ──────────────────────────────────────────────────────────────

    async def download_link(
        self, org_id: str, user_id: str, document_id: str,
        request_id: Optional[str] = None,
    ) -> Optional[tuple[str, int]]:
        """
        Signed URL for direct download, or None when the active storage
        backend cannot mint one (caller falls back to proxy bytes).
        """
        doc = await self.get(user_id, document_id)
        url = await self._storage.signed_url(
            doc.storage_key,
            expires_in=self._signed_ttl,
            download_filename=doc.original_filename,
        )
        if url is None:
            return None
        await self._audit.log(
            "download", org_id, user_id, document_id,
            {"mode": "signed_url"}, request_id,
        )
        return url, self._signed_ttl

    async def download_bytes(
        self, org_id: str, user_id: str, document_id: str,
        request_id: Optional[str] = None,
    ) -> tuple[Document, bytes]:
        """Proxy download — used when signed URLs are unavailable (local backend)."""
        doc = await self.get(user_id, document_id)
        try:
            data = await self._storage.get(doc.storage_key)
        except BlobNotFoundError:
            raise DocumentNotFoundError(document_id)
        await self._audit.log(
            "download", org_id, user_id, document_id,
            {"mode": "proxy"}, request_id,
        )
        return doc, data

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete(
        self, org_id: str, user_id: str, document_id: str,
        request_id: Optional[str] = None,
    ) -> None:
        doc = await self.get(user_id, document_id)
        await self._repo.soft_delete(doc)
        await self._audit.log(
            "delete", org_id, user_id, document_id,
            {"filename": doc.original_filename}, request_id,
        )
