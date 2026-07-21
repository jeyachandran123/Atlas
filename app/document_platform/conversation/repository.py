"""
All SQL for the Conversation layer — same rule as SemanticRepository:
no other module in this package issues queries. The single read into a
frozen Knowledge Platform table (document_chunks.page, for citations) is
centralized here, read-only, mirroring the sanctioned pattern
SemanticRepository documented in Phase 3.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ConversationEventRecord,
    DipConversation,
    DipConversationTurn,
    DocumentChunk,
)
from app.document_platform.conversation.events import ConversationEvent
from app.document_platform.conversation.metrics import TurnMetrics


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConversationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Conversations ────────────────────────────────────────────────────────

    async def create_conversation(
        self, user_id: str, org_id: str, title: str = "",
    ) -> DipConversation:
        conv = DipConversation(user_id=user_id, org_id=org_id, title=title[:300])
        self._db.add(conv)
        await self._db.flush()
        return conv

    async def get_conversation(
        self, conversation_id: str, user_id: str,
    ) -> Optional[DipConversation]:
        return (
            await self._db.execute(
                select(DipConversation).where(
                    DipConversation.id == conversation_id,
                    DipConversation.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    async def list_conversations(
        self, user_id: str, limit: int = 50,
    ) -> list[DipConversation]:
        rows = (
            await self._db.execute(
                select(DipConversation)
                .where(DipConversation.user_id == user_id)
                .order_by(DipConversation.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    # ── Turns ────────────────────────────────────────────────────────────────

    async def create_turn(
        self, conversation: DipConversation, question: str,
        document_id: str | None = None,
    ) -> DipConversationTurn:
        seq = (
            await self._db.execute(
                select(func.count()).select_from(DipConversationTurn)
                .where(DipConversationTurn.conversation_id == conversation.id)
            )
        ).scalar_one()
        turn = DipConversationTurn(
            conversation_id=conversation.id, question=question,
            seq=int(seq) + 1, document_id=document_id,
            correlation_id=conversation.correlation_id,
        )
        self._db.add(turn)
        await self._db.flush()
        return turn

    async def get_turn(self, turn_id: str) -> Optional[DipConversationTurn]:
        return (
            await self._db.execute(
                select(DipConversationTurn).where(DipConversationTurn.id == turn_id)
            )
        ).scalar_one_or_none()

    async def list_turns(self, conversation_id: str) -> list[DipConversationTurn]:
        rows = (
            await self._db.execute(
                select(DipConversationTurn)
                .where(DipConversationTurn.conversation_id == conversation_id)
                .order_by(DipConversationTurn.seq)
            )
        ).scalars().all()
        return list(rows)

    async def completed_turns(
        self, conversation_id: str, limit: int,
    ) -> list[DipConversationTurn]:
        """Most recent successfully-answered turns, oldest→newest, for memory."""
        rows = (
            await self._db.execute(
                select(DipConversationTurn)
                .where(
                    DipConversationTurn.conversation_id == conversation_id,
                    DipConversationTurn.status == "completed",
                    DipConversationTurn.answer.is_not(None),
                )
                .order_by(DipConversationTurn.seq.desc())
                .limit(limit)
            )
        ).scalars().all()
        return list(reversed(rows))

    async def finish_turn(
        self, turn: DipConversationTurn, *, status: str, answer: str | None,
        intent: str, grounded: bool, refusal_reason: str | None,
        citations_json: str | None, metrics: TurnMetrics,
        llm_provider: str, llm_model: str, error: str | None = None,
    ) -> None:
        turn.status = status
        turn.answer = answer
        turn.intent = intent
        turn.grounded = grounded
        turn.refusal_reason = refusal_reason
        turn.citations_json = citations_json
        turn.retrieval_ms = metrics.retrieval_ms
        turn.ranking_ms = metrics.ranking_ms
        turn.llm_ms = metrics.llm_ms
        turn.streaming_ms = metrics.streaming_ms
        turn.total_ms = metrics.total_ms
        turn.prompt_tokens = metrics.prompt_tokens
        turn.completion_tokens = metrics.completion_tokens
        turn.total_tokens = metrics.total_tokens
        turn.cost_estimate = metrics.cost_estimate
        turn.grounding_score = metrics.grounding_score
        turn.citation_count = metrics.citation_count
        turn.llm_provider = llm_provider
        turn.llm_model = llm_model
        turn.error = error
        turn.finished_at = _now()
        await self._db.flush()

    # ── Events ───────────────────────────────────────────────────────────────

    async def add_event(self, event: ConversationEvent) -> None:
        self._db.add(ConversationEventRecord(
            conversation_id=event.conversation_id,
            turn_id=event.turn_id,
            event_type=event.event_type.value,
            status=event.status,
            duration_ms=event.duration_ms,
            detail_json=json.dumps(event.detail) if event.detail else None,
            correlation_id=event.correlation_id,
        ))
        await self._db.flush()

    async def events_for_turn(self, turn_id: str) -> list[ConversationEventRecord]:
        rows = (
            await self._db.execute(
                select(ConversationEventRecord)
                .where(ConversationEventRecord.turn_id == turn_id)
                .order_by(ConversationEventRecord.created_at)
            )
        ).scalars().all()
        return list(rows)

    # ── Read-only citation enrichment (frozen table, page numbers only) ──────

    async def chunk_pages(self, chunk_ids: list[str]) -> dict[str, Optional[int]]:
        if not chunk_ids:
            return {}
        rows = (
            await self._db.execute(
                select(DocumentChunk.id, DocumentChunk.page)
                .where(DocumentChunk.id.in_(chunk_ids))
            )
        ).all()
        return {row[0]: row[1] for row in rows}
