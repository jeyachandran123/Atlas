"""API schemas for the Conversational Knowledge Intelligence endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ConversationCreateIn(BaseModel):
    title: str = Field(default="", max_length=300)


class ConversationOut(BaseModel):
    id: str
    title: str
    status: str
    correlation_id: str
    created_at: datetime


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    document_id: Optional[str] = None            # optional single-document scope
    document_ids: Optional[list[str]] = None     # multi-document scope (Phase 5.5)


class CitationOut(BaseModel):
    source_id: str
    knowledge_id: str
    document_id: str
    section: str
    page: Optional[int]
    chunk_ids: list[str]
    seqs: list[int]
    confidence: float


class TurnOut(BaseModel):
    turn_id: str
    conversation_id: str
    correlation_id: str
    status: str
    intent: str
    answer: Optional[str]
    grounded: bool
    grounding_score: Optional[float]
    refusal_reason: Optional[str]
    citations: list[CitationOut] = []
    metrics: dict[str, Any] = {}
    error: Optional[str] = None


class TurnHistoryOut(BaseModel):
    id: str
    seq: int
    question: str
    answer: Optional[str]
    intent: str
    status: str
    grounded: bool
    grounding_score: Optional[float]
    citation_count: int
    citations_json: Optional[str] = None  # full citations — used for history restore
    total_ms: Optional[int]
    total_tokens: Optional[int]
    created_at: datetime


class ConversationEventOut(BaseModel):
    id: str
    event_type: str
    status: str
    duration_ms: Optional[int]
    detail_json: Optional[str]
    created_at: datetime
