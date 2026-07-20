"""MetadataExtractor — merges source metadata with computed statistics."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.document_platform.processing.models import DocumentNode, ParsedDocument


@dataclass
class ExtractedMetadata:
    title: str = ""
    author: str = ""
    source_created: str = ""
    source_modified: str = ""
    page_count: Optional[int] = None
    sheet_count: Optional[int] = None
    slide_count: Optional[int] = None
    word_count: int = 0
    char_count: int = 0
    encoding: str = "utf-8"
    custom: dict[str, Any] = field(default_factory=dict)


class MetadataExtractor:
    def extract(self, parsed: ParsedDocument, tree: DocumentNode) -> ExtractedMetadata:
        raw = parsed.raw_metadata
        full_text = "\n".join(n.text for n in tree.walk() if n.text)
        return ExtractedMetadata(
            title=(raw.title or self._infer_title(tree))[:500],
            author=raw.author[:255],
            source_created=raw.created[:50],
            source_modified=raw.modified[:50],
            page_count=raw.page_count,
            sheet_count=raw.sheet_count,
            slide_count=raw.slide_count,
            word_count=len(full_text.split()),
            char_count=len(full_text),
            encoding=raw.encoding,
            custom=raw.custom,
        )

    @staticmethod
    def _infer_title(tree: DocumentNode) -> str:
        """First heading, else first non-trivial text line."""
        from app.document_platform.processing.models import NodeType
        for n in tree.walk():
            if n.type == NodeType.HEADING and n.text.strip():
                return n.text.strip()
        for n in tree.walk():
            t = n.text.strip()
            if len(t) >= 4:
                return t.splitlines()[0][:200]
        return ""
