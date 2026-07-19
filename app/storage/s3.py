"""
AWS S3 blob backend.

Uses boto3 with explicit credentials from settings (falls back to the default
AWS credential chain — env vars / instance profile — when not set).

boto3 is synchronous — every call is wrapped in asyncio.to_thread so the event
loop is never blocked.

Read fallback: if an object is missing in the bucket, we transparently try the
local disk path. This keeps old (not-yet-migrated) files readable during and
after the migration window.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from loguru import logger

from app.storage.base import BlobNotFoundError, BlobStorage, BlobStorageError


class S3BlobStorage(BlobStorage):
    def __init__(
        self,
        bucket_name: str,
        prefix: str,
        region: str = "us-east-1",
        access_key_id: str = "",
        secret_access_key: str = "",
        local_fallback_root: Optional[Path] = None,
    ) -> None:
        if not bucket_name:
            raise BlobStorageError(
                "AWS_S3_BUCKET is not set. Create a private S3 bucket and add its name to .env"
            )
        self._bucket_name = bucket_name
        self._prefix = prefix.strip("/")
        self._region = region
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._fallback_root = local_fallback_root
        self._client = None  # boto3 client, created lazily (thread-safe for our use)

    def _get_client(self):
        if self._client is None:
            import boto3
            kwargs: dict = {"region_name": self._region}
            if self._access_key_id and self._secret_access_key:
                kwargs["aws_access_key_id"] = self._access_key_id
                kwargs["aws_secret_access_key"] = self._secret_access_key
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def _object_key(self, key: str) -> str:
        return f"{self._prefix}/{self.normalize_key(key)}"

    @staticmethod
    def _is_missing(exc: Exception) -> bool:
        """True when a botocore ClientError means 'object does not exist'."""
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        return code in ("404", "NoSuchKey", "NotFound")

    # ── Sync workers (run in thread) ──────────────────────────────────────────

    def _put_sync(self, key: str, data: bytes, content_type: str) -> None:
        self._get_client().put_object(
            Bucket=self._bucket_name,
            Key=self._object_key(key),
            Body=data,
            ContentType=content_type,
        )

    def _get_sync(self, key: str) -> bytes:
        from botocore.exceptions import ClientError
        try:
            resp = self._get_client().get_object(
                Bucket=self._bucket_name, Key=self._object_key(key)
            )
            return resp["Body"].read()
        except ClientError as e:
            if self._is_missing(e):
                raise BlobNotFoundError(f"Object not found in S3: {self._object_key(key)}")
            raise

    def _delete_sync(self, key: str) -> None:
        # S3 delete_object is a no-op for missing keys — no error handling needed
        self._get_client().delete_object(Bucket=self._bucket_name, Key=self._object_key(key))

    def _exists_sync(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self._get_client().head_object(Bucket=self._bucket_name, Key=self._object_key(key))
            return True
        except ClientError as e:
            if self._is_missing(e):
                return False
            raise

    # ── Async interface ───────────────────────────────────────────────────────

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        try:
            await asyncio.to_thread(self._put_sync, key, data, content_type)
        except BlobStorageError:
            raise
        except Exception as e:
            raise BlobStorageError(f"S3 upload failed for {key}: {e}") from e

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
            raise BlobStorageError(f"S3 read failed for {key}: {e}") from e

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._delete_sync, key)
        except Exception as e:
            raise BlobStorageError(f"S3 delete failed for {key}: {e}") from e

    async def exists(self, key: str) -> bool:
        try:
            return await asyncio.to_thread(self._exists_sync, key)
        except Exception as e:
            raise BlobStorageError(f"S3 exists-check failed for {key}: {e}") from e
