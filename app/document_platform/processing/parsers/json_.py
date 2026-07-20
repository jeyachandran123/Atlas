"""JSON parser — the tree structure becomes OBJECT/ARRAY/VALUE nodes."""
from __future__ import annotations

import json

from app.document_platform.processing.models import (
    DocumentNode, NodeType, ParsedDocument, RawMetadata,
)
from app.document_platform.processing.parsers.base import AbstractDocumentParser, ParserError
from app.document_platform.processing.parsers.text import decode_text

_MAX_DEPTH = 12
_MAX_NODES = 20_000


class JsonParser(AbstractDocumentParser):
    name = "json"
    extensions = (".json",)

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        text, encoding = decode_text(content)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ParserError(f"Invalid JSON: {e}") from e

        root = DocumentNode(type=NodeType.DOCUMENT)
        self._count = 0
        self._build(data, root, key="", depth=0)

        return ParsedDocument(
            root=root,
            raw_metadata=RawMetadata(encoding=encoding),
            parser_name=self.name,
        )

    def _build(self, value, parent: DocumentNode, key: str, depth: int) -> None:
        if self._count >= _MAX_NODES or depth > _MAX_DEPTH:
            return
        self._count += 1

        if isinstance(value, dict):
            node = parent.add(DocumentNode(
                type=NodeType.OBJECT, text=key, meta={"keys": list(value.keys())[:100]},
            ))
            for k, v in value.items():
                self._build(v, node, k, depth + 1)
        elif isinstance(value, list):
            node = parent.add(DocumentNode(
                type=NodeType.ARRAY, text=key, meta={"length": len(value)},
            ))
            for i, v in enumerate(value[:500]):
                self._build(v, node, f"[{i}]", depth + 1)
        else:
            rendered = "null" if value is None else str(value)
            parent.add(DocumentNode(
                type=NodeType.VALUE,
                text=f"{key}: {rendered}" if key else rendered,
            ))
