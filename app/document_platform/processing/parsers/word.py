"""Word (.docx) parser — paragraphs, headings, lists, tables, images, metadata."""
from __future__ import annotations

import io
import re

from loguru import logger

from app.document_platform.processing.models import (
    DocumentNode, ImageRef, NodeType, ParsedDocument, RawMetadata,
)
from app.document_platform.processing.parsers.base import AbstractDocumentParser, ParserError

_HEADING_STYLE = re.compile(r"heading\s*(\d)", re.IGNORECASE)


class WordParser(AbstractDocumentParser):
    name = "word"
    extensions = (".docx",)

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        import docx

        try:
            document = docx.Document(io.BytesIO(content))
        except Exception as e:
            raise ParserError(f"Cannot open .docx: {e}") from e

        root = DocumentNode(type=NodeType.DOCUMENT)
        current_list: DocumentNode | None = None

        # Interleave paragraphs and tables in document order via the body XML
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        for block in self._iter_blocks(document):
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if not text:
                    current_list = None
                    continue
                style = (block.style.name or "") if block.style else ""
                m = _HEADING_STYLE.search(style)
                if m or style.lower() == "title":
                    current_list = None
                    root.add(DocumentNode(
                        type=NodeType.HEADING, text=text,
                        level=int(m.group(1)) if m else 1,
                    ))
                elif "list" in style.lower():
                    if current_list is None:
                        current_list = root.add(DocumentNode(type=NodeType.LIST))
                    current_list.add(DocumentNode(type=NodeType.LIST_ITEM, text=text))
                else:
                    current_list = None
                    root.add(DocumentNode(type=NodeType.PARAGRAPH, text=text))
            elif isinstance(block, Table):
                current_list = None
                table_node = root.add(DocumentNode(type=NodeType.TABLE))
                for r_i, row in enumerate(block.rows):
                    row_node = table_node.add(DocumentNode(
                        type=NodeType.ROW, meta={"is_header": r_i == 0},
                    ))
                    for cell in row.cells:
                        row_node.add(DocumentNode(type=NodeType.CELL, text=cell.text.strip()))

        images = self._extract_images(document)

        props = document.core_properties
        return ParsedDocument(
            root=root,
            images=images,
            raw_metadata=RawMetadata(
                title=props.title or "",
                author=props.author or "",
                created=str(props.created or ""),
                modified=str(props.modified or ""),
            ),
            parser_name=self.name,
        )

    @staticmethod
    def _iter_blocks(document):
        """Yield Paragraph and Table objects in true document order."""
        from docx.document import Document as DocxDocument
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        body = document.element.body
        for child in body.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, document)
            elif child.tag == qn("w:tbl"):
                yield Table(child, document)

    @staticmethod
    def _extract_images(document) -> list[ImageRef]:
        images: list[ImageRef] = []
        try:
            for rel in document.part.rels.values():
                if "image" in rel.reltype and not rel.is_external:
                    part = rel.target_part
                    name = part.partname.rsplit("/", 1)[-1]
                    images.append(ImageRef(
                        name=name,
                        content=part.blob,
                        format=name.rsplit(".", 1)[-1].lower() if "." in name else "png",
                    ))
        except Exception as e:
            logger.debug(f"docx image extraction failed: {e}")
        return images
