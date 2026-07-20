"""
DIP upload validation — the single gate every upload passes through.

Server-side only; client-declared values are checked, never trusted.
Raises DocumentValidationError with a stable machine-readable code so the
API layer can map errors to HTTP responses without string matching.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from app.document_platform.constants import (
    ALLOWED_EXTENSIONS,
    FILE_TYPES,
    MAGIC_SIGNATURES,
)


class DocumentValidationError(Exception):
    """Rejected upload. `code` is stable for API error mapping."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ValidatedUpload:
    """Output of validation — everything the service needs, all server-derived."""

    safe_filename: str      # sanitised original name (for display / Content-Disposition)
    extension: str          # normalised, with dot, lowercase
    mime_type: str          # canonical MIME derived from extension
    size_bytes: int
    checksum_sha256: str


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


class UploadValidator:
    """
    Validates one upload: filename → extension → size → MIME → content magic.
    Stateless and unit-testable; max size injected for configurability.
    """

    def __init__(self, max_size_bytes: int) -> None:
        self._max_size = max_size_bytes

    def validate(
        self,
        filename: str | None,
        content: bytes,
        declared_mime: str | None,
    ) -> ValidatedUpload:
        # ── Filename ──────────────────────────────────────────────────────────
        if not filename or not filename.strip():
            raise DocumentValidationError("missing_filename", "A filename is required.")

        # Strip any client-supplied path components (both separators), then
        # normalise unicode and remove control characters.
        base = PureWindowsPath(PurePosixPath(filename.strip()).name).name
        base = unicodedata.normalize("NFC", base)
        base = _CONTROL_CHARS_RE.sub("", base).strip()
        if not base or base in (".", "..") or len(base) > 255:
            raise DocumentValidationError("invalid_filename", "The filename is not valid.")

        # ── Extension ─────────────────────────────────────────────────────────
        dot = base.rfind(".")
        if dot <= 0:
            raise DocumentValidationError(
                "missing_extension",
                "The file has no extension. Supported: " + ", ".join(sorted(ALLOWED_EXTENSIONS)),
            )
        ext = base[dot:].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise DocumentValidationError(
                "unsupported_type",
                f"'{ext}' files are not supported. Supported: " + ", ".join(sorted(ALLOWED_EXTENSIONS)),
            )

        # ── Size ──────────────────────────────────────────────────────────────
        size = len(content)
        if size == 0:
            raise DocumentValidationError("empty_file", "The file is empty.")
        if size > self._max_size:
            mb = self._max_size // (1024 * 1024)
            raise DocumentValidationError(
                "file_too_large", f"The file exceeds the {mb} MB limit."
            )

        # ── Declared MIME (validated, not trusted) ────────────────────────────
        canonical_mime, accepted = FILE_TYPES[ext]
        if declared_mime:
            declared = declared_mime.split(";")[0].strip().lower()
            if declared and declared not in accepted:
                raise DocumentValidationError(
                    "mime_mismatch",
                    f"Declared content type '{declared}' does not match a {ext} file.",
                )

        # ── Content sniffing (magic bytes) ────────────────────────────────────
        signatures = MAGIC_SIGNATURES.get(ext)
        if signatures and not any(content.startswith(sig) for sig in signatures):
            raise DocumentValidationError(
                "content_mismatch",
                f"The file content does not look like a valid {ext} file.",
            )

        return ValidatedUpload(
            safe_filename=base,
            extension=ext,
            mime_type=canonical_mime,
            size_bytes=size,
            checksum_sha256=hashlib.sha256(content).hexdigest(),
        )
