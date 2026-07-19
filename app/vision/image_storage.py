"""
Image Storage — handles upload, persistence, and retrieval of images.

Storage is delegated to the pluggable blob backend (app/storage):
  STORAGE_BACKEND=local    → data/vision_uploads/{conversation_id}/{id}{ext}
  STORAGE_BACKEND=firebase → gs://<bucket>/vision_uploads/{conversation_id}/{id}{ext}

Keys stored in MessageImage.storage_path are identical across backends, so
switching requires no DB migration. Each image is identified by a SHA256 hash
for deduplication.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.storage import BlobNotFoundError, BlobStorage, get_blob_storage
from app.vision.schemas import ImageAttachment

# Storage root — local backend root AND cloud key prefix
VISION_STORAGE_DIR = Path("data/vision_uploads")

# Allowed MIME types
ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/tiff",
}

MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB


class ImageStorageError(Exception):
    pass


class ImageStorage:
    """Manages image persistence and metadata via the blob storage backend."""

    def __init__(self, blobs: Optional[BlobStorage] = None) -> None:
        self._blobs = blobs or get_blob_storage("vision_uploads", local_root=VISION_STORAGE_DIR)

    async def store(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        conversation_id: str,
    ) -> ImageAttachment:
        """Store an image and return its metadata."""
        if mime_type not in ALLOWED_MIME_TYPES:
            raise ImageStorageError(f"Unsupported image type: {mime_type}")
        if len(file_bytes) > MAX_IMAGE_SIZE:
            raise ImageStorageError(f"Image too large: {len(file_bytes)} bytes (max {MAX_IMAGE_SIZE})")

        image_hash = hashlib.sha256(file_bytes).hexdigest()
        image_id = str(uuid.uuid4())

        ext = Path(filename).suffix or ".png"
        # Key layout mirrors the historical disk layout: {conversation_id}/{id}{ext}
        storage_key = f"{conversation_id}/{image_id}{ext}"

        await self._blobs.put(storage_key, file_bytes, content_type=mime_type)

        # Get dimensions if possible
        width, height = self._get_dimensions(file_bytes)

        return ImageAttachment(
            id=image_id,
            conversation_id=conversation_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(file_bytes),
            storage_path=storage_key,
            image_hash=image_hash,
            width=width,
            height=height,
            created_at=datetime.utcnow(),
        )

    async def get_bytes(self, attachment: ImageAttachment) -> bytes:
        """Read image bytes from storage."""
        return await self.get_bytes_by_key(attachment.storage_path)

    async def get_bytes_by_key(self, storage_key: str) -> bytes:
        """Read image bytes by raw storage key (as stored in MessageImage.storage_path)."""
        try:
            return await self._blobs.get(storage_key)
        except BlobNotFoundError as e:
            raise ImageStorageError(f"Image not found: {storage_key}") from e

    async def delete(self, attachment: ImageAttachment) -> None:
        """Delete an image from storage."""
        await self._blobs.delete(attachment.storage_path)

    @staticmethod
    def _get_dimensions(data: bytes) -> tuple[Optional[int], Optional[int]]:
        """Extract image dimensions without heavy dependencies."""
        try:
            # PNG
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                w = int.from_bytes(data[16:20], "big")
                h = int.from_bytes(data[20:24], "big")
                return w, h
            # JPEG
            if data[:2] == b"\xff\xd8":
                import struct
                idx = 2
                while idx < len(data) - 1:
                    if data[idx] != 0xFF:
                        break
                    marker = data[idx + 1]
                    if marker in (0xC0, 0xC2):
                        h = struct.unpack(">H", data[idx + 5:idx + 7])[0]
                        w = struct.unpack(">H", data[idx + 7:idx + 9])[0]
                        return w, h
                    length = struct.unpack(">H", data[idx + 2:idx + 4])[0]
                    idx += 2 + length
        except Exception:
            pass
        return None, None


# Singleton
_storage: ImageStorage | None = None


def get_image_storage() -> ImageStorage:
    global _storage
    if _storage is None:
        _storage = ImageStorage()
    return _storage
