"""
The zero-modification trigger seam (Objective 2's "Knowledge Ready ->
Embedding Queue" transition).

ProcessingOrchestrator already accepts an injectable `event_publisher`
(Phase 2.5 DI). This wraps the default publisher and CAPTURES — but does
NOT enqueue — a semantic trigger when it observes the "persist" stage
complete. The actual EmbeddingJob creation + Redis push happens in
document_worker.py AFTER its own transaction commits.

That split matters: pushing to Redis before the triggering transaction
commits is exactly the race condition fixed elsewhere in this platform
(the worker's BRPOP can fire faster than another connection can see an
uncommitted row under READ COMMITTED). Committing first, then publishing,
avoids reintroducing that bug here.

This file is the ONLY thing that changes in the composition root
(document_worker.py imports it); orchestrator.py and everything under
processing/ and knowledge/ are untouched.
"""
from __future__ import annotations

from typing import Optional

from app.document_platform.processing.events import EventPublisher, ProcessingEvent


class EmbeddingTriggerEventPublisher(EventPublisher):
    def __init__(self, inner: EventPublisher) -> None:
        self._inner = inner
        self.triggered_knowledge_id: Optional[str] = None
        # Objective 4 — the document's own correlation_id, carried forward
        # so the embedding job traces back to the same originating request
        # instead of minting an unrelated one.
        self.triggered_correlation_id: Optional[str] = None

    async def publish(self, job_id: str, event: ProcessingEvent) -> None:
        await self._inner.publish(job_id, event)
        if event.stage == "persist" and event.status == "completed":
            knowledge_id = event.detail.get("knowledge_id")
            if knowledge_id:
                self.triggered_knowledge_id = knowledge_id
                self.triggered_correlation_id = event.correlation_id
