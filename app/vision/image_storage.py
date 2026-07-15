"""
Image Storage — handles upload, persistence, and retrieval of images.

Images are stored on the local filesystem under VISION_STORAGE_DIR.
Each image is identified by a SHA256 hash for deduplication.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.vision.schemas import ImageAttachment

# Storage root — relative to backend working directory
VISION_STORAGE_DIR = Path("data/vision_uploads")

# Allowed MIME types
ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/tiff",
}

MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB


class ImageStorageError(Exception):
    pass


class ImageStorage:
    """Manages image file persistence and metadata."""

    def __init__(self, storage_dir: Path = VISION_STORAGE_DIR) -> None:
        self._dir = storage_dir
        self._dir.mkdir(parents=True, exist_ok=True)

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

        # Organize by conversation
        conv_dir = self._dir / conversation_id
        conv_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(filename).suffix or ".png"
        storage_filename = f"{image_id}{ext}"
        storage_path = conv_dir / storage_filename
        storage_path.write_bytes(file_bytes)

        # Get dimensions if possible
        width, height = self._get_dimensions(file_bytes)

        return ImageAttachment(
            id=image_id,
            conversation_id=conversation_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(file_bytes),
            storage_path=str(storage_path.relative_to(self._dir)),
            image_hash=image_hash,
            width=width,
            height=height,
            created_at=datetime.utcnow(),
        )

    def get_path(self, attachment: ImageAttachment) -> Path:
        """Get the absolute filesystem path for an image."""
        return self._dir / attachment.storage_path

    def get_bytes(self, attachment: ImageAttachment) -> bytes:
        """Read image bytes from storage."""
        path = self.get_path(attachment)
        if not path.exists():
            raise ImageStorageError(f"Image not found: {attachment.id}")
        return path.read_bytes()

    def delete(self, attachment: ImageAttachment) -> None:
        """Delete an image from storage."""
        path = self.get_path(attachment)
        if path.exists():
            path.unlink()

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
