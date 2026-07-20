"""
Retry Policy (Objective 7).

Classifies failures as retryable or not, decides how many attempts to allow,
and computes exponential backoff. On exhaustion, pushes the job to a real
dead-letter queue (Redis list) — reusing the exact pattern the repo-index
queue and DIP processing queue already use, so this introduces no new
infrastructure concept.

No distributed delay queue exists yet: a retryable failure is re-enqueued
immediately with an incremented attempt counter (the existing `attempt`
field on document_processing_jobs). `backoff_seconds()` is computed and
recorded so a future delayed-queue implementation can honour it without
this policy changing.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.document_platform.processing.parsers.base import ParserError
from app.document_platform.validation import DocumentValidationError
from app.redis_client import get_redis

DEAD_LETTER_QUEUE = "queue:dip_dead_letter"

# Errors that will never succeed on retry — the input itself is invalid.
_NON_RETRYABLE = (ParserError, DocumentValidationError, ValueError, KeyError)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 2.0
    backoff_factor: float = 2.0

    def is_retryable(self, exc: BaseException) -> bool:
        if isinstance(exc, _NON_RETRYABLE):
            return False
        return True

    def should_retry(self, attempt: int, exc: BaseException) -> bool:
        return attempt < self.max_attempts and self.is_retryable(exc)

    def backoff_seconds(self, attempt: int) -> float:
        return round(self.base_delay_seconds * (self.backoff_factor ** max(0, attempt - 1)), 1)


DEFAULT_RETRY_POLICY = RetryPolicy()


class DeadLetterSink:
    """Real, working DLQ — a Redis list, exactly like the existing queues."""

    async def send(self, document_id: str, job_id: str, attempt: int, error: str) -> None:
        import json
        r = get_redis()
        await r.lpush(
            DEAD_LETTER_QUEUE,
            json.dumps({
                "document_id": document_id,
                "job_id": job_id,
                "attempt": attempt,
                "error": error[:2000],
            }),
        )


_sink: DeadLetterSink | None = None


def get_dead_letter_sink() -> DeadLetterSink:
    global _sink
    if _sink is None:
        _sink = DeadLetterSink()
    return _sink
