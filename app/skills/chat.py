"""
Glue between chat paths and skills. Every function here is fail-safe: a
skills problem logs a warning and the turn proceeds exactly as it would
without skills. With ENABLE_SKILLS off nothing here touches the database.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.skills.router import SkillSelection


def skills_enabled() -> bool:
    return bool(get_settings().enable_skills)


async def select_skills(
    db: AsyncSession,
    *,
    user_id: str,
    org_id: str,
    message: str,
    agent_mode: str = "auto",
    history: list[dict] | None = None,
    picked: list[str] | None = None,
) -> SkillSelection:
    if not skills_enabled():
        return SkillSelection(message=message)
    try:
        from app.skills.service import SkillService

        # A savepoint, because catching the exception is not enough: a failed
        # query aborts the session's whole transaction, and the turn's next
        # query then fails with "current transaction is aborted". With the
        # skills tables missing (migration 0021 not applied) every chat turn
        # died that way. Rolling back to the savepoint keeps the session usable.
        async with db.begin_nested():
            return await SkillService(db).select(
                user_id, org_id, message, agent_mode, history, picked=picked
            )
    except Exception as e:  # noqa: BLE001 — skills must never break a turn
        logger.warning(f"Skill selection failed (continuing without skills): {e}")
        return SkillSelection(message=message)


def capabilities_sse(selection: SkillSelection) -> str | None:
    """Early `capabilities` frame for the chat SSE stream (None = nothing to send)."""
    if not selection.skills:
        return None
    return f"data: {json.dumps({'type': 'capabilities', 'skills': selection.refs})}\n\n"


def done_extras(selection: SkillSelection) -> dict:
    """Additive fields for the `done` event — empty when no skill was used."""
    return {"skills": selection.refs} if selection.skills else {}


async def record_skill_usage(
    db: AsyncSession,
    refs: Sequence[dict[str, str]],
    *,
    message_id: str | None = None,
    turn_id: str | None = None,
) -> None:
    """Persist usage in its own commit AFTER the reply was saved, so a failure
    here can never roll back the assistant message."""
    if not refs or not skills_enabled():
        return
    try:
        from app.skills.repository import SkillRepository

        SkillRepository(db).add_capabilities(refs, "skill", message_id=message_id, turn_id=turn_id)
        await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Recording skill usage failed: {e}")
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001, S110
            pass
