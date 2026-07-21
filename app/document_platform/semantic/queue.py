"""Embedding processing queue — same Redis conventions as the DIP processing queue."""
from __future__ import annotations

import json
from typing import Any, Optional

from app.redis_client import get_redis

EMBEDDING_QUEUE = "queue:dip_embedding"
EMBEDDING_DEAD_LETTER_QUEUE = "queue:dip_embedding_dead_letter"


async def enqueue_embedding_job(knowledge_id: str, job_id: str, attempt: int = 1) -> None:
    r = get_redis()
    await r.lpush(
        EMBEDDING_QUEUE,
        json.dumps({"knowledge_id": knowledge_id, "job_id": job_id, "attempt": attempt}),
    )


async def dequeue_embedding_job(timeout: int = 5) -> Optional[dict[str, Any]]:
    r = get_redis()
    result = await r.brpop(EMBEDDING_QUEUE, timeout=timeout)
    if result:
        _, raw = result
        return json.loads(raw)
    return None


class EmbeddingDeadLetterSink:
    async def send(self, knowledge_id: str, job_id: str, attempt: int, error: str) -> None:
        r = get_redis()
        await r.lpush(
            EMBEDDING_DEAD_LETTER_QUEUE,
            json.dumps({
                "knowledge_id": knowledge_id, "job_id": job_id,
                "attempt": attempt, "error": error[:2000],
            }),
        )


_sink: EmbeddingDeadLetterSink | None = None


def get_embedding_dead_letter_sink() -> EmbeddingDeadLetterSink:
    global _sink
    if _sink is None:
        _sink = EmbeddingDeadLetterSink()
    return _sink
