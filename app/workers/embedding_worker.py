"""
Embedding worker — background process for the Semantic Intelligence Layer.

Reads jobs from the Redis queue (queue:dip_embedding) and runs the
EmbeddingOrchestrator. Mirrors document_worker.py's lifecycle exactly.

Usage:
  python -m app.workers.embedding_worker
"""

from __future__ import annotations

import asyncio
import signal

from loguru import logger

from app.database import get_db_session
from app.document_platform.semantic.orchestrator import EmbeddingOrchestrator
from app.document_platform.semantic.queue import dequeue_embedding_job
from app.observability import configure_logging

_running = True


def _handle_signal(sig: int, frame: object) -> None:
    global _running
    logger.info(f"Received signal {sig} — stopping embedding worker after current job")
    _running = False


async def process_job(job: dict) -> None:
    knowledge_id = job["knowledge_id"]
    job_id = job["job_id"]
    logger.info(f"Embedding knowledge {knowledge_id} (job {job_id}, attempt {job.get('attempt', 1)})")
    try:
        async with get_db_session() as session:
            orchestrator = EmbeddingOrchestrator(session)
            await orchestrator.run(knowledge_id, job_id)
            await session.commit()
    except Exception as e:
        logger.exception(f"Embedding job {job_id} crashed: {e}")


async def main() -> None:
    configure_logging()
    logger.info("Embedding worker started — waiting for jobs")
    while _running:
        try:
            job = await dequeue_embedding_job(timeout=5)
        except Exception as e:
            logger.warning(f"Queue read failed (retrying in 5s): {e}")
            await asyncio.sleep(5)
            continue
        if job:
            await process_job(job)
    logger.info("Embedding worker stopped")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    asyncio.run(main())
