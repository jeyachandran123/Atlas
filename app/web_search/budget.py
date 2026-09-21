"""How many searches today, and may we run another one.

You.com gives 100 searches a day free. A chat that quietly crosses that line
starts charging, so the count lives in Redis with a key that expires when the
day does, and the service asks before it searches.

Redis being unreachable must not disable search — this backend is explicitly
degrade-don't-die, and Redis is one of the optional pieces. So a counter that
cannot be read allows the search and says so in the log.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from loguru import logger

_PREFIX = "web_search:count:"


def _key(today: str | None = None) -> str:
    return _PREFIX + (today or date.today().isoformat())


def _seconds_until_midnight() -> int:
    now = datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((tomorrow - now).total_seconds()))


async def searches_used_today() -> int:
    """How many searches this deployment has spent today. 0 if unknown."""
    try:
        from app.redis_client import get_redis

        value = await get_redis().get(_key())
        return int(value or 0)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Web search budget unreadable: {e}")
        return 0


async def claim_search(cap: int) -> bool:
    """Take one search from today's budget.

    Increments first and compares after, so two turns arriving together cannot
    both see the last unit and both spend it.
    """
    if cap <= 0:
        return False
    try:
        from app.redis_client import get_redis

        redis = get_redis()
        key = _key()
        used = await redis.incr(key)
        if used == 1:
            await redis.expire(key, _seconds_until_midnight())
        if used > cap:
            logger.info(f"Web search budget spent for today ({used - 1}/{cap}); answering without it")
            return False
        return True
    except Exception as e:  # noqa: BLE001
        # Unmetered is better than unavailable: the cap protects a bill, and
        # Redis is an optional dependency of this backend.
        logger.warning(f"Web search budget not enforced ({e}); allowing the search")
        return True
