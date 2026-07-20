"""
Excel (.xlsx) parser (openpyxl) — workbook → sheets → rows/cells, formulas,
header inference, merged cells. Each sheet becomes a SHEET node with a TABLE.
"""
from __future__ import annotations

import io

from app.document_platform.processing.capabilities import ParserCapabilities
from app.document_platform.processing.models import (
    DocumentNode, NodeType, ParsedDocument, RawMetadata,
)
from app.document_platform.processing.parsers.base import AbstractDocumentParser, ParserError

_MAX_ROWS_PER_SHEET = 20_000
_MAX_COLS = 200


class ExcelParser(AbstractDocumentParser):
    name = "excel"
    extensions = (".xlsx",)
    version = "1.0.0"
    capabilities = ParserCapabilities(
        supports_tables=True,
        supports_structure=False,  # sheets are flat tables, not heading hierarchies
    )

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        import openpyxl

        try:
            # data_only=False keeps formula strings — a required extraction
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=False, read_only=False)
        except Exception as e:
            raise ParserError(f"Cannot open .xlsx: {e}") from e

        root = DocumentNode(type=NodeType.DOCUMENT)
        formula_count = 0

        for sheet_no, ws in enumerate(wb.worksheets, start=1):
            sheet_node = root.add(DocumentNode(
                type=NodeType.SHEET, text=ws.title, page=sheet_no,
                meta={"dimensions": ws.dimensions or ""},
            ))
            merged = [str(r) for r in getattr(ws, "merged_cells", []).ranges] if getattr(ws, "merged_cells", None) else []

            rows_iter = ws.iter_rows(max_row=_MAX_ROWS_PER_SHEET, max_col=_MAX_COLS)
            all_rows: list[list[str]] = []
            for row in rows_iter:
                cells: list[str] = []
                for cell in row:
                    v = cell.value
                    if v is None:
                        cells.append("")
                    else:
                        s = str(v)
                        if s.startswith("="):
                            formula_count += 1
                        cells.append(s)
                if any(c for c in cells):
                    all_rows.append(cells)

            if not all_rows:
                continue

            table = sheet_node.add(DocumentNode(
                type=NodeType.TABLE, page=sheet_no,
                meta={
                    "headers": all_rows[0],
                    "merged_cells": merged,
                    "caption": ws.title,
                },
            ))
            for r_i, cells in enumerate(all_rows):
                row_node = table.add(DocumentNode(
                    type=NodeType.ROW, page=sheet_no, meta={"is_header": r_i == 0},
                ))
                for c in cells:
                    row_node.add(DocumentNode(type=NodeType.CELL, text=c, page=sheet_no))

        props = wb.properties
        return ParsedDocument(
            root=root,
            raw_metadata=RawMetadata(
                title=props.title or "",
                author=props.creator or "",
                created=str(props.created or ""),
                modified=str(props.modified or ""),
                sheet_count=len(wb.worksheets),
                custom={"formula_count": formula_count},
            ),
            parser_name=self.name,
        )
