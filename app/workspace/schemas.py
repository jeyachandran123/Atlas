"""API schemas for the Workspace endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class WorkspaceCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    icon: str = Field(default="folder", max_length=30)


class WorkspaceUpdateIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)
    icon: Optional[str] = Field(default=None, max_length=30)


class WorkspaceOut(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    is_default: bool
    status: str
    created_at: datetime


class WorkspaceDocumentOut(BaseModel):
    id: str
    filename: str
    extension: str
    size_bytes: int
    processing_status: str
    created_at: datetime


class AddDocumentIn(BaseModel):
    document_id: str
    conversation_id: Optional[str] = None  # also attach to this conversation


class WorkspaceConversationOut(BaseModel):
    conversation_id: str
    title: str
    title_generated: bool
    created_at: datetime
    updated_at: datetime


class ConversationCreateIn(BaseModel):
    title: str = Field(default="", max_length=300)


class ConversationRenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class WorkspaceAskIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    document_ids: Optional[list[str]] = None  # attach + scope these documents


class AttachDocumentIn(BaseModel):
    document_id: str


class WorkspaceGenerateIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    format: str = Field(min_length=1, max_length=20)
    conversation_id: Optional[str] = None


class WorkspaceArtifactOut(BaseModel):
    id: str
    title: str
    filename: str
    format: str
    status: str
    size_bytes: int
    grounded: bool
    conversation_id: Optional[str]
    created_at: datetime


class TimelineEventOut(BaseModel):
    id: str
    event_type: str
    title: str
    ref_type: Optional[str]
    ref_id: Optional[str]
    detail_json: Optional[str]
    created_at: datetime


class BookmarkIn(BaseModel):
    target_type: str = Field(pattern="^(answer|document|conversation|artifact)$")
    target_id: str
    note: Optional[str] = Field(default=None, max_length=500)


class BookmarkOut(BaseModel):
    id: str
    target_type: str
    target_id: str
    note: Optional[str]
    created_at: datetime


class DashboardOut(BaseModel):
    workspace: WorkspaceOut
    stats: dict[str, int]
    summary: str
    suggestions: list[str]
    summary_generated_at: Optional[datetime]
    recent_conversations: list[WorkspaceConversationOut]
    recent_documents: list[WorkspaceDocumentOut]
    recent_artifacts: list[WorkspaceArtifactOut]
    recent_activity: list[TimelineEventOut]


class SearchOut(BaseModel):
    query: str
    results: dict[str, Any]


class RelatedOut(BaseModel):
    documents: list[dict[str, Any]]
    conversations: list[dict[str, Any]]


class SaveKnowledgeOut(BaseModel):
    document_id: str
    duplicate_of: Optional[str]
