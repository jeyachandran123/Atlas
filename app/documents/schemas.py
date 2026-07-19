"""
Document schemas — data structures for document-augmented conversations.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DocumentAttachment(BaseModel):
    """Metadata for an uploaded document, stored alongside a message."""
    id: str
    conversation_id: str
    message_id: Optional[str] = None
    filename: str
    mime_type: str
    size_bytes: int
    storage_path: str       # original file, relative to storage root
    text_path: str          # extracted-text sidecar, relative to storage root
    doc_hash: str           # SHA256 of original bytes
    page_count: Optional[int] = None
    char_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DocumentAttachmentOut(BaseModel):
    """Public-facing document metadata returned to the frontend."""
    id: str
    filename: str
    mime_type: str
    size_bytes: int
    page_count: Optional[int] = None
    char_count: int = 0
    url: str = ""  # served path
    created_at: datetime
