"""
Citation Builder (Objective 10) — parses [S#] markers out of the generated
answer and resolves each to full provenance: knowledge ID, document ID,
section, page, chunk IDs, sequence numbers, confidence. Pages come from a
read-only lookup supplied by the caller (vector metadata doesn't carry
them); everything else rides on the ContextBundle.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.document_platform.conversation.context_builder import ContextBundle

_MARKER_RE = re.compile(r"\[S(\d+)\]")


@dataclass(frozen=True)
class Citation:
    source_id: str
    knowledge_id: str
    document_id: str
    section: str
    page: Optional[int]
    chunk_ids: list[str] = field(default_factory=list)
    seqs: list[int] = field(default_factory=list)
    confidence: float = 0.0


@dataclass(frozen=True)
class CitationOutcome:
    citations: list[Citation]
    cited_source_ids: list[str]      # in first-mention order
    unresolved_markers: list[str]    # markers citing sources that don't exist


class CitationBuilder:
    def build(
        self, answer: str, bundle: ContextBundle,
        pages_by_chunk: dict[str, Optional[int]] | None = None,
    ) -> CitationOutcome:
        pages = pages_by_chunk or {}
        seen: list[str] = []
        unresolved: list[str] = []
        for match in _MARKER_RE.finditer(answer):
            sid = f"S{match.group(1)}"
            if sid in seen or sid in unresolved:
                continue
            (seen if bundle.get(sid) else unresolved).append(sid)

        citations = []
        for sid in seen:
            src = bundle.get(sid)
            assert src is not None
            page = next(
                (pages[cid] for cid in src.chunk_ids if pages.get(cid) is not None), None,
            )
            citations.append(Citation(
                source_id=sid,
                knowledge_id=src.knowledge_id,
                document_id=src.document_id,
                section=src.section_path,
                page=page,
                chunk_ids=list(src.chunk_ids),
                seqs=list(src.seqs),
                confidence=round(src.confidence, 4),
            ))
        return CitationOutcome(
            citations=citations, cited_source_ids=seen, unresolved_markers=unresolved,
        )
