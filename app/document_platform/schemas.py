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
