"""
ImageExtractor — persists images found in documents.

Binaries go to blob storage under {user}/{doc}/images/…; metadata rows go to
document_images with page references. Future OCR / Vision phases consume both.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from loguru import logger

from app.document_platform.constants import STORAGE_PREFIX
from app.document_platform.processing.models import ImageRef
from app.storage import get_blob_storage
from app.storage.base import BlobStorage

_FORMAT_MIME = {
    "png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
}


@dataclass
class StoredImage:
    storage_key: str
    name: str
    format: str
    page: Optional[int]
    width: Optional[int]
    height: Optional[int]
    size_bytes: int


class ImageExtractor:
    def __init__(self, storage: BlobStorage | None = None) -> None:
        self._storage = storage or get_blob_storage(STORAGE_PREFIX)

    async def store(
        self, user_id: str, document_id: str, images: list[ImageRef]
    ) -> list[StoredImage]:
        stored: list[StoredImage] = []
        for i, img in enumerate(images):
            fmt = (img.format or "png").lower().lstrip(".")
            if img.content:
                key = f"{user_id}/{document_id}/images/{i:03d}.{fmt}"
                try:
                    await self._storage.put(
                        key, img.content, _FORMAT_MIME.get(fmt, "application/octet-stream")
                    )
                except Exception as e:
                    logger.warning(f"Image store failed for {document_id}[{i}]: {e}")
                    continue
                size = len(img.content)
            else:
                # Referenced but not extractable (e.g. inside a PDF) — metadata only
                key = ""
                size = 0
            stored.append(
                StoredImage(
                    storage_key=key,
                    name=img.name or f"image-{i:03d}",
                    format=fmt,
                    page=img.page,
                    width=img.width,
                    height=img.height,
                    size_bytes=size,
                )
            )
        return stored
