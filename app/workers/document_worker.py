"""
Document processing worker — background process for the DIP pipeline.

Reads jobs from the Redis queue (queue:dip_processing) and runs the
ProcessingOrchestrator. Mirrors the repo index worker's lifecycle.

Usage:
  python -m app.workers.document_worker
"""

from __future__ import annotations

import asyncio
import signal
import time

from loguru import logger

from app.database import get_db_session
from app.document_platform.processing.events import PersistingEventPublisher
from app.document_platform.processing.orchestrator import ProcessingOrchestrator
from app.document_platform.processing.persistence import ProcessingRepository
from app.document_platform.processing.queue import dequeue_processing_job
from app.document_platform.semantic.trigger import EmbeddingTriggerEventPublisher
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
    triggered_knowledge_id: str | None = None
    triggered_correlation_id: str | None = None
    try:
        async with get_db_session() as session:
            # Phase 3 wiring only — ProcessingOrchestrator itself, and
            # everything under processing/ and knowledge/, is untouched.
            #
            # Reprocessing hazard this guards against: ProcessingOrchestrator's
            # frozen wipe_derived() deletes document_chunks for a re-run, but
            # it predates Phase 3 and has no idea embedding_records now holds
            # a foreign key into those chunks. Deleting the semantic layer's
            # rows for this document's CURRENT knowledge object first — before
            # the frozen pipeline touches anything — avoids a foreign key
            # violation without changing a single line of orchestrator.py.
            await _wipe_stale_embeddings(session, document_id)

            trigger = EmbeddingTriggerEventPublisher(
                PersistingEventPublisher(ProcessingRepository(session))
            )
            orchestrator = ProcessingOrchestrator(session, event_publisher=trigger)
            await orchestrator.run(document_id, job_id)
            await session.commit()
        triggered_knowledge_id = trigger.triggered_knowledge_id
        triggered_correlation_id = trigger.triggered_correlation_id
    except Exception as e:
        logger.exception(f"Document job {job_id} crashed: {e}")
        return

    # Only after the document-processing transaction has committed do we
    # create the embedding job row and publish to Redis — same
    # commit-before-publish discipline applied to document processing itself.
    if triggered_knowledge_id:
        await _enqueue_embedding(triggered_knowledge_id, triggered_correlation_id)


async def _wipe_stale_embeddings(session, document_id: str) -> None:
    """Delete embedding_records/semantic_manifests for this document's
    CURRENT knowledge object, if one exists, before the frozen pipeline
    wipes and recreates document_chunks/knowledge_objects underneath it."""
    from app.document_platform.semantic.repository import SemanticRepository

    proc_repo = ProcessingRepository(session)
    existing_ko = await proc_repo.knowledge_for(document_id)
    if existing_ko is not None:
        await SemanticRepository(session).wipe_all_semantic_for_document_reprocess(existing_ko.id)


async def _enqueue_embedding(knowledge_id: str, correlation_id: str | None = None) -> None:
    from app.document_platform.semantic.queue import enqueue_embedding_job
    from app.document_platform.semantic.repository import SemanticRepository

    try:
        async with get_db_session() as session:
            repo = SemanticRepository(session)
            job = await repo.create_job(knowledge_id, correlation_id=correlation_id)
            await session.commit()
        await enqueue_embedding_job(knowledge_id, job.id, 1)
        logger.info(f"Knowledge {knowledge_id} → embedding queued (job {job.id})")
    except Exception as e:
        logger.warning(f"Embedding enqueue failed for knowledge {knowledge_id} (non-fatal): {e}")


async def main() -> None:
    configure_logging()
    logger.info("Document processing worker started — waiting for jobs")

    from app.document_platform.processing.recovery import recover_orphaned_jobs

    # Recovery makes the pipeline self-healing: a document stranded at
    # `queued` because its Redis item was lost (queue/worker restart) would
    # otherwise never progress. Sweep once on startup, then whenever idle.
    reenqueue_cooldown: dict[str, float] = {}
    try:
        recovered = await recover_orphaned_jobs(reenqueue_cooldown)
        if recovered:
            logger.info(f"Startup recovery re-enqueued {recovered} orphaned document(s)")
    except Exception as e:
        logger.warning(f"Startup recovery failed (non-fatal): {e}")
    last_sweep = time.monotonic()

    while _running:
        try:
            job = await dequeue_processing_job(timeout=5)
        except Exception as e:
            logger.warning(f"Queue read failed (retrying in 5s): {e}")
            await asyncio.sleep(5)
            continue
        if job:
            await process_job(job)
        elif time.monotonic() - last_sweep >= 60:
            last_sweep = time.monotonic()
            try:
                recovered = await recover_orphaned_jobs(reenqueue_cooldown)
                if recovered:
                    logger.info(f"Recovery sweep re-enqueued {recovered} orphaned document(s)")
            except Exception as e:
                logger.warning(f"Recovery sweep failed (non-fatal): {e}")
    logger.info("Document processing worker stopped")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    asyncio.run(main())
