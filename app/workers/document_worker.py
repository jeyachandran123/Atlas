"""
Document processing worker — background process for the DIP pipeline.

Reads jobs from the Redis queue (queue:dip_processing) and runs the
DocumentProcessingPipeline. Mirrors the repo index worker's lifecycle.

Usage:
  python -m app.workers.document_worker
"""

from __future__ import annotations

import asyncio
import signal

from loguru import logger

from app.database import get_db_session
from app.document_platform.processing.pipeline import DocumentProcessingPipeline
from app.document_platform.processing.queue import dequeue_processing_job
from app.observability import configure_logging

_running = True


def _handle_signal(sig: int, frame: object) -> None:
    global _running
    logger.info(f"Received signal {sig} — stopping document worker after current job")
    _running = False


async def process_job(job: dict) -> None:
    document_id = job["document_id"]
    job_id = job["job_id"]
    logger.info(f"Processing document {document_id} (job {job_id}, attempt {job.get('attempt', 1)})")
    try:
        async with get_db_session() as session:
            pipeline = DocumentProcessingPipeline(session)
            await pipeline.run(document_id, job_id)
            await session.commit()
    except Exception as e:
        logger.exception(f"Document job {job_id} crashed: {e}")


async def main() -> None:
    configure_logging()
    logger.info("Document processing worker started — waiting for jobs")
    while _running:
        try:
            job = await dequeue_processing_job(timeout=5)
        except Exception as e:
            logger.warning(f"Queue read failed (retrying in 5s): {e}")
            await asyncio.sleep(5)
            continue
        if job:
            await process_job(job)
    logger.info("Document processing worker stopped")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    asyncio.run(main())
