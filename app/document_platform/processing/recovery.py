"""
Orphaned-job recovery — makes the processing pipeline self-healing.

The enqueue-to-Redis step is best-effort by design (a queue outage or a
Redis/worker restart can drop an in-flight list item). Without recovery,
such a document is stranded forever at `queued`: it has a job row but no
worker will ever pick it up again. This reconciler — run once on worker
startup and periodically while the worker is idle — finds those stranded
documents and re-enqueues them, so uploads and save-as-knowledge reliably
progress to knowledge_ready even across infrastructure hiccups.

No frozen business logic is touched: it only re-publishes an existing job
for an existing document row. Reprocessing is idempotent (wipe_derived).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import select

from app.database import get_db_session
from app.db.models import Document, DocumentProcessingJob
from app.document_platform.processing.queue import enqueue_processing_job

# A job younger than this may still be legitimately in flight — don't touch it.
STALE_AFTER_SECONDS = 90
# Give up re-enqueuing a document that has already burned through this many
# attempts (its own retry/DLQ path owns terminal failure).
MAX_RECOVERY_ATTEMPTS = 5


async def recover_orphaned_jobs(
    cooldown: dict[str, float], cooldown_seconds: float = 300.0,
) -> int:
    """
    Re-enqueue documents stranded at `queued` with a stale, non-dead-lettered
    job. `cooldown` is a caller-owned dict tracking recent re-enqueues so the
    same document is not re-published on every sweep. Returns the count
    re-enqueued.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STALE_AFTER_SECONDS)
    async with get_db_session() as session:
        rows = (
            await session.execute(
                select(
                    Document.id,
                    DocumentProcessingJob.id,
                    DocumentProcessingJob.attempt,
                )
                .join(DocumentProcessingJob, DocumentProcessingJob.document_id == Document.id)
                .where(
                    Document.processing_status == "queued",
                    DocumentProcessingJob.status == "queued",
                    DocumentProcessingJob.dead_lettered.is_(False),
                    DocumentProcessingJob.created_at < cutoff,
                )
                .order_by(DocumentProcessingJob.created_at.desc())
            )
        ).all()

    now = time.monotonic()
    seen: set[str] = set()
    reenqueued = 0
    for doc_id, job_id, attempt in rows:
        if doc_id in seen:  # only the latest job per document
            continue
        seen.add(doc_id)
        if (attempt or 1) > MAX_RECOVERY_ATTEMPTS:
            continue
        if now - cooldown.get(doc_id, 0.0) < cooldown_seconds:
            continue
        cooldown[doc_id] = now
        try:
            await enqueue_processing_job(doc_id, job_id, attempt or 1)
            reenqueued += 1
        except Exception as e:
            logger.warning(f"Recovery re-enqueue failed for {doc_id} (will retry next sweep): {e}")
    return reenqueued
