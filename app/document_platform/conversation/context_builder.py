"""
Context Builder (Objective 6) — ranked chunks in, AI-ready ContextBundle
out. Dedupes by chunk_id, merges adjacent chunks (same document, consecutive
seq — restoring the source's natural reading order inside one source block),
preserves section hierarchy and document references, and enforces the token
budget. Chunks are never passed raw to the LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.document_platform.conversation.ranking import RankedChunk


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)  # same ~4 chars/token heuristic used platform-wide


@dataclass(frozen=True)
class ContextSource:
    source_id: str                   # "S1", "S2", … — cited by the model
    document_id: str
    knowledge_id: str
    chunk_ids: list[str]
    seqs: list[int]
    section_path: str
    text: str
    confidence: float
    token_estimate: int


@dataclass(frozen=True)
class ContextBundle:
    sources: list[ContextSource]
    total_tokens: int
    truncated: bool = False          # budget forced dropping lower-ranked material
    best_confidence: float = 0.0

    @property
    def source_ids(self) -> set[str]:
        return {s.source_id for s in self.sources}

    def get(self, source_id: str) -> ContextSource | None:
        return next((s for s in self.sources if s.source_id == source_id), None)


class ContextBuilder:
    def __init__(self, token_budget: int) -> None:
        self._budget = token_budget

    def build(self, ranked: list[RankedChunk]) -> ContextBundle:
        # Dedupe by chunk_id, keeping the highest-confidence occurrence
        # (list arrives confidence-ordered from the Ranking Engine).
        seen: set[str] = set()
        unique = []
        for r in ranked:
            if r.chunk.chunk_id in seen:
                continue
            seen.add(r.chunk.chunk_id)
            unique.append(r)

        # Merge adjacent chunks: same document + consecutive seq become one
        # source, re-ordered by seq so the text reads as the author wrote it.
        merged: list[list[RankedChunk]] = []
        for r in unique:
            placed = False
            for group in merged:
                if group[0].chunk.document_id == r.chunk.document_id and any(
                    abs(g.chunk.seq - r.chunk.seq) == 1 for g in group
                ):
                    group.append(r)
                    placed = True
                    break
            if not placed:
                merged.append([r])

        sources: list[ContextSource] = []
        total = 0
        truncated = False
        for i, group in enumerate(merged):
            group.sort(key=lambda g: g.chunk.seq)
            text = "\n\n".join(g.chunk.text for g in group)
            tokens = _estimate_tokens(text)
            if total + tokens > self._budget and sources:
                truncated = True
                continue  # keep scanning — a smaller later group may still fit
            first = group[0].chunk
            sources.append(ContextSource(
                source_id=f"S{len(sources) + 1}",
                document_id=first.document_id,
                knowledge_id=first.knowledge_id,
                chunk_ids=[g.chunk.chunk_id for g in group],
                seqs=[g.chunk.seq for g in group],
                section_path=first.section_path,
                text=text,
                confidence=max(g.confidence for g in group),
                token_estimate=tokens,
            ))
            total += tokens

        best = max((r.confidence for r in unique), default=0.0)
        return ContextBundle(
            sources=sources, total_tokens=total, truncated=truncated, best_confidence=best,
        )
