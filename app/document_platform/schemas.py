"""
DIP API schemas.

Security note: storage_bucket and storage_key are internal — no schema in this
file exposes them, and DocumentOut is the ONLY shape a Document ever leaves
the API in.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.db.models import Document


class DocumentOut(BaseModel):
    id: str
    filename: str
    extension: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str
    upload_status: str
    processing_status: str = "none"
    version: int
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, doc: Document) -> "DocumentOut":
        tags: list[str] = []
        if doc.tags_json:
            try:
                parsed = json.loads(doc.tags_json)
                if isinstance(parsed, list):
                    tags = [str(t) for t in parsed]
            except ValueError:
                pass
        return cls(
            id=doc.id,
            filename=doc.original_filename,
            extension=doc.extension,
            mime_type=doc.mime_type,
            size_bytes=doc.size_bytes,
            checksum_sha256=doc.checksum_sha256,
            upload_status=doc.upload_status,
            processing_status=getattr(doc, "processing_status", "none"),
            version=doc.version,
            tags=tags,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )


class DocumentListOut(BaseModel):
    items: list[DocumentOut]
    total: int
    limit: int
    offset: int


class UploadResponse(BaseModel):
    document: DocumentOut
    duplicate_of: Optional[str] = None  # set when an identical file already existed


class DownloadLinkOut(BaseModel):
    """A time-limited signed URL. Raw storage paths are never exposed."""
    document_id: str
    url: str
    expires_in_seconds: int


class DeleteResponse(BaseModel):
    id: str
    deleted: bool


class ErrorDetail(BaseModel):
    """Stable machine-readable error body for validation failures."""
    code: str
    message: str


# ── Phase 2: processing & knowledge shapes ───────────────────────────────────


class ProcessingEventOut(BaseModel):
    stage: str
    status: str
    duration_ms: Optional[int] = None
    detail: Optional[dict] = None
    created_at: datetime


class ProcessingStateOut(BaseModel):
    document_id: str
    processing_status: str
    job_status: Optional[str] = None
    current_stage: Optional[str] = None
    attempt: Optional[int] = None
    error: Optional[str] = None
    events: list[ProcessingEventOut] = Field(default_factory=list)


class DocumentImageOut(BaseModel):
    id: str
    name: str
    format: str
    page: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    size_bytes: int


class KnowledgeMetadataOut(BaseModel):
    title: str = ""
    author: str = ""
    language: str = "unknown"
    page_count: Optional[int] = None
    sheet_count: Optional[int] = None
    slide_count: Optional[int] = None
    word_count: int = 0
    char_count: int = 0
    encoding: str = "utf-8"
    custom: Optional[dict] = None


class KnowledgeObjectOut(BaseModel):
    id: str
    document_id: str
    title: str
    doc_type: str
    language: str
    confidence: float
    word_count: int
    char_count: int
    chunk_count: int
    table_count: int
    image_count: int
    section_count: int
    structure: Optional[dict] = None
    metadata: Optional[KnowledgeMetadataOut] = None
    images: list[DocumentImageOut] = Field(default_factory=list)
    created_at: datetime


class ChunkOut(BaseModel):
    id: str
    seq: int
    content: str
    token_count: int
    node_type: str
    section_path: str
    page: Optional[int] = None
    meta: Optional[dict] = None


class ChunkListOut(BaseModel):
    document_id: str
    items: list[ChunkOut]
    total: int
    limit: int
    offset: int


class ReprocessResponse(BaseModel):
    document_id: str
    job_id: str
    queued: bool = True
