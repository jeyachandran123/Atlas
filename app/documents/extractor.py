"""
Document text extraction.

Supported types:
  - PDF (.pdf)            → pypdf
  - Word (.docx)          → python-docx (paragraphs + tables)
  - Excel (.xlsx, .xlsm)  → openpyxl (every sheet, as rows)
  - Plain text families   → direct decode (.txt, .md, .csv, .json, code files, …)

Legacy binary .doc and .xls are NOT supported — users get a clear error asking
for .docx / .xlsx or PDF instead.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class DocumentExtractionError(Exception):
    """Raised when a document cannot be parsed or its type is unsupported."""


# Extensions treated as plain text (decoded directly, no parser needed)
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl",
    ".yaml", ".yml", ".toml", ".xml", ".html", ".htm", ".log", ".ini", ".cfg",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cs", ".go", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".rb", ".php", ".sql", ".sh", ".ps1", ".css",
}

SPREADSHEET_EXTENSIONS = {".xlsx", ".xlsm"}

SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | SPREADSHEET_EXTENSIONS | {".pdf", ".docx"}

# How much of a spreadsheet goes into the text used for chat context. The full
# file is always kept: questions that need every row are answered by running
# code over the original, not by reading this preview.
_SHEET_PREVIEW_ROWS = 300


def is_supported_document(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS


@dataclass
class ExtractedText:
    """Result of a text extraction pass."""
    text: str
    page_count: Optional[int] = None  # PDFs only

    @property
    def char_count(self) -> int:
        return len(self.text)


def extract_text(file_bytes: bytes, filename: str) -> ExtractedText:
    """
    Extract plain text from an uploaded document.

    Raises DocumentExtractionError for unsupported types or parse failures.
    """
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        return _extract_pdf(file_bytes, filename)
    if ext == ".docx":
        return _extract_docx(file_bytes, filename)
    if ext in SPREADSHEET_EXTENSIONS:
        return _extract_xlsx(file_bytes, filename)
    if ext == ".doc":
        raise DocumentExtractionError(
            f"Legacy .doc format is not supported ({filename}). "
            "Please save the file as .docx or PDF and upload again."
        )
    if ext == ".xls":
        raise DocumentExtractionError(
            f"Legacy .xls format is not supported ({filename}). "
            "Please save the file as .xlsx or .csv and upload again."
        )
    if ext in TEXT_EXTENSIONS:
        return _extract_plain_text(file_bytes, filename)

    raise DocumentExtractionError(
        f"Unsupported document type: {ext or 'no extension'} ({filename}). "
        f"Supported: PDF, Word (.docx), Excel (.xlsx), and text files."
    )


def _extract_pdf(file_bytes: bytes, filename: str) -> ExtractedText:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise DocumentExtractionError(
            "PDF support is not installed. Run: pip install pypdf"
        ) from e

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        if reader.is_encrypted:
            # Try empty-password decryption (common for "protected" PDFs)
            try:
                reader.decrypt("")
            except Exception:
                raise DocumentExtractionError(
                    f"PDF is password-protected: {filename}"
                )
        pages = []
        for i, page in enumerate(reader.pages):
            page_text = (page.extract_text() or "").strip()
            if page_text:
                pages.append(f"[Page {i + 1}]\n{page_text}")
        text = "\n\n".join(pages)
        if not text.strip():
            raise DocumentExtractionError(
                f"No extractable text found in PDF: {filename}. "
                "It may be a scanned/image-only PDF — try uploading page screenshots "
                "as images instead so the vision model can read them."
            )
        return ExtractedText(text=text, page_count=len(reader.pages))
    except DocumentExtractionError:
        raise
    except Exception as e:
        raise DocumentExtractionError(f"Failed to parse PDF {filename}: {e}") from e


def _extract_docx(file_bytes: bytes, filename: str) -> ExtractedText:
    try:
        import docx  # python-docx
    except ImportError as e:
        raise DocumentExtractionError(
            "Word support is not installed. Run: pip install python-docx"
        ) from e

    try:
        document = docx.Document(io.BytesIO(file_bytes))
        parts: list[str] = []

        for para in document.paragraphs:
            if para.text.strip():
                parts.append(para.text)

        # Tables — render as pipe-separated rows so the LLM can read them
        for table in document.tables:
            rows = []
            for row in table.rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                rows.append(" | ".join(cells))
            if rows:
                parts.append("\n".join(rows))

        text = "\n\n".join(parts)
        if not text.strip():
            raise DocumentExtractionError(f"No extractable text found in Word file: {filename}")
        return ExtractedText(text=text)
    except DocumentExtractionError:
        raise
    except Exception as e:
        raise DocumentExtractionError(f"Failed to parse Word file {filename}: {e}") from e


def _extract_xlsx(file_bytes: bytes, filename: str) -> ExtractedText:
    """Every sheet as pipe-separated rows, with its true size stated.

    The preview is capped, and says so: a model reading 300 rows of a 1,251-row
    sheet must know it has not seen them all, or it will count what it can see
    and report that as the total.
    """
    try:
        from openpyxl import load_workbook
    except ImportError as e:
        raise DocumentExtractionError(
            "Excel support is not installed. Run: pip install openpyxl"
        ) from e

    try:
        wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        parts: list[str] = []
        for ws in wb.worksheets:
            rows: list[str] = []
            total = 0
            for row in ws.iter_rows(values_only=True):
                cells = ["" if v is None else str(v).replace("\n", " ").strip() for v in row]
                if not any(cells):
                    continue
                total += 1
                if len(rows) < _SHEET_PREVIEW_ROWS + 1:  # header + preview rows
                    while cells and not cells[-1]:
                        cells.pop()
                    rows.append(" | ".join(cells))
            if not rows:
                continue
            data_rows = max(0, total - 1)
            shown = max(0, len(rows) - 1)
            header = f"[Sheet: {ws.title}] {data_rows} data rows"
            if shown < data_rows:
                header += f" (first {shown} shown below; the full sheet is kept for calculations)"
            parts.append(header + "\n" + "\n".join(rows))
        wb.close()
        text = "\n\n".join(parts)
        if not text.strip():
            raise DocumentExtractionError(f"No data found in Excel file: {filename}")
        return ExtractedText(text=text)
    except DocumentExtractionError:
        raise
    except Exception as e:
        raise DocumentExtractionError(f"Failed to parse Excel file {filename}: {e}") from e


def _extract_plain_text(file_bytes: bytes, filename: str) -> ExtractedText:
    if b"\x00" in file_bytes[:8192]:
        raise DocumentExtractionError(f"File appears to be binary, not text: {filename}")
    text = file_bytes.decode("utf-8", errors="replace").strip()
    if not text:
        raise DocumentExtractionError(f"File is empty: {filename}")
    return ExtractedText(text=text)
