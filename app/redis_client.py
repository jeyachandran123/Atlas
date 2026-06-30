"""
Redis client — connection pool and utility helpers.

Redis owns: session memory, rate limiting, index job progress,
distributed locks, model health cache, job queues.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import redis.asyncio as aioredis

from app.config import get_settings

settings = get_settings()

_redis_pool: aioredis.ConnectionPool | None = None
_redis_client: aioredis.Redis | None = None


def get_redis_pool() -> aioredis.ConnectionPool:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=settings.redis_max_connections,
            decode_responses=True,
        )
    return _redis_pool


def get_redis() -> aioredis.Redis:
    """Return a Redis client using the shared connection pool."""
    return aioredis.Redis(connection_pool=get_redis_pool())


async def close_redis() -> None:
    global _redis_pool, _redis_client
    if _redis_pool:
        await _redis_pool.aclose()
        _redis_pool = None


# ─────────────────────────────────────────────────────────────────────────────
# SESSION MEMORY
# ─────────────────────────────────────────────────────────────────────────────

SESSION_WINDOW = 20  # last N messages kept in Redis
SESSION_TTL = 86400  # 24 hours


async def push_session_message(
    user_id: str,
    conversation_id: str,
    role: str,
    content: str,
) -> None:
    """Add a message to the session window, trim to last SESSION_WINDOW messages."""
    key = f"session:{user_id}:{conversation_id}"
    r = get_redis()
    message = json.dumps({"role": role, "content": content})
    await r.lpush(key, message)
    await r.ltrim(key, 0, SESSION_WINDOW - 1)
    await r.expire(key, SESSION_TTL)


async def get_session_messages(
    user_id: str,
    conversation_id: str,
) -> list[dict[str, str]]:
    """Retrieve session messages in chronological order."""
    key = f"session:{user_id}:{conversation_id}"
    r = get_redis()
    raw = await r.lrange(key, 0, -1)
    # Messages are stored newest-first (LPUSH), reverse for chronological
    return [json.loads(m) for m in reversed(raw)]


# ─────────────────────────────────────────────────────────────────────────────
# INDEX JOB PROGRESS
# ─────────────────────────────────────────────────────────────────────────────

PROGRESS_TTL = 7200  # 2 hours


async def set_index_progress(job_id: str, progress: dict[str, Any]) -> None:
    r = get_redis()
    # Convert all values to strings for Redis HSET
    string_progress = {k: str(v) for k, v in progress.items()}
    await r.hset(f"index:progress:{job_id}", mapping=string_progress)
    await r.expire(f"index:progress:{job_id}", PROGRESS_TTL)


async def get_index_progress(job_id: str) -> Optional[dict[str, str]]:
    r = get_redis()
    data = await r.hgetall(f"index:progress:{job_id}")
    return data if data else None


# ─────────────────────────────────────────────────────────────────────────────
# DISTRIBUTED LOCKS
# ─────────────────────────────────────────────────────────────────────────────


async def acquire_lock(key: str, value: str, ttl_seconds: int = 3600) -> bool:
    """Acquire a distributed lock. Returns True if acquired, False if already held."""
    r = get_redis()
    return await r.set(key, value, nx=True, ex=ttl_seconds) is not None


async def release_lock(key: str, value: str) -> None:
    """Release a lock only if we hold it (compare-and-delete)."""
    r = get_redis()
    current = await r.get(key)
    if current == value:
        await r.delete(key)


# ─────────────────────────────────────────────────────────────────────────────
# JOB QUEUE
# ─────────────────────────────────────────────────────────────────────────────

INDEX_QUEUE = "queue:index_jobs"


async def enqueue_index_job(job: dict[str, Any]) -> None:
    r = get_redis()
    await r.lpush(INDEX_QUEUE, json.dumps(job))


async def dequeue_index_job(timeout: int = 5) -> Optional[dict[str, Any]]:
    """Blocking pop from the index job queue."""
    r = get_redis()
    result = await r.brpop(INDEX_QUEUE, timeout=timeout)
    if result:
        _, raw = result
        return json.loads(raw)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# MODEL HEALTH CACHE
# ─────────────────────────────────────────────────────────────────────────────

MODEL_HEALTH_TTL = 30


async def cache_model_health(model_name: str, available: bool, latency_ms: int) -> None:
    r = get_redis()
    await r.hset(
        f"model:health:{model_name}",
        mapping={"available": str(available), "latency_ms": str(latency_ms)},
    )
    await r.expire(f"model:health:{model_name}", MODEL_HEALTH_TTL)


async def get_model_health(model_name: str) -> Optional[dict[str, str]]:
    r = get_redis()
    return await r.hgetall(f"model:health:{model_name}") or None
