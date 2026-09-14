"""A file as data a browser can draw — for the in-app viewer.

PDFs and images the browser shows by itself. Spreadsheets and Word files it
cannot, so they are read here, where the libraries already are (openpyxl,
python-docx), and sent as a grid of cells or as headings and paragraphs.

Every row is sent: the viewer draws only the rows on screen, so a sheet of a
few thousand rows scrolls as smoothly as a short one. Only a sheet past
MAX_CELLS is cut, and the preview then says how much there really is.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, time
from pathlib import PurePosixPath
from typing import Any, Iterable

MAX_CELLS = 1_500_000   # per sheet — about 20,000 rows of 77 columns
MAX_COLS = 200
MAX_SHEETS = 20
MAX_TEXT_CHARS = 200_000
MAX_BYTES = 25 * 1024 * 1024


class PreviewError(Exception):
    """The file could not be read for a preview. The message is safe to show."""


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        if value.time() == time():
            return value.date().isoformat()
        return value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.10g}"
    return str(value)


def _grid(name: str, rows: Iterable[Iterable[Any]]) -> dict[str, Any]:
    """One sheet: its first rows as text, and how big it really is.

    Trailing empty rows and columns — which spreadsheets carry around after
    formatting — are not counted, so "1,251 rows" means rows with something in them.
    """
    kept: list[list[str]] = []
    kept_cells = 0
    last_row = 0      # rows up to the last one with content
    width = 0         # columns up to the last one with content
    for index, raw in enumerate(rows, start=1):
        cells = [_cell(c) for c in raw]
        while cells and cells[-1] == "":
            cells.pop()
        if cells:
            last_row = index
            width = max(width, len(cells))
        if kept_cells < MAX_CELLS:
            row = cells[:MAX_COLS]
            kept.append(row)
            kept_cells += max(len(row), 1)
    kept = kept[:last_row]
    return {
        "name": name,
        "rows": kept,
        "total_rows": last_row,
        "total_cols": width,
        "truncated": last_row > len(kept) or width > MAX_COLS,
    }


def _delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def build_preview(filename: str, data: bytes) -> dict[str, Any]:
    """The preview for one file, by its extension.

    ``type`` is ``table`` (spreadsheets, CSV), ``document`` (Word), ``too_large``
    or ``unsupported`` — PDFs, images and plain text are shown from the file itself.
    """
    if len(data) > MAX_BYTES:
        return {"type": "too_large", "max_mb": MAX_BYTES // (1024 * 1024)}

    ext = PurePosixPath(filename.lower()).suffix
    try:
        if ext in (".xlsx", ".xlsm"):
            from openpyxl import load_workbook

            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            try:
                sheets = [_grid(ws.title, ws.iter_rows(values_only=True)) for ws in wb.worksheets[:MAX_SHEETS]]
                return {"type": "table", "sheets": sheets, "sheet_count": len(wb.worksheets)}
            finally:
                wb.close()

        if ext in (".csv", ".tsv"):
            text = data.decode("utf-8-sig", errors="replace")
            delimiter = "\t" if ext == ".tsv" else _delimiter(text[:4096])
            name = PurePosixPath(filename).stem or "Sheet"
            return {
                "type": "table",
                "sheets": [_grid(name, csv.reader(io.StringIO(text), delimiter=delimiter))],
                "sheet_count": 1,
            }

        if ext == ".docx":
            from docx import Document

            doc = Document(io.BytesIO(data))
            blocks: list[dict[str, str]] = []
            size = 0
            for p in doc.paragraphs:
                text = p.text.strip()
                if not text:
                    continue
                style = ((p.style.name if p.style is not None else "") or "").lower()
                blocks.append({"kind": "heading" if style.startswith(("heading", "title")) else "paragraph", "text": text})
                size += len(text)
                if size > MAX_TEXT_CHARS:
                    break
            tables = [
                _grid(f"Table {i + 1}", ([cell.text for cell in row.cells] for row in table.rows))
                for i, table in enumerate(doc.tables[:MAX_SHEETS])
            ]
            return {"type": "document", "blocks": blocks, "tables": tables, "truncated": size > MAX_TEXT_CHARS}
    except Exception as e:  # noqa: BLE001 - a damaged file is a message, not a crash
        raise PreviewError("This file couldn't be read for a preview. Download it to open it.") from e

    return {"type": "unsupported"}
