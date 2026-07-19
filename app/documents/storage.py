"""
Document Storage — persistence of uploaded documents and their extracted text.

Storage is delegated to the pluggable blob backend (app/storage):
  STORAGE_BACKEND=local    → data/document_uploads/{conversation_id}/...
  STORAGE_BACKEND=firebase → gs://<bucket>/document_uploads/{conversation_id}/...

Key layout (identical across backends — stored in MessageDocument rows):
  {conversation_id}/{document_id}{ext}            original file
  {conversation_id}/{document_id}.extracted.txt   extracted plain text
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Optional

from app.config import get_settings
from app.storage import BlobNotFoundError, BlobStorage, get_blob_storage
from app.documents.schemas import DocumentAttachment

_cfg = get_settings()


class DocumentStorageError(Exception):
    pass


class DocumentStorage:
    """Manages document persistence and extracted-text sidecars via blob storage."""

    def __init__(self, blobs: Optional[BlobStorage] = None) -> None:
        self._blobs = blobs or get_blob_storage(
            "document_uploads", local_root=Path(_cfg.document_storage_dir)
        )

    async def store(
        self,
        file_bytes: bytes,
        extracted_text: str,
        filename: str,
        mime_type: str,
        conversation_id: str,
        page_count: int | None = None,
    ) -> DocumentAttachment:
        """Store the original document + extracted text, return metadata."""
        max_bytes = _cfg.document_max_file_size_mb * 1024 * 1024
        if len(file_bytes) > max_bytes:
            raise DocumentStorageError(
                f"Document too large: {len(file_bytes)} bytes (max {max_bytes})"
            )

        doc_hash = hashlib.sha256(file_bytes).hexdigest()
        doc_id = str(uuid.uuid4())

        ext = Path(filename).suffix or ".txt"
        storage_key = f"{conversation_id}/{doc_id}{ext}"
        text_key = f"{conversation_id}/{doc_id}.extracted.txt"

        await self._blobs.put(storage_key, file_bytes, content_type=mime_type)
        await self._blobs.put(
            text_key, extracted_text.encode("utf-8"), content_type="text/plain; charset=utf-8"
        )

        return DocumentAttachment(
            id=doc_id,
            conversation_id=conversation_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(file_bytes),
            storage_path=storage_key,
            text_path=text_key,
            doc_hash=doc_hash,
            page_count=page_count,
            char_count=len(extracted_text),
        )

    async def get_text(self, attachment: DocumentAttachment) -> str:
        """Read the extracted text for a document."""
        try:
            data = await self._blobs.get(attachment.text_path)
        except BlobNotFoundError as e:
            raise DocumentStorageError(f"Extracted text not found: {attachment.id}") from e
        return data.decode("utf-8", errors="replace")

    async def get_bytes(self, storage_key: str) -> bytes:
        """Read original document bytes by raw storage key (for serving/download)."""
        try:
            return await self._blobs.get(storage_key)
        except BlobNotFoundError as e:
            raise DocumentStorageError(f"Document file not found: {storage_key}") from e

    async def delete(self, attachment: DocumentAttachment) -> None:
        for key in (attachment.storage_path, attachment.text_path):
            await self._blobs.delete(key)


# Singleton
_storage: DocumentStorage | None = None


def get_document_storage() -> DocumentStorage:
    global _storage
    if _storage is None:
        _storage = DocumentStorage()
    return _storage
