"""DIP processing queue — same Redis conventions as the repo-index queue."""
from __future__ import annotations

import json
from typing import Any, Optional

from app.redis_client import get_redis

PROCESSING_QUEUE = "queue:dip_processing"


async def enqueue_processing_job(document_id: str, job_id: str, attempt: int = 1) -> None:
    r = get_redis()
    await r.lpush(
        PROCESSING_QUEUE,
        json.dumps({"document_id": document_id, "job_id": job_id, "attempt": attempt}),
    )


async def dequeue_processing_job(timeout: int = 5) -> Optional[dict[str, Any]]:
    """Blocking pop from the processing queue."""
    r = get_redis()
    result = await r.brpop(PROCESSING_QUEUE, timeout=timeout)
    if result:
        _, raw = result
        return json.loads(raw)
    return None
