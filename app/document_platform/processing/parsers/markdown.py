"""Markdown parser — headers, lists, code blocks, tables, images."""
from __future__ import annotations

import re

from app.document_platform.processing.capabilities import ParserCapabilities
from app.document_platform.processing.models import (
    DocumentNode, ImageRef, NodeType, ParsedDocument, RawMetadata,
)
from app.document_platform.processing.parsers.base import AbstractDocumentParser
from app.document_platform.processing.parsers.text import decode_text

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+(.*)$")
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


class MarkdownParser(AbstractDocumentParser):
    name = "markdown"
    extensions = (".md",)
    version = "1.0.0"
    capabilities = ParserCapabilities(
        supports_tables=True,
        supports_images=False,        # images are referenced (![]()), not extracted
        supports_structure=True,
        supports_embedded_images=True,
    )

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        text, encoding = decode_text(content)
        root = DocumentNode(type=NodeType.DOCUMENT)
        images: list[ImageRef] = []

        lines = text.split("\n")
        i = 0
        para: list[str] = []
        current_list: DocumentNode | None = None

        def flush_para() -> None:
            nonlocal para
            if para:
                root.add(DocumentNode(type=NodeType.PARAGRAPH, text="\n".join(para).strip()))
                para = []

        while i < len(lines):
            line = lines[i]

            # fenced code block
            if line.strip().startswith("```"):
                flush_para(); current_list = None
                lang = line.strip()[3:].strip()
                code: list[str] = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    code.append(lines[i]); i += 1
                root.add(DocumentNode(
                    type=NodeType.CODE_BLOCK, text="\n".join(code),
                    meta={"language": lang},
                ))
                i += 1
                continue

            # heading
            m = _HEADING.match(line)
            if m:
                flush_para(); current_list = None
                root.add(DocumentNode(
                    type=NodeType.HEADING, text=m.group(2).strip(), level=len(m.group(1)),
                ))
                i += 1
                continue

            # table
            if _TABLE_ROW.match(line) and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
                flush_para(); current_list = None
                headers = [c.strip() for c in line.strip().strip("|").split("|")]
                table = DocumentNode(type=NodeType.TABLE, meta={"headers": headers})
                i += 2
                while i < len(lines) and _TABLE_ROW.match(lines[i]):
                    cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                    row = DocumentNode(type=NodeType.ROW)
                    for c in cells:
                        row.add(DocumentNode(type=NodeType.CELL, text=c))
                    table.add(row)
                    i += 1
                root.add(table)
                continue

            # list item
            m = _LIST_ITEM.match(line)
            if m:
                flush_para()
                if current_list is None:
                    current_list = root.add(DocumentNode(type=NodeType.LIST))
                current_list.add(DocumentNode(type=NodeType.LIST_ITEM, text=m.group(1).strip()))
                i += 1
                continue

            # images (referenced — no binary in markdown)
            for alt, src in _IMAGE.findall(line):
                images.append(ImageRef(name=alt or src.rsplit("/", 1)[-1], meta={"src": src}))

            if line.strip():
                current_list = None
                para.append(line)
            else:
                flush_para(); current_list = None
            i += 1

        flush_para()
        return ParsedDocument(
            root=root, images=images,
            raw_metadata=RawMetadata(encoding=encoding),
            parser_name=self.name,
        )
