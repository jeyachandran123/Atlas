"""Glue between chat paths and plugins. Like app.skills.chat, every function here
is fail-safe: a plugin problem is logged and the turn goes ahead exactly as it
would without plugins. With ENABLE_PLUGINS off nothing touches the database."""

from __future__ import annotations

import json
from collections.abc import Sequence

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.plugins.service import PluginContext, PluginService


def plugins_enabled() -> bool:
    return bool(get_settings().enable_plugins)


async def gather_plugin_context(db: AsyncSession, *, user_id: str, message: str) -> PluginContext:
    """Fetch what the message asks of the user's connected accounts (usually nothing)."""
    if not plugins_enabled():
        return PluginContext()
    try:
        return await PluginService(db).run_for_message(user_id, message)
    except Exception as e:  # noqa: BLE001 - plugins must never break a turn
        logger.warning(f"Plugin lookup failed (continuing without plugins): {e}")
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001, S110
            pass
        return PluginContext()


def prompt_section(ctx: PluginContext) -> str:
    return ctx.render(get_settings().plugin_context_chars)


def capabilities_sse(ctx: PluginContext) -> str | None:
    """Early `capabilities` frame naming the plugins about to be used."""
    if not ctx.refs:
        return None
    return f"data: {json.dumps({'type': 'capabilities', 'plugins': ctx.refs})}\n\n"


def done_extras(ctx: PluginContext) -> dict:
    return {"plugins": ctx.refs} if ctx.refs else {}


async def record_plugin_usage(
    db: AsyncSession, refs: Sequence[dict[str, str]], *, message_id: str | None = None
) -> None:
    """Persist usage after the reply is saved, in its own commit."""
    if not refs or not plugins_enabled():
        return
    try:
        from app.skills.repository import SkillRepository

        SkillRepository(db).add_capabilities(
            [{"slug": f"plugin:{r['slug']}", "name": r["name"]} for r in refs],
            "plugin_tool",
            message_id=message_id,
        )
        await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Recording plugin usage failed: {e}")
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001, S110
            pass
