"""
Blob storage factory — one singleton per prefix, selected by STORAGE_BACKEND.

Prefixes mirror the historical disk layout so keys stay identical across
backends:
  "vision_uploads"    → data/vision_uploads/...    or  gs://bucket/vision_uploads/...
  "document_uploads"  → data/document_uploads/...  or  gs://bucket/document_uploads/...
"""
from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.storage.base import BlobStorage

_instances: dict[str, BlobStorage] = {}


def get_blob_storage(prefix: str, local_root: Path | None = None) -> BlobStorage:
    """
    Return the blob storage backend for a given prefix.

    Args:
        prefix: logical namespace ("vision_uploads" / "document_uploads")
        local_root: disk root for the local backend AND the read-fallback of
                    the firebase backend. Defaults to data/{prefix}.
    """
    if prefix in _instances:
        return _instances[prefix]

    cfg = get_settings()
    root = local_root or Path("data") / prefix

    if cfg.storage_backend == "s3":
        from app.storage.s3 import S3BlobStorage
        instance: BlobStorage = S3BlobStorage(
            bucket_name=cfg.aws_s3_bucket,
            prefix=prefix,
            region=cfg.aws_region,
            access_key_id=cfg.aws_access_key_id.get_secret_value(),
            secret_access_key=cfg.aws_secret_access_key.get_secret_value(),
            local_fallback_root=root,
        )
    elif cfg.storage_backend == "firebase":
        from app.storage.firebase import FirebaseBlobStorage
        instance = FirebaseBlobStorage(
            bucket_name=cfg.firebase_storage_bucket,
            prefix=prefix,
            local_fallback_root=root,
        )
    else:
        from app.storage.local import LocalBlobStorage
        instance = LocalBlobStorage(root=root)

    _instances[prefix] = instance
    return instance


def reset_blob_storage() -> None:
    """Clear cached instances (for tests)."""
    _instances.clear()
