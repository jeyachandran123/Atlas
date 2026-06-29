"""
Index worker — background process that executes indexing jobs.

Reads jobs from the Redis queue and runs the IndexingPipeline.
Designed to run as a separate Docker container or process.

Usage:
  python -m app.workers.index_worker

Or via Docker Compose as the 'worker' service.
"""

from __future__ import annotations

import asyncio
import signal
import sys

from loguru import logger

from app.config import get_settings
from app.database import get_db_session
from app.db.repositories import IndexJobRepository, IndexedFileRepository, RepositoryRepo
from app.indexing.embedder import ChunkEmbedder
from app.indexing.indexer import IndexingPipeline
from app.observability import configure_logging
from app.redis_client import dequeue_index_job
from app.vector_store.chroma_client import get_chroma_store

cfg = get_settings()
_running = True


def _handle_signal(sig: int, frame: object) -> None:
    global _running
    logger.info(f"Received signal {sig} — stopping worker after current job")
    _running = False


async def process_job(job: dict) -> None:
    """Process a single indexing job."""
    job_id = job["job_id"]
    repo_id = job["repo_id"]
    repo_path = job["repo_path"]
    job_type = job.get("job_type", "full")

    logger.info(f"Starting {job_type} index job {job_id} for repo {repo_id}")

    try:
        vector_store = await get_chroma_store()
        embedder = ChunkEmbedder(batch_size=cfg.index_embed_batch_size)

        async with get_db_session() as session:
            pipeline = IndexingPipeline(
                vector_store=vector_store,
                embedder=embedder,
                job_repo=IndexJobRepository(session),
                file_repo=IndexedFileRepository(session),
                repo_repo=RepositoryRepo(session),
            )
            await pipeline.run(
                job_id=job_id,
                repo_id=repo_id,
                repo_path=repo_path,
                job_type=job_type,
            )

        logger.info(f"Completed index job {job_id}")

    except Exception as e:
        logger.exception(f"Index job {job_id} failed: {e}")

        # Mark as failed in DB
        try:
            async with get_db_session() as session:
                job_repo = IndexJobRepository(session)
                await job_repo.fail(job_id, str(e))
        except Exception as db_err:
            logger.error(f"Failed to update job status: {db_err}")


async def run_worker() -> None:
    """Main worker loop — continuously polls Redis for jobs."""
    configure_logging()
    logger.info("Index worker started")

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while _running:
        try:
            job = await dequeue_index_job(timeout=5)
            if job:
                await process_job(job)
            # else: timeout expired, loop again
        except Exception as e:
            logger.error(f"Worker error: {e}")
            await asyncio.sleep(1)

    logger.info("Index worker stopped")


if __name__ == "__main__":
    asyncio.run(run_worker())
