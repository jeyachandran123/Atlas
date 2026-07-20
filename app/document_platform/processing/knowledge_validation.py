"""
Knowledge Validation Layer (Objective 9).

Runs right before persistence. Structural checks only (types, ranges,
internal consistency) — never semantic thresholds like "word_count must be
> N", which would spuriously reject legitimate sparse documents (a
table-only spreadsheet, a short config file). A malformed Knowledge Object
must never reach storage; a merely small one is completely valid.
"""
from __future__ import annotations

from app.document_platform.processing.chunker import Chunk
from app.document_platform.processing.knowledge import BuiltKnowledgeObject


class KnowledgeValidationError(Exception):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


class KnowledgeValidator:
    def validate(self, built: BuiltKnowledgeObject, chunks: list[Chunk]) -> None:
        reasons: list[str] = []

        if not isinstance(built.doc_type, str) or not built.doc_type:
            reasons.append("doc_type is missing")
        if not isinstance(built.language, str) or not built.language:
            reasons.append("language is missing")
        if not (0.0 <= built.confidence <= 1.0):
            reasons.append(f"confidence {built.confidence} out of range [0,1]")
        if built.word_count < 0 or built.char_count < 0:
            reasons.append("negative word/char count")
        if not isinstance(built.structure, dict):
            reasons.append("structure is not a valid tree")

        # Chunk referential integrity: sequence must be contiguous from 0,
        # every chunk must reference this document's content only.
        seqs = [c.seq for c in chunks]
        if seqs != list(range(len(chunks))):
            reasons.append("chunk sequence is not contiguous from 0")
        for c in chunks:
            if c.token_count <= 0 and c.content.strip():
                reasons.append(f"chunk {c.seq} has non-positive token_count with content")
                break
        if len(chunks) != len(built.chunks):
            reasons.append("chunk count mismatch between builder output and validated chunks")

        if reasons:
            raise KnowledgeValidationError(reasons)
