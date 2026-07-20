"""
Processing Metrics (Objective 4).

Assembled from the ProcessingContext once processing completes — no new
table: the assembled dict rides as the `detail` payload of the final
ProcessingCompleted event (queryable today via GET /{id}/processing,
promotable to a dedicated metrics table later without touching callers).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from app.document_platform.processing.context import ProcessingContext


@dataclass
class ProcessingMetrics:
    document_size_bytes: int
    total_duration_ms: int
    stage_durations_ms: dict[str, int]
    word_count: int
    char_count: int
    page_count: Optional[int]
    table_count: int
    image_count: int
    chunk_count: int
    avg_chunk_tokens: float
    language: str
    parser_name: str
    parser_version: str
    warning_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MetricsCollector:
    def collect(self, ctx: ProcessingContext, parser_name: str, parser_version: str) -> ProcessingMetrics:
        chunks = ctx.chunks
        avg_tokens = (sum(c.token_count for c in chunks) / len(chunks)) if chunks else 0.0
        return ProcessingMetrics(
            document_size_bytes=len(ctx.content) if ctx.content else 0,
            total_duration_ms=ctx.total_duration_ms,
            stage_durations_ms=dict(ctx.timings_ms),
            word_count=ctx.metadata.word_count if ctx.metadata else 0,
            char_count=ctx.metadata.char_count if ctx.metadata else 0,
            page_count=ctx.metadata.page_count if ctx.metadata else None,
            table_count=len(ctx.tables),
            image_count=ctx.image_count,
            chunk_count=len(chunks),
            avg_chunk_tokens=round(avg_tokens, 1),
            language=ctx.language,
            parser_name=parser_name,
            parser_version=parser_version,
            warning_count=len(ctx.warnings),
        )
