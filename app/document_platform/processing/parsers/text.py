"""Plain-text parser — paragraphs split on blank lines."""
from __future__ import annotations

from app.document_platform.processing.capabilities import ParserCapabilities
from app.document_platform.processing.models import (
    DocumentNode, NodeType, ParsedDocument, RawMetadata,
)
from app.document_platform.processing.parsers.base import AbstractDocumentParser


def decode_text(content: bytes) -> tuple[str, str]:
    """Best-effort decode → (text, encoding-used)."""
    for enc in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return content.decode(enc), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return content.decode("utf-8", errors="replace"), "utf-8/replace"


class TextParser(AbstractDocumentParser):
    name = "text"
    extensions = (".txt",)
    version = "1.0.0"
    capabilities = ParserCapabilities(supports_tables=False, supports_structure=False)

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        text, encoding = decode_text(content)
        root = DocumentNode(type=NodeType.DOCUMENT)
        for block in text.split("\n\n"):
            if block.strip():
                root.add(DocumentNode(type=NodeType.PARAGRAPH, text=block.strip()))
        return ParsedDocument(
            root=root,
            raw_metadata=RawMetadata(encoding=encoding),
            parser_name=self.name,
        )
