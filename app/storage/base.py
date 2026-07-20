"""
Blob storage interface.

Keys are relative POSIX-style paths (e.g. "conv-id/uuid.png") — exactly the
values already stored in MessageImage.storage_path / MessageDocument.storage_path,
so switching backends requires no DB migration.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class BlobStorageError(Exception):
    """Base error for blob storage operations."""


class BlobNotFoundError(BlobStorageError):
    """Raised when a requested blob does not exist."""


class BlobStorage(ABC):
    """Async blob storage interface."""

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        """Store a blob under the given key (overwrites)."""

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Read a blob. Raises BlobNotFoundError if missing."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete a blob (no error if missing)."""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check whether a blob exists."""

    async def signed_url(
        self,
        key: str,
        expires_in: int = 300,
        download_filename: str | None = None,
    ) -> str | None:
        """
        Return a time-limited, pre-authenticated download URL for the blob,
        or None when the backend cannot mint one (e.g. local disk). Callers
        must fall back to proxying bytes through the API when None.
        """
        return None

    @staticmethod
    def normalize_key(key: str) -> str:
        """Normalise Windows-style separators to POSIX for cloud keys."""
        return key.replace("\\", "/")
