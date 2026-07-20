"""
KnowledgeObjectBuilder — assembles the final Knowledge Object from the
outputs of every prior stage. Builds only; persistence is the pipeline's job.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.document_platform.processing.chunker import Chunk
from app.document_platform.processing.metadata import ExtractedMetadata
from app.document_platform.processing.models import DocumentNode, TableData
from app.document_platform.processing.structure import StructureStats


@dataclass
class BuiltKnowledgeObject:
    title: str
    doc_type: str
    language: str
    confidence: float
    word_count: int
    char_count: int
    section_count: int
    table_count: int
    image_count: int
    structure: dict = field(default_factory=dict)
    chunks: list[Chunk] = field(default_factory=list)
    tables: list[TableData] = field(default_factory=list)


class KnowledgeObjectBuilder:
    def build(
        self,
        *,
        doc_type: str,
        tree: DocumentNode,
        chunks: list[Chunk],
        tables: list[TableData],
        metadata: ExtractedMetadata,
        stats: StructureStats,
        language: str,
        image_count: int,
        ocr_pending: bool,
    ) -> BuiltKnowledgeObject:
        return BuiltKnowledgeObject(
            title=metadata.title,
            doc_type=doc_type,
            language=language,
            confidence=self._confidence(chunks, language, ocr_pending),
            word_count=metadata.word_count,
            char_count=metadata.char_count,
            section_count=stats.section_count,
            table_count=len(tables),
            image_count=image_count,
            structure=tree.to_dict(),
            chunks=chunks,
            tables=tables,
        )

    @staticmethod
    def _confidence(chunks: list[Chunk], language: str, ocr_pending: bool) -> float:
        """
        Honest quality signal for downstream consumers:
        full extraction → 1.0; degraded signals subtract.
        """
        score = 1.0
        if not chunks:
            score -= 0.5
        if language == "unknown":
            score -= 0.1
        if ocr_pending:
            score -= 0.4   # scanned/image content whose text is not yet extracted
        return max(0.0, round(score, 2))
