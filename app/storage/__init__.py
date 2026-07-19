"""
Storage package — pluggable blob storage for chat attachments.

Backends (selected via STORAGE_BACKEND setting):
  local     → filesystem under a root dir (default; dev + rollback)
  firebase  → Firebase Storage (GCS bucket) via firebase-admin

Usage:
    from app.storage import get_blob_storage
    blobs = get_blob_storage("vision_uploads")   # prefix mirrors disk layout
    await blobs.put("conv-id/uuid.png", data, "image/png")
"""

from app.storage.base import BlobNotFoundError, BlobStorage, BlobStorageError
from app.storage.factory import get_blob_storage

__all__ = [
    "BlobStorage",
    "BlobStorageError",
    "BlobNotFoundError",
    "get_blob_storage",
]
