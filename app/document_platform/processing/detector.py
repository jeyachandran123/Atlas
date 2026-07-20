"""
FileTypeDetector — confirms the effective type of a stored document.

Re-uses the Phase 1 magic-byte registry. The stored extension is authoritative
(it passed upload validation); detection guards against drift and picks the
parser. ZIP-family disambiguation (docx/xlsx/pptx are all zips) trusts the
extension, since content was already sniffed at upload.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.document_platform.constants import ALLOWED_EXTENSIONS, MAGIC_SIGNATURES


@dataclass(frozen=True)
class DetectedType:
    extension: str          # ".pdf"
    family: str             # "pdf" | "office" | "tabular" | "structured" | "text" | "image" | "archive"
    content_confirmed: bool


_FAMILIES: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "office", ".pptx": "office",
    ".xlsx": "tabular", ".csv": "tabular",
    ".json": "structured", ".xml": "structured",
    ".txt": "text", ".md": "text",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image", ".webp": "image",
    ".zip": "archive",
}


class FileTypeDetector:
    def detect(self, extension: str, content: bytes) -> DetectedType:
        ext = extension.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported extension: {ext}")
        signatures = MAGIC_SIGNATURES.get(ext)
        confirmed = (
            any(content.startswith(sig) for sig in signatures) if signatures else True
        )
        return DetectedType(
            extension=ext,
            family=_FAMILIES.get(ext, "text"),
            content_confirmed=confirmed,
        )
