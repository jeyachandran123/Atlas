"""CSV parser — rows, columns, header inference; the sheet becomes one table."""
from __future__ import annotations

import csv
import io

from app.document_platform.processing.capabilities import ParserCapabilities
from app.document_platform.processing.models import (
    DocumentNode, NodeType, ParsedDocument, RawMetadata,
)
from app.document_platform.processing.parsers.base import AbstractDocumentParser, ParserError
from app.document_platform.processing.parsers.text import decode_text

_MAX_ROWS = 50_000


class CsvParser(AbstractDocumentParser):
    name = "csv"
    extensions = (".csv",)
    version = "1.0.0"
    capabilities = ParserCapabilities(supports_tables=True, supports_structure=False)

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        text, encoding = decode_text(content)
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel

        reader = csv.reader(io.StringIO(text), dialect)
        rows = []
        for i, row in enumerate(reader):
            if i >= _MAX_ROWS:
                break
            rows.append([c.strip() for c in row])
        if not rows:
            raise ParserError("CSV contains no rows")

        # Header inference: first row is a header when no cell parses as a number
        def _numeric(v: str) -> bool:
            try:
                float(v.replace(",", ""))
                return True
            except ValueError:
                return False

        has_header = rows[0] and not any(_numeric(c) for c in rows[0] if c)
        headers = rows[0] if has_header else []
        data_rows = rows[1:] if has_header else rows

        root = DocumentNode(type=NodeType.DOCUMENT)
        table = root.add(DocumentNode(type=NodeType.TABLE, meta={"headers": headers}))
        for r in data_rows:
            row_node = table.add(DocumentNode(type=NodeType.ROW))
            for c in r:
                row_node.add(DocumentNode(type=NodeType.CELL, text=c))

        return ParsedDocument(
            root=root,
            raw_metadata=RawMetadata(
                encoding=encoding,
                custom={"delimiter": dialect.delimiter, "row_count": len(data_rows)},
            ),
            parser_name=self.name,
        )
