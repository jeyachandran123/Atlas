"""Conversation Memory (Objective 13) — current conversation only, by
design. A token-capped window of completed turns feeds the Prompt Builder
so follow-ups resolve, while answers stay grounded in freshly retrieved
knowledge (history informs phrasing, never substitutes for sources)."""
from __future__ import annotations

from app.document_platform.conversation.prompts import HistoryTurn
from app.document_platform.conversation.repository import ConversationRepository


class ConversationMemory:
    def __init__(self, repository: ConversationRepository, max_turns: int) -> None:
        self._repo = repository
        self._max_turns = max_turns

    async def window(self, conversation_id: str) -> list[HistoryTurn]:
        turns = await self._repo.completed_turns(conversation_id, self._max_turns)
        return [HistoryTurn(question=t.question, answer=t.answer or "") for t in turns]
