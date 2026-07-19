"""Smoke test: S3 blob backend roundtrip against the real configured bucket."""
import asyncio

from app.config import get_settings
from app.storage import get_blob_storage
from app.storage.base import BlobNotFoundError

cfg = get_settings()


async def main() -> None:
    print(f"backend={cfg.storage_backend} bucket={cfg.aws_s3_bucket} region={cfg.aws_region}")
    assert cfg.storage_backend == "s3", "STORAGE_BACKEND is not 's3'"

    blobs = get_blob_storage("vision_uploads")
    key = "smoke-test/roundtrip.txt"
    payload = b"atlas s3 smoke test"

    await blobs.put(key, payload, content_type="text/plain")
    assert await blobs.exists(key), "exists() false after put"
    data = await blobs.get(key)
    assert data == payload, f"roundtrip mismatch: {data!r}"
    await blobs.delete(key)
    assert not await blobs.exists(key), "exists() true after delete"

    try:
        await blobs.get("smoke-test/definitely-missing.bin")
        raise SystemExit("expected BlobNotFoundError")
    except BlobNotFoundError:
        pass

    print("S3_SMOKE_OK")


asyncio.run(main())
