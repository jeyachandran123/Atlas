"""Conversation Memory (Objective 13) — current conversation only, by
design. A token-capped window of completed turns feeds the Prompt Builder
so follow-ups resolve, while answers stay grounded in freshly retrieved
knowledge (history informs phrasing, never substitutes for sources)."""
from __future__ import annotations

import re

from app.document_platform.conversation.prompts import HistoryTurn
from app.document_platform.conversation.repository import ConversationRepository

_MARKER = re.compile(r"\s*\[S\d+\]")
"""Citation markers inside a remembered answer.

Source numbers are minted fresh for every turn - S5 is whichever block landed
fifth in this prompt. An answer quoted from an earlier turn carries that turn's
numbering, and the model copies markers it can see: asked a follow-up, it cited
[S5] into a prompt that had four sources, and the validator rejected the whole
answer as an invented citation. History is kept for continuity of phrasing, so
the markers come out and the sources below the question are the only ones the
model can reach for.
"""


_GIST_CHARS = 400
"""How much of a previous answer is worth remembering.

Enough to resolve "the other one" and "that total", and not enough to be worth
copying. A full previous answer in the window is not context, it is a template:
the model reads a finished, well-formatted reply directly above the question
and produces it again. Trimming is the cheap half of the fix; the prompt says
the rest out loud.
"""


def _gist(answer: str) -> str:
    if len(answer) <= _GIST_CHARS:
        return answer
    return answer[:_GIST_CHARS].rsplit(" ", 1)[0] + " …"


class ConversationMemory:
    def __init__(self, repository: ConversationRepository, max_turns: int) -> None:
        self._repo = repository
        self._max_turns = max_turns

    async def window(
        self, conversation_id: str,
        document_id: str | list[str] | None = None,
    ) -> list[HistoryTurn]:
        """History for the document scope this turn is asked under.

        The scope matters because the window becomes prompt text: an answer
        about a different document, sitting directly above the current
        question, is material the model will happily reuse.
        """
        if document_id is None:
            scope = None
        elif isinstance(document_id, list):
            scope = [d for d in document_id if d] or None
        else:
            scope = [document_id]
        turns = await self._repo.completed_turns(
            conversation_id, self._max_turns, scope,
        )
        return [
            HistoryTurn(
                question=t.question,
                answer=_gist(_MARKER.sub("", t.answer or "").strip()),
            )
            for t in turns
        ]

    async def chat_window(self, conversation_id: str) -> list[HistoryTurn]:
        """History for talk addressed to the assistant rather than the documents.

        Deliberately a different window from ``window``. A greeting has no
        document scope, so scoping it makes no sense; and the grounded window
        is full of long cited answers, which is what a model reaches for when
        it is asked something as contentless as "thanks!" and has nothing else
        in front of it.
        """
        turns = await self._repo.chat_turns(conversation_id, self._max_turns)
        return [
            HistoryTurn(question=t.question, answer=(t.answer or "").strip())
            for t in turns
        ]
