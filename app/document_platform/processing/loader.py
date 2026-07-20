"""DocumentLoader — fetches the original binary from blob storage. Nothing else."""
from __future__ import annotations

from app.document_platform.constants import STORAGE_PREFIX
from app.storage import get_blob_storage
from app.storage.base import BlobStorage


class DocumentLoader:
    def __init__(self, storage: BlobStorage | None = None) -> None:
        self._storage = storage or get_blob_storage(STORAGE_PREFIX)

    async def load(self, storage_key: str) -> bytes:
        return await self._storage.get(storage_key)
