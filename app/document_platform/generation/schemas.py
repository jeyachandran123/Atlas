"""API schemas for the Generation Platform endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class GenerateIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    format: str = Field(min_length=1, max_length=20)   # excel|pdf|word|csv|json|markdown|html
    document_id: Optional[str] = None                  # optional single-document grounding scope


class ArtifactOut(BaseModel):
    id: str
    status: str
    format: str
    title: str
    filename: str
    content_type: str
    checksum: str
    size_bytes: int
    grounded: bool
    builder_name: str
    builder_version: str
    spec_version: str
    schema_version: str
    source_document_id: Optional[str]
    source_knowledge_ids_json: Optional[str]
    llm_provider: str
    llm_model: str
    planning_ms: Optional[int]
    transform_ms: Optional[int]
    build_ms: Optional[int]
    store_ms: Optional[int]
    total_ms: Optional[int]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    error: Optional[str]
    correlation_id: str
    created_at: datetime
    finished_at: Optional[datetime]


class DownloadOut(BaseModel):
    mode: str                        # signed_url | proxy
    url: Optional[str]
    expires_in: Optional[int]
    filename: str
    content_type: str


class GenerationEventOut(BaseModel):
    id: str
    event_type: str
    status: str
    duration_ms: Optional[int]
    detail_json: Optional[str]
    created_at: datetime


class FormatsOut(BaseModel):
    formats: list[str]
