"""
PDF parser (pypdf) — pages, paragraphs, heading heuristics, images, metadata.
Flags needs_ocr when the text layer is empty/near-empty (scanned document).
"""
from __future__ import annotations

import io
import re

from loguru import logger

from app.document_platform.processing.capabilities import ParserCapabilities
from app.document_platform.processing.models import (
    DocumentNode, ImageRef, NodeType, ParsedDocument, RawMetadata,
)
from app.document_platform.processing.parsers.base import AbstractDocumentParser, ParserError

_SCANNED_CHARS_PER_PAGE = 50
# Short line, no terminal punctuation, mostly title-cased → heading heuristic
_HEADING_LIKE = re.compile(r"^[A-Z0-9][^.!?]{0,79}$")


class PdfParser(AbstractDocumentParser):
    name = "pdf"
    extensions = (".pdf",)
    version = "1.0.0"
    capabilities = ParserCapabilities(
        supports_tables=False,   # pypdf does not expose table structure
        supports_images=True,
        supports_ocr_trigger=True,
        supports_structure=True,  # heading heuristic
    )

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(content))
        except Exception as e:
            raise ParserError(f"Cannot open PDF: {e}") from e

        root = DocumentNode(type=NodeType.DOCUMENT)
        images: list[ImageRef] = []
        total_chars = 0

        for page_no, page in enumerate(reader.pages, start=1):
            page_node = root.add(DocumentNode(type=NodeType.PAGE, page=page_no))
            try:
                text = page.extract_text() or ""
            except Exception as e:
                logger.debug(f"PDF page {page_no} text extraction failed: {e}")
                text = ""
            total_chars += len(text.strip())

            for block in re.split(r"\n\s*\n", text):
                block = block.strip()
                if not block:
                    continue
                first_line = block.splitlines()[0].strip()
                if (
                    len(block.splitlines()) == 1
                    and len(first_line) <= 80
                    and _HEADING_LIKE.match(first_line)
                    and first_line == first_line.rstrip(".")
                    and sum(w[:1].isupper() for w in first_line.split()) >= max(1, len(first_line.split()) // 2)
                ):
                    page_node.add(DocumentNode(
                        type=NodeType.HEADING, text=first_line, level=2, page=page_no,
                    ))
                else:
                    page_node.add(DocumentNode(
                        type=NodeType.PARAGRAPH, text=block, page=page_no,
                    ))

            # Embedded images (best-effort — some encodings aren't extractable)
            try:
                for img in page.images:
                    images.append(ImageRef(
                        name=img.name or f"page{page_no}-img",
                        content=img.data,
                        page=page_no,
                        format=(img.name or "").rsplit(".", 1)[-1].lower() if "." in (img.name or "") else "png",
                    ))
            except Exception as e:
                logger.debug(f"PDF page {page_no} image extraction failed: {e}")

        meta = reader.metadata or {}
        page_count = len(reader.pages)
        needs_ocr = page_count > 0 and (total_chars / page_count) < _SCANNED_CHARS_PER_PAGE

        return ParsedDocument(
            root=root,
            images=images,
            raw_metadata=RawMetadata(
                title=str(meta.get("/Title", "") or ""),
                author=str(meta.get("/Author", "") or ""),
                created=str(meta.get("/CreationDate", "") or ""),
                modified=str(meta.get("/ModDate", "") or ""),
                page_count=page_count,
            ),
            needs_ocr=needs_ocr,
            parser_name=self.name,
        )
