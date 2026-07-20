"""
ProcessingContext (Objective 2).

One object flows through every stage instead of a dozen loose parameters.

Immutability note: a true copy-on-write context (dataclasses.replace() per
stage) would deep-copy the full document tree on every one of ~14 stages —
wasteful for no real safety gain on a single-threaded, single-document run.
Instead this uses SINGLE-WRITER DISCIPLINE: each field below is written by
exactly one stage (noted in the comment), and every other stage treats it as
read-only. The orchestrator is the only code that constructs and mutates a
ProcessingContext; stages themselves never see or touch each other.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from app.document_platform.processing.chunker import Chunk
from app.document_platform.processing.knowledge import BuiltKnowledgeObject
from app.document_platform.processing.metadata import ExtractedMetadata
from app.document_platform.processing.models import DocumentNode, ParsedDocument, TableData


@dataclass
class ProcessingContext:
    # Identity — set at construction, never reassigned
    document_id: str
    job_id: str
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    profile_name: str = "standard"
    attempt: int = 1

    # Enriched by stages, one writer each
    content: Optional[bytes] = None                    # loader
    detected_extension: str = ""                        # detector
    detected_family: str = ""                           # detector
    parsed: Optional[ParsedDocument] = None              # parser
    ocr_pending: bool = False                            # ocr
    tree: Optional[DocumentNode] = None                  # normalizer / structure / clean (sequential owners)
    metadata: Optional[ExtractedMetadata] = None         # metadata extractor
    tables: list[TableData] = field(default_factory=list)      # table extractor
    image_count: int = 0                                 # image extractor
    language: str = "unknown"                            # language detector
    chunks: list[Chunk] = field(default_factory=list)     # chunker
    knowledge: Optional[BuiltKnowledgeObject] = None      # knowledge builder

    # Cross-cutting — any stage may append (never overwrite the list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    timings_ms: dict[str, int] = field(default_factory=dict)

    # Owned by the orchestrator only
    processing_status: str = "queued"

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def record_timing(self, stage: str, ms: int) -> None:
        self.timings_ms[stage] = ms

    @property
    def total_duration_ms(self) -> int:
        return sum(self.timings_ms.values())

    def to_summary(self) -> dict[str, Any]:
        """Compact dict for logging/events — never the full tree."""
        return {
            "document_id": self.document_id,
            "correlation_id": self.correlation_id,
            "profile": self.profile_name,
            "attempt": self.attempt,
            "language": self.language,
            "chunk_count": len(self.chunks),
            "table_count": len(self.tables),
            "image_count": self.image_count,
            "warnings": len(self.warnings),
            "total_duration_ms": self.total_duration_ms,
        }
