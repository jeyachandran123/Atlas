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

            # `max_col` is a **ceiling**, not a width. Asking openpyxl for 200
            # columns returns 200 cells per row whether or not the sheet is
            # that wide, and every one of the empties used to be kept — so a
            # four-column grocery list rendered as
            # `Milk | 2 | Dairy | 3.5 |  |  |  | ...` out to column 200.
            #
            # That padding was not cosmetic. It inflated one six-row sheet into
            # a 62,000-character chunk, which the embedding model refused
            # outright ("the input length exceeds the context length"), so the
            # document was never indexed and every question about it was
            # answered "I don't have enough information in the knowledge base"
            # — with nothing anywhere reporting a fault.
            width = min(ws.max_column or 1, _MAX_COLS)
            rows_iter = ws.iter_rows(max_row=_MAX_ROWS_PER_SHEET, max_col=width)
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
                # Trailing empties carry no information and cost separator noise
                # in the embedded text. `ws.max_column` is itself often inflated
                # by stray formatting on an otherwise empty column, so trimming
                # per row is what actually keeps a narrow sheet narrow.
                while cells and not cells[-1]:
                    cells.pop()
                if any(c for c in cells):
                    all_rows.append(cells)

            if not all_rows:
                continue

            # Rectangular again, at the width the data actually occupies, so
            # `headers` and every row still line up column for column.
            true_width = max(len(r) for r in all_rows)
            for r in all_rows:
                r.extend([""] * (true_width - len(r)))

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
