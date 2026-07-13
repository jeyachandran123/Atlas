"""
Memory Port.

Adapter that wraps the existing MemoryManager behind the AbstractMemoryPort interface.
The intelligence engine depends on this interface — not on MemoryManager directly.
This means long-term memory, vector memory, or any other memory backend
can be swapped without changing the engine.
"""

from __future__ import annotations

from typing import Optional

from app.intelligence.interfaces import AbstractMemoryPort


class MemoryPort(AbstractMemoryPort):
    """Adapts MemoryManager to the AbstractMemoryPort interface."""

    def __init__(self, manager=None) -> None:
        self._manager = manager  # lazy — resolved on first use

    def _get_manager(self):
        if self._manager is None:
            from app.memory.manager import get_memory_manager
            self._manager = get_memory_manager()
        return self._manager

    async def get_session(
        self,
        user_id: str,
        conversation_id: str,
        limit: int = 10,
    ) -> list[dict]:
        return await self._get_manager().get_messages(user_id, conversation_id, limit)

    async def get_long_term(
        self,
        user_id: str,
        query: str,
        limit: int = 3,
    ) -> str:
        try:
            return await self._get_manager().long_term.get_formatted_context(
                user_id=user_id,
                query=query,
                limit=limit,
            )
        except Exception:
            return ""

    async def save_turn(
        self,
        user_id: str,
        conversation_id: str,
        user_message: str,
        assistant_response: str,
        agent_mode: str,
    ) -> None:
        mgr = self._get_manager()
        await mgr.add_message(user_id, conversation_id, "user", user_message, agent_mode)
        if assistant_response:
            await mgr.add_message(
                user_id, conversation_id, "assistant", assistant_response, agent_mode
            )


# ── Singleton ─────────────────────────────────────────────────────────────────

_port: MemoryPort | None = None


def get_memory_port() -> MemoryPort:
    global _port
    if _port is None:
        _port = MemoryPort()
    return _port
