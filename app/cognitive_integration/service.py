"""Service seam — run one turn through the brain, safely (Option A).

Used by the existing chat route when ``COGNITIVE_BRAIN_ENABLED`` is on. It runs the
synchronous brain off the event loop (worker thread) and returns a ``TurnResult`` —
or ``None`` when the brain has nothing usable (e.g. the LLM is unreachable), so the
caller falls back to the existing pipeline and **chat never breaks by enabling the flag**.
"""

from __future__ import annotations

import asyncio
from typing import Any, Sequence

from .factory import get_pipeline
from .ports import Turn, TurnResult


async def cognitive_turn(
    message: str,
    *,
    conversation_id: str = "conv",
    user_id: str = "user",
    org_id: str = "org",
    history: Sequence[Any] | None = None,
    pipeline: Any | None = None,
) -> TurnResult | None:
    turn = Turn(message=message, conversation_id=str(conversation_id), user_id=str(user_id),
                org_id=str(org_id), history=tuple(history or ()))
    engine = pipeline or get_pipeline()
    try:
        result = await asyncio.to_thread(engine.handle, turn)
    except Exception:
        return None  # brain/LLM unavailable -> caller falls back to the existing orchestrator

    # Use the brain only when it actually reasoned to a conclusion, or when it
    # deliberately escalated a high-stakes/unsafe request (which must NOT be auto-answered).
    if result.conclusion is None and not result.escalated:
        return None
    return result
