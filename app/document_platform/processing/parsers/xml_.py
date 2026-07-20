"""XML parser — hierarchy, attributes, nodes (defusedxml-style safe parse)."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from app.document_platform.processing.models import (
    DocumentNode, NodeType, ParsedDocument, RawMetadata,
)
from app.document_platform.processing.parsers.base import AbstractDocumentParser, ParserError
from app.document_platform.processing.parsers.text import decode_text

_MAX_DEPTH = 15
_MAX_NODES = 20_000


class XmlParser(AbstractDocumentParser):
    name = "xml"
    extensions = (".xml",)

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        text, encoding = decode_text(content)
        # Reject DTD/entity declarations outright — XXE hardening
        head = text[:2000].lower()
        if "<!doctype" in head or "<!entity" in head:
            raise ParserError("XML documents with DTD/entity declarations are not accepted")
        try:
            xml_root = ET.fromstring(text)
        except ET.ParseError as e:
            raise ParserError(f"Invalid XML: {e}") from e

        root = DocumentNode(type=NodeType.DOCUMENT)
        self._count = 0
        self._build(xml_root, root, depth=0)

        return ParsedDocument(
            root=root,
            raw_metadata=RawMetadata(encoding=encoding),
            parser_name=self.name,
        )

    def _build(self, el: ET.Element, parent: DocumentNode, depth: int) -> None:
        if self._count >= _MAX_NODES or depth > _MAX_DEPTH:
            return
        self._count += 1

        tag = el.tag.split("}")[-1]  # strip namespace
        text = (el.text or "").strip()
        node = parent.add(DocumentNode(
            type=NodeType.OBJECT if len(el) else NodeType.VALUE,
            text=f"{tag}: {text}" if text else tag,
            meta={"attributes": dict(el.attrib)} if el.attrib else {},
        ))
        for child in el:
            self._build(child, node, depth + 1)
