"""The document queues, drained inside the API process.

An uploaded document is useless until it has been parsed, chunked and
embedded, and until this existed that work happened only in two separate
terminals nobody was reliably running. The symptom is the worst kind: the
upload succeeds, the file appears in the sidebar, and every question about it
is answered "I don't have enough information in the knowledge base" — which is
true, permanently, and looks exactly like the product not working.

This is not a second implementation of the workers. It is the same
``process_job`` from each of them, driven by a loop that lives in the API's
event loop instead of its own process. Running both is safe and sometimes
wanted: Redis hands a queued job to exactly one ``BRPOP``, so a standalone
worker and this loop share the queue rather than duplicating it.

What it deliberately does not do is grow into a job system. There is no
concurrency, no priority and no scheduling here — one job at a time, in order,
because a single-tenant deployment processing one upload at a time is the
actual workload, and anything cleverer would be inventing infrastructure to
solve a problem nobody has.
"""

from __future__ import annotations

import asyncio

from loguru import logger

_tasks: list[asyncio.Task] = []


async def _drain(name: str, dequeue, handle) -> None:
    """Take one job at a time, forever, and survive everything.

    Every failure mode here is a reason to keep looping rather than stop: Redis
    restarting, a malformed entry, a job that raises. A drain loop that exits
    on error is indistinguishable from one that was never started, and the
    thing it was added to prevent is precisely a queue silently going unread.
    """
    logger.info(f"In-process {name} worker started")
    idle = 0
    while True:
        try:
            job = await dequeue(timeout=5)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - Redis down is not fatal
            idle += 1
            if idle in (1, 12):  # once, then once a minute of failures
                logger.warning(f"In-process {name} worker cannot reach the queue: {e}")
            await asyncio.sleep(5)
            continue

        idle = 0
        if job is None:
            continue
        try:
            await handle(job)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - one bad job must not end the loop
            logger.exception(f"In-process {name} worker: job failed ({e})")


async def start_inprocess_workers() -> None:
    """Begin draining the document and embedding queues in this process."""
    if _tasks:
        return

    from app.document_platform.processing.queue import dequeue_processing_job
    from app.document_platform.semantic.queue import dequeue_embedding_job
    from app.workers.document_worker import process_job as process_document
    from app.workers.embedding_worker import process_job as process_embedding

    _tasks.append(asyncio.create_task(
        _drain("document", dequeue_processing_job, process_document),
        name="inprocess-document-worker",
    ))
    _tasks.append(asyncio.create_task(
        _drain("embedding", dequeue_embedding_job, process_embedding),
        name="inprocess-embedding-worker",
    ))


async def stop_inprocess_workers() -> None:
    """Cancel the drain loops and wait for them to finish the current job."""
    for task in _tasks:
        task.cancel()
    if _tasks:
        await asyncio.gather(*_tasks, return_exceptions=True)
    _tasks.clear()
