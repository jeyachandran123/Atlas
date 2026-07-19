"""
Firebase Storage (Google Cloud Storage) blob backend.

Uses the already-initialized Firebase Admin SDK (app/firebase_admin.py) with an
explicit bucket name, so initialize_firebase() needs no changes.

The google-cloud-storage client is synchronous — every call is wrapped in
asyncio.to_thread so the event loop is never blocked.

Read fallback: if a blob is missing in the bucket, we transparently try the
local disk path. This keeps old (not-yet-migrated) files readable during and
after the migration window.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from loguru import logger

from app.storage.base import BlobNotFoundError, BlobStorage, BlobStorageError


class FirebaseBlobStorage(BlobStorage):
    def __init__(
        self,
        bucket_name: str,
        prefix: str,
        local_fallback_root: Optional[Path] = None,
    ) -> None:
        if not bucket_name:
            raise BlobStorageError(
                "FIREBASE_STORAGE_BUCKET is not set. "
                "Enable Storage in the Firebase console and add the bucket name to .env"
            )
        self._bucket_name = bucket_name
        self._prefix = prefix.strip("/")
        self._fallback_root = local_fallback_root
        self._bucket = None  # resolved lazily — requires initialize_firebase() to have run

    def _get_bucket(self):
        if self._bucket is None:
            from firebase_admin import storage as fb_storage
            self._bucket = fb_storage.bucket(name=self._bucket_name)
        return self._bucket

    def _blob_name(self, key: str) -> str:
        return f"{self._prefix}/{self.normalize_key(key)}"

    # ── Sync workers (run in thread) ──────────────────────────────────────────

    def _put_sync(self, key: str, data: bytes, content_type: str) -> None:
        blob = self._get_bucket().blob(self._blob_name(key))
        blob.upload_from_string(data, content_type=content_type)

    def _get_sync(self, key: str) -> bytes:
        from google.cloud.exceptions import NotFound
        blob = self._get_bucket().blob(self._blob_name(key))
        try:
            return blob.download_as_bytes()
        except NotFound:
            raise BlobNotFoundError(f"Blob not found in bucket: {self._blob_name(key)}")

    def _delete_sync(self, key: str) -> None:
        from google.cloud.exceptions import NotFound
        blob = self._get_bucket().blob(self._blob_name(key))
        try:
            blob.delete()
        except NotFound:
            pass

    def _exists_sync(self, key: str) -> bool:
        return self._get_bucket().blob(self._blob_name(key)).exists()

    # ── Async interface ───────────────────────────────────────────────────────

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        try:
            await asyncio.to_thread(self._put_sync, key, data, content_type)
        except BlobStorageError:
            raise
        except Exception as e:
            raise BlobStorageError(f"Firebase Storage upload failed for {key}: {e}") from e

    async def get(self, key: str) -> bytes:
        try:
            return await asyncio.to_thread(self._get_sync, key)
        except BlobNotFoundError:
            # Migration-window fallback: not yet uploaded → try local disk
            if self._fallback_root is not None:
                local_path = self._fallback_root / self.normalize_key(key)
                if local_path.exists():
                    logger.debug(f"Blob {key} served from local fallback")
                    return local_path.read_bytes()
            raise
        except Exception as e:
            raise BlobStorageError(f"Firebase Storage read failed for {key}: {e}") from e

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._delete_sync, key)
        except Exception as e:
            raise BlobStorageError(f"Firebase Storage delete failed for {key}: {e}") from e

    async def exists(self, key: str) -> bool:
        try:
            return await asyncio.to_thread(self._exists_sync, key)
        except Exception as e:
            raise BlobStorageError(f"Firebase Storage exists-check failed for {key}: {e}") from e
