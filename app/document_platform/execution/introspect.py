"""Describe a document's real structure, so the model writes code against facts.

Retrieval was the wrong instrument for this. It hands the model eight semantic
chunks out of hundreds and no sense of the whole: asked how many rows a 1252-row
sheet had, a model reading chunks answered "20", because twenty was all it could
see. Code cannot be written against a sample either - the difference between
``Soft & Bite`` (what people call the column) and ``Soft and bite-sized`` (what
the header actually says) is the difference between working code and a KeyError.

So this reads the file itself and reports exact headers, exact types and a few
real rows. It is cheap - openpyxl in read-only mode streams rows rather than
loading the workbook - and it is bounded, because the description goes into a
prompt.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field

from loguru import logger

SAMPLE_ROWS = 5
MAX_COLUMNS_LISTED = 200
MAX_CELL_CHARS = 60
MAX_DESCRIPTION_CHARS = 12_000
"""The description shares a prompt with the request and the rules. A sheet with
hundreds of columns is summarised rather than allowed to crowd them out."""


@dataclass
class SheetStructure:
    name: str
    rows: int
    columns: int
    headers: list[str] = field(default_factory=list)
    dtypes: dict[str, str] = field(default_factory=dict)
    samples: list[list[str]] = field(default_factory=list)


@dataclass
class DocumentStructure:
    filename: str
    kind: str                        # xlsx | csv | docx | pdf | html | json | text
    summary: str                     # one line, e.g. "1251 rows x 77 columns"
    sheets: list[SheetStructure] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_prompt_text(self, include_samples: bool = True) -> str:
        """The description that goes into the prompt.

        ``include_samples`` is the one privacy control that matters here: with
        it off, the prompt carries column names and inferred types and no cell
        values at all. The rows themselves are never sent either way - they are
        read inside a container with no network.
        """
        lines = [f"FILE: {self.filename}", f"TYPE: {self.kind}", f"SHAPE: {self.summary}"]
        for sheet in self.sheets:
            lines.append("")
            lines.append(f"SHEET {sheet.name!r}: {sheet.rows} data rows x {sheet.columns} columns")
            lines.append("COLUMN NAMES (exact, use these verbatim):")
            for i, header in enumerate(sheet.headers[:MAX_COLUMNS_LISTED]):
                dtype = sheet.dtypes.get(header, "unknown")
                lines.append(f"  {i:>3}. {header!r}  [{dtype}]")
            if len(sheet.headers) > MAX_COLUMNS_LISTED:
                lines.append(f"  ... {len(sheet.headers) - MAX_COLUMNS_LISTED} more columns")
            if sheet.samples and include_samples:
                lines.append(f"SAMPLE ROWS (first {len(sheet.samples)}):")
                for row in sheet.samples:
                    lines.append("  " + " | ".join(row))
        for note in self.notes:
            lines.append("")
            lines.append(note)
        text = "\n".join(lines)
        return text[:MAX_DESCRIPTION_CHARS]


def _cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return text[:MAX_CELL_CHARS]


def _infer_dtype(values: list[object]) -> str:
    """Name the type a person would call it, from the values actually present.

    Reported per column so generated code does not, say, do string slicing on a
    column of integers. Blank-only columns are called that rather than guessed
    at - they are common in these sheets and they matter to a transform.
    """
    present = [v for v in values if v is not None and str(v).strip() != ""]
    if not present:
        return "blank"
    kinds = set()
    for v in present:
        if isinstance(v, bool):
            kinds.add("boolean")
        elif isinstance(v, int):
            kinds.add("integer")
        elif isinstance(v, float):
            kinds.add("integer" if float(v).is_integer() else "decimal")
        elif hasattr(v, "year") and hasattr(v, "month"):
            kinds.add("date")
        else:
            kinds.add("string")
    if kinds == {"string"}:
        flags = {str(v).strip().lower() for v in present}
        if flags and flags <= {"x", "y", "yes", "no", "true", "false"}:
            return "flag"
        return "string"
    if len(kinds) == 1:
        return kinds.pop()
    return "mixed(" + ",".join(sorted(kinds)) + ")"


def _excel(data: bytes, filename: str) -> DocumentStructure:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    sheets: list[SheetStructure] = []
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        try:
            header_row = next(rows)
        except StopIteration:
            sheets.append(SheetStructure(name=ws.title, rows=0, columns=0))
            continue
        headers = [_cell(h) or f"column_{i}" for i, h in enumerate(header_row)]

        samples: list[list[str]] = []
        column_values: list[list[object]] = [[] for _ in headers]
        data_rows = 0
        for row in rows:
            if all(v is None or str(v).strip() == "" for v in row):
                continue
            data_rows += 1
            if data_rows <= 50:  # types are inferred from a window, not the file
                for i, v in enumerate(row[: len(headers)]):
                    column_values[i].append(v)
            if len(samples) < SAMPLE_ROWS:
                samples.append([_cell(v) for v in row[: len(headers)]])
        sheets.append(SheetStructure(
            name=ws.title,
            rows=data_rows,
            columns=len(headers),
            headers=headers,
            dtypes={h: _infer_dtype(column_values[i]) for i, h in enumerate(headers)},
            samples=samples,
        ))
    wb.close()
    total = ", ".join(f"{s.name}: {s.rows}x{s.columns}" for s in sheets) or "empty"
    return DocumentStructure(filename=filename, kind="xlsx", summary=total, sheets=sheets)


def _csv(data: bytes, filename: str) -> DocumentStructure:
    text = data.decode("utf-8-sig", errors="replace")
    sample = text[:64_000]
    try:
        dialect = csv.Sniffer().sniff(sample.split("\n\n")[0][:4000])
        delimiter = dialect.delimiter
    except Exception:  # noqa: BLE001 - an unsniffable file is almost always a comma
        delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        headers = [_cell(h) or f"column_{i}" for i, h in enumerate(next(reader))]
    except StopIteration:
        return DocumentStructure(filename=filename, kind="csv", summary="empty")
    samples, column_values, count = [], [[] for _ in headers], 0
    for row in reader:
        if not any(str(v).strip() for v in row):
            continue
        count += 1
        if count <= 50:
            for i, v in enumerate(row[: len(headers)]):
                column_values[i].append(v)
        if len(samples) < SAMPLE_ROWS:
            samples.append([_cell(v) for v in row[: len(headers)]])
    sheet = SheetStructure(
        name="(csv)", rows=count, columns=len(headers), headers=headers,
        dtypes={h: _infer_dtype(column_values[i]) for i, h in enumerate(headers)},
        samples=samples,
    )
    return DocumentStructure(
        filename=filename, kind="csv", summary=f"{count} rows x {len(headers)} columns",
        sheets=[sheet], notes=[f"DELIMITER: {delimiter!r}"],
    )


def _docx(data: bytes, filename: str) -> DocumentStructure:
    import docx

    doc = docx.Document(io.BytesIO(data))
    paragraphs = [p for p in doc.paragraphs if p.text.strip()]
    headings = [p.text.strip()[:80] for p in paragraphs if p.style.name.startswith("Heading")]
    notes = [
        f"PARAGRAPHS: {len(paragraphs)}",
        f"TABLES: {len(doc.tables)}",
    ]
    if headings:
        notes.append("HEADINGS:\n" + "\n".join(f"  - {h}" for h in headings[:40]))
    if paragraphs:
        notes.append("FIRST PARAGRAPHS:\n" + "\n".join(
            f"  {p.text.strip()[:160]}" for p in paragraphs[:5]))
    sheets = []
    for i, table in enumerate(doc.tables[:5]):
        rows = len(table.rows)
        cols = len(table.columns) if rows else 0
        headers = [_cell(c.text) for c in table.rows[0].cells] if rows else []
        samples = [[_cell(c.text) for c in r.cells] for r in table.rows[1 : 1 + SAMPLE_ROWS]]
        sheets.append(SheetStructure(
            name=f"table[{i}]", rows=max(0, rows - 1), columns=cols,
            headers=headers, samples=samples,
        ))
    return DocumentStructure(
        filename=filename, kind="docx",
        summary=f"{len(paragraphs)} paragraphs, {len(doc.tables)} tables",
        sheets=sheets, notes=notes,
    )


def _pdf(data: bytes, filename: str) -> DocumentStructure:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = len(reader.pages)
    first = ""
    if pages:
        try:
            first = (reader.pages[0].extract_text() or "")[:1200]
        except Exception as e:  # noqa: BLE001 - an unreadable page is a fact, not a crash
            first = f"(text could not be extracted: {type(e).__name__})"
    notes = [f"PAGES: {pages}", "FIRST PAGE TEXT:\n" + first]
    if not first.strip():
        notes.append(
            "NOTE: no extractable text - this PDF is probably scanned images."
        )
    return DocumentStructure(
        filename=filename, kind="pdf", summary=f"{pages} pages", notes=notes,
    )


def _json(data: bytes, filename: str) -> DocumentStructure:
    parsed = json.loads(data.decode("utf-8", errors="replace"))
    if isinstance(parsed, list):
        shape = f"array of {len(parsed)} items"
        keys = sorted({k for item in parsed[:50] if isinstance(item, dict) for k in item})
    elif isinstance(parsed, dict):
        shape = f"object with {len(parsed)} top-level keys"
        keys = sorted(parsed)
    else:
        shape, keys = type(parsed).__name__, []
    notes = [f"KEYS: {', '.join(keys[:80])}"] if keys else []
    notes.append("SAMPLE:\n" + json.dumps(parsed, default=str)[:1500])
    return DocumentStructure(filename=filename, kind="json", summary=shape, notes=notes)


def _text(data: bytes, filename: str, kind: str) -> DocumentStructure:
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    return DocumentStructure(
        filename=filename, kind=kind, summary=f"{len(lines)} lines, {len(text)} characters",
        notes=["FIRST LINES:\n" + "\n".join(f"  {ln[:160]}" for ln in lines[:15])],
    )


_READERS = {
    "xlsx": _excel, "xlsm": _excel, "xls": _excel,
    "csv": _csv, "tsv": _csv,
    "docx": _docx,
    "pdf": _pdf,
    "json": _json,
}


def introspect(data: bytes, filename: str) -> DocumentStructure:
    """Read the document and describe it. Never raises: an unreadable file is
    still a file the model can be told about, and refusing to describe it would
    turn a recoverable situation into a dead end."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    reader = _READERS.get(ext)
    try:
        if reader is not None:
            return reader(data, filename)
        if ext in ("html", "htm", "xml", "md", "markdown", "txt", "log"):
            return _text(data, filename, ext)
        return _text(data, filename, ext or "unknown")
    except Exception as e:  # noqa: BLE001 - describe what went wrong, keep going
        logger.warning(f"Could not introspect {filename}: {type(e).__name__}: {e}")
        return DocumentStructure(
            filename=filename, kind=ext or "unknown",
            summary=f"{len(data)} bytes (structure could not be read)",
            notes=[f"NOTE: reading the structure failed with {type(e).__name__}: {e}. "
                   f"Inspect the file in code before transforming it."],
        )
