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

from app.adapters.document_vlm.registry import get_document_vlm
from app.config import get_settings
from app.database import get_db_session
from app.document_platform.processing.events import PersistingEventPublisher
from app.document_platform.processing.ocr import (
    OcrService,
    TesseractOcrProvider,
    VlmOcrProvider,
)
from app.document_platform.processing.orchestrator import ProcessingOrchestrator
from app.document_platform.processing.persistence import ProcessingRepository
from app.document_platform.processing.queue import dequeue_processing_job
from app.document_platform.semantic.trigger import EmbeddingTriggerEventPublisher
from app.observability import configure_logging

_running = True

_ocr: OcrService | None = None


def ocr_service() -> OcrService:
    """The OCR stage this worker runs, chosen once.

    This is the worker's composition root. A background process has no request
    to hang dependency injection off, so the single place that picks a provider
    for this process is here — and, as in the API, nothing downstream of this
    function can observe which one was picked.

    Why a vision model rather than nothing: an image reaching the pipeline with
    no text stage produces no chunks, and a document with no chunks is
    retrievable by nothing. The platform then answers every question about that
    image with "I don't have enough information in the knowledge base" — true,
    useless, and indistinguishable to the user from the upload having been
    ignored. Describing the picture gives the rest of the pipeline the text it
    already knows how to index.
    """
    global _ocr
    if _ocr is not None:
        return _ocr

    settings = get_settings()
    if settings.document_ocr_provider == "tesseract":
        _ocr = OcrService(TesseractOcrProvider())
        logger.info("OCR stage: tesseract")
        return _ocr

    try:
        _ocr = OcrService(VlmOcrProvider(get_document_vlm(settings=settings)))
        logger.info(f"OCR stage: vision model ({_ocr.provider_name})")
    except Exception as e:  # noqa: BLE001 - degrade, do not die
        # No vision provider configured, or it failed to bind. Documents still
        # parse, store and list; images simply carry no description, which is
        # exactly the behaviour that existed before this stage was filled.
        logger.warning(f"OCR stage: none - could not bind a vision model ({e})")
        _ocr = OcrService()
    return _ocr


def _handle_signal(sig: int, frame: object) -> None:
    global _running
    logger.info(f"Received signal {sig} — stopping document worker after current job")
    _running = False


TERMINAL_JOB_STATUSES = frozenset({"knowledge_ready", "failed"})
"""A job in one of these has already had its outcome recorded."""


async def _already_finished(job_id: str) -> bool:
    """Has this job already run to a conclusion?

    The queue is at-least-once and nothing removes an entry when its job
    finishes by another route — a retry that created a fresh row, a recovery
    sweep that re-enqueued, a run driven directly. Entries therefore
    accumulate, and a worker starting after a quiet spell finds a backlog of
    work that is already done. Re-running it is not corrupting, but it
    re-parses, re-chunks, re-embeds and re-calls a vision model for every
    image, and to anyone watching the UI it looks like the whole library has
    spontaneously begun reprocessing itself.

    Only terminal statuses are skipped. A row still ``queued`` or ``processing``
    is exactly what recovery re-enqueues on purpose, and must still run.
    """
    try:
        async with get_db_session() as session:
            row = await ProcessingRepository(session).get_job(job_id)
            return row is not None and row.status in TERMINAL_JOB_STATUSES
    except Exception as e:  # noqa: BLE001 - a failed check must not skip work
        logger.warning(f"Could not check job {job_id} state ({e}); processing it")
        return False


async def process_job(job: dict) -> None:
    document_id = job["document_id"]
    job_id = job["job_id"]
    if await _already_finished(job_id):
        logger.info(f"Job {job_id} already finished — dropping stale queue entry")
        return
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
            orchestrator = ProcessingOrchestrator(
                session, event_publisher=trigger, ocr=ocr_service(),
            )
            await orchestrator.run(document_id, job_id)
            await session.commit()
        triggered_knowledge_id = trigger.triggered_knowledge_id
        triggered_correlation_id = trigger.triggered_correlation_id
    except Exception as e:
        logger.exception(f"Document job {job_id} crashed: {e}")
        await _mark_job_crashed(document_id, job_id, e)
        return

    # Only after the document-processing transaction has committed do we
    # create the embedding job row and publish to Redis — same
    # commit-before-publish discipline applied to document processing itself.
    if triggered_knowledge_id:
        await _enqueue_embedding(triggered_knowledge_id, triggered_correlation_id)


async def _mark_job_crashed(document_id: str, job_id: str, exc: Exception) -> None:
    """
    Terminate a job that died *before* the orchestrator could own its failure.

    ProcessingOrchestrator records its own failures — retry, DLQ, job_finished.
    But anything that raises before `run()` is reached (the pre-wipe below, or
    building the orchestrator itself) leaves the row exactly as
    `recover_orphaned_jobs` looks for it: status `queued`, dead_lettered false.
    The sweep then re-enqueues it every 60s, re-publishing the SAME attempt
    number, so MAX_RECOVERY_ATTEMPTS never trips — the document loops forever
    while the UI shows "Processing…" and the reason lives only in this log.

    Marking it failed here makes the failure terminal and, more importantly,
    visible: the document leaves "Processing…" and the error reaches the API.

    Uses a fresh session because the one that raised may hold a broken
    transaction, and never re-raises — the worker must survive to take the
    next job.
    """
    error = f"{type(exc).__name__}: {exc}"[:2000]
    try:
        async with get_db_session() as session:
            repo = ProcessingRepository(session)
            job = await repo.get_job(job_id)
            if job is not None:
                await repo.job_finished(job, "failed", error, dead_lettered=True)
                await repo.add_event(
                    job_id, document_id, "worker", "failed", detail={"error": error}
                )
            doc = await repo.get_document(document_id)
            if doc is not None:
                await repo.set_processing_status(doc, "failed")
            await session.commit()
    except Exception as e:  # noqa: BLE001 — last resort; the log is the record
        logger.error(f"Could not mark document job {job_id} as failed: {e}")


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
