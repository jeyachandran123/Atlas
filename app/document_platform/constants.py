"""
DIP file-type registry.

One source of truth for what the platform accepts. The canonical MIME type is
derived server-side from the extension — the client's declared Content-Type is
validated against the allowlist but never trusted as the stored value.
"""
from __future__ import annotations

# extension → (canonical MIME, accepted declared MIMEs)
FILE_TYPES: dict[str, tuple[str, frozenset[str]]] = {
    ".pdf":  ("application/pdf", frozenset({"application/pdf"})),
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/octet-stream", "application/zip"}),
    ),
    ".xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        frozenset({"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/octet-stream", "application/zip"}),
    ),
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        frozenset({"application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/octet-stream", "application/zip"}),
    ),
    ".csv":  ("text/csv", frozenset({"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel"})),
    ".json": ("application/json", frozenset({"application/json", "text/plain", "text/json"})),
    ".xml":  ("application/xml", frozenset({"application/xml", "text/xml", "text/plain"})),
    ".txt":  ("text/plain", frozenset({"text/plain"})),
    ".md":   ("text/markdown", frozenset({"text/markdown", "text/plain", "text/x-markdown"})),
    ".png":  ("image/png", frozenset({"image/png"})),
    ".jpg":  ("image/jpeg", frozenset({"image/jpeg"})),
    ".jpeg": ("image/jpeg", frozenset({"image/jpeg"})),
    ".gif":  ("image/gif", frozenset({"image/gif"})),
    ".webp": ("image/webp", frozenset({"image/webp"})),
    ".zip":  ("application/zip", frozenset({"application/zip", "application/x-zip-compressed", "application/octet-stream"})),
}

ALLOWED_EXTENSIONS: frozenset[str] = frozenset(FILE_TYPES.keys())

# Magic-byte signatures for server-side content sniffing (never trust the
# client). An entry means: files with this extension MUST start with one of
# these prefixes. Extensions without an entry are text-like and not sniffed.
MAGIC_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".pdf":  (b"%PDF",),
    ".docx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
    ".pptx": (b"PK\x03\x04",),
    ".zip":  (b"PK\x03\x04", b"PK\x05\x06"),  # PK\x05\x06 = empty archive
    ".png":  (b"\x89PNG\r\n\x1a\n",),
    ".jpg":  (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif":  (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),
}

# Blob-storage namespace (mirrors the factory's prefix convention)
STORAGE_PREFIX = "dip_documents"

# Upload lifecycle states
STATUS_UPLOADING = "uploading"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
