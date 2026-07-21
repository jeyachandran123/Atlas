"""Semantic layer API schemas — kept separate from document_platform/schemas.py
so Phase 3's contracts don't bloat the Phase 1/2 surface."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SemanticManifestOut(BaseModel):
    knowledge_id: str
    document_id: str
    vector_store_provider: str
    collection_name: str
    index_name: str
    embedding_version: str
    provider_name: str
    model_name: str
    dimension: int
    embedding_count: int
    status: str
    similarity_strategy: str
    ranking_strategy: Optional[str] = None
    retrieval_strategy: Optional[str] = None
    correlation_id: str
    created_at: datetime
    updated_at: datetime


class EmbeddingRecordOut(BaseModel):
    id: str
    chunk_id: str
    embedding_version: str
    provider_name: str
    model_name: str
    dimension: int
    status: str
    quality_score: Optional[float] = None
    latency_ms: Optional[int] = None
    vector_checksum: str
    created_at: datetime


class EmbeddingListOut(BaseModel):
    knowledge_id: str
    items: list[EmbeddingRecordOut]
    total: int
    limit: int
    offset: int


class SemanticHealthOut(BaseModel):
    knowledge_id: str
    status: str
    reasons: list[str] = Field(default_factory=list)


class EmbedTriggerResponse(BaseModel):
    knowledge_id: str
    job_id: str
    queued: bool = True
