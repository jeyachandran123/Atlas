"""
One-time migration: upload existing local attachments to cloud storage
(AWS S3 or Firebase Storage — whichever STORAGE_BACKEND selects).

DB-driven and idempotent — safe to re-run. Local files are left in place as a
backup; delete them manually once you've verified the bucket.

Usage (from backend/, with STORAGE_BACKEND=s3|firebase configured in .env):
    python scripts/migrate_storage_to_cloud.py            # migrate + verify
    python scripts/migrate_storage_to_cloud.py --dry-run  # report only
"""
from __future__ import annotations

import asyncio
import mimetypes
import sys
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.database import get_db_session
from app.db.models import MessageDocument, MessageImage
from app.storage import get_blob_storage
from app.storage.base import BlobStorage

cfg = get_settings()
DRY_RUN = "--dry-run" in sys.argv

VISION_ROOT = Path(cfg.vision_storage_dir)
DOCS_ROOT = Path(cfg.document_storage_dir)


class Stats:
    def __init__(self) -> None:
        self.migrated = 0
        self.skipped = 0
        self.missing = 0

    def __str__(self) -> str:
        return f"migrated={self.migrated}  already-in-cloud={self.skipped}  missing-local={self.missing}"


async def migrate_key(
    blobs: BlobStorage, root: Path, key: str, stats: Stats, mime: str | None = None
) -> None:
    """Upload one local file to the bucket if not already there."""
    key = key.replace("\\", "/")
    if await blobs.exists(key):
        stats.skipped += 1
        return
    local_path = root / key
    if not local_path.exists():
        print(f"  !! missing local file: {local_path}")
        stats.missing += 1
        return
    if DRY_RUN:
        print(f"  would upload: {key}")
        stats.migrated += 1
        return
    content_type = mime or mimetypes.guess_type(key)[0] or "application/octet-stream"
    await blobs.put(key, local_path.read_bytes(), content_type=content_type)
    if not await blobs.exists(key):
        raise RuntimeError(f"Verification failed after upload: {key}")
    stats.migrated += 1
    print(f"  uploaded: {key}")


async def migrate_orphans(blobs: BlobStorage, root: Path, known: set[str], stats: Stats) -> None:
    """Best-effort: upload files on disk that no DB row references (e.g. Redis-only vision context)."""
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        key = str(path.relative_to(root)).replace("\\", "/")
        if key in known:
            continue
        await migrate_key(blobs, root, key, stats)


async def main() -> None:
    if cfg.storage_backend == "local":
        sys.exit("STORAGE_BACKEND is 'local' — set it to 's3' or 'firebase' in .env first.")

    if cfg.storage_backend == "firebase":
        from app.firebase_admin import initialize_firebase
        initialize_firebase()

    print(f"Target backend: {cfg.storage_backend}")
    vision_blobs = get_blob_storage("vision_uploads", local_root=VISION_ROOT)
    doc_blobs = get_blob_storage("document_uploads", local_root=DOCS_ROOT)

    img_stats, doc_stats = Stats(), Stats()
    known_img_keys: set[str] = set()
    known_doc_keys: set[str] = set()

    async with get_db_session() as session:
        images = (await session.execute(select(MessageImage))).scalars().all()
        documents = (await session.execute(select(MessageDocument))).scalars().all()

    print(f"Found {len(images)} image rows, {len(documents)} document rows"
          f"{' (DRY RUN)' if DRY_RUN else ''}\n")

    print("── Images ──")
    for img in images:
        known_img_keys.add(img.storage_path.replace("\\", "/"))
        await migrate_key(vision_blobs, VISION_ROOT, img.storage_path, img_stats, img.mime_type)

    print("── Documents ──")
    for doc in documents:
        known_doc_keys.add(doc.storage_path.replace("\\", "/"))
        known_doc_keys.add(doc.text_path.replace("\\", "/"))
        await migrate_key(doc_blobs, DOCS_ROOT, doc.storage_path, doc_stats, doc.mime_type)
        await migrate_key(doc_blobs, DOCS_ROOT, doc.text_path, doc_stats, "text/plain; charset=utf-8")

    print("── Orphans (files on disk without DB rows) ──")
    await migrate_orphans(vision_blobs, VISION_ROOT, known_img_keys, img_stats)
    await migrate_orphans(doc_blobs, DOCS_ROOT, known_doc_keys, doc_stats)

    print(f"\nImages:    {img_stats}")
    print(f"Documents: {doc_stats}")
    print("\nDone. Local files were left in place as backup — delete backend/data/ "
          "manually once you've verified the bucket contents.")


if __name__ == "__main__":
    asyncio.run(main())
