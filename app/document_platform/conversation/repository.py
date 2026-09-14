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

from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ConversationEventRecord,
    DipConversation,
    DipConversationTurn,
    Document,
    DocumentChunk,
    DocumentMetadataRow,
    KnowledgeObject,
)
from app.document_platform.conversation.context_builder import DocumentFacts
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

    async def document_facts(self, document_ids: list[str]) -> list[DocumentFacts]:
        """Whole-document totals for the documents a turn is scoped to.

        Read-only across the frozen Knowledge Platform tables, the same
        sanctioned pattern the document_chunks.page read already uses. The
        counts were computed once at processing time; nothing is derived from
        the excerpts, which is the entire point.
        """
        if not document_ids:
            return []
        rows = (
            await self._db.execute(
                select(
                    Document.id,
                    Document.original_filename,
                    KnowledgeObject.doc_type,
                    KnowledgeObject.title,
                    KnowledgeObject.chunk_count,
                    KnowledgeObject.word_count,
                    KnowledgeObject.table_count,
                    DocumentMetadataRow.page_count,
                    DocumentMetadataRow.sheet_count,
                )
                .select_from(Document)
                .outerjoin(KnowledgeObject, KnowledgeObject.document_id == Document.id)
                .outerjoin(DocumentMetadataRow, DocumentMetadataRow.document_id == Document.id)
                .where(Document.id.in_(document_ids))
            )
        ).all()

        table_rows = await self._table_row_counts(document_ids)
        return [
            DocumentFacts(
                document_id=r[0],
                filename=r[1] or "",
                doc_type=r[2] or "",
                title=r[3] or "",
                chunk_count=r[4] or 0,
                word_count=r[5] or 0,
                table_count=r[6] or 0,
                table_rows=table_rows.get(r[0], 0),
                page_count=r[7],
                sheet_count=r[8],
            )
            for r in rows
        ]

    async def _table_row_counts(self, document_ids: list[str]) -> dict[str, int]:
        """Real row totals, summed from the row_count each table chunk recorded.

        The chunker already counted the rows it put in every part, so the total
        is an aggregate rather than a scan of the content. The JSON accessor is
        PostgreSQL's; on any other engine this returns nothing and the facts
        block simply omits row totals rather than reporting a wrong one.
        """
        try:
            rows = (
                await self._db.execute(
                    sql_text(
                        "SELECT document_id, "
                        "SUM((meta_json::json->>'row_count')::int) AS row_total "
                        "FROM document_chunks "
                        "WHERE document_id = ANY(:ids) AND node_type = 'table' "
                        "AND meta_json IS NOT NULL "
                        "AND meta_json::json->>'row_count' IS NOT NULL "
                        "GROUP BY document_id"
                    ),
                    {"ids": list(document_ids)},
                )
            ).all()
        except Exception as e:  # noqa: BLE001 - a missing total beats a wrong one
            logger.debug(f"Table row totals unavailable on this engine: {e}")
            return {}
        return {r[0]: int(r[1] or 0) for r in rows}

    async def completed_turns(
        self, conversation_id: str, limit: int,
        document_ids: list[str] | None = None,
    ) -> list[DipConversationTurn]:
        """Most recent genuinely-answered turns, oldest-to-newest, for memory.

        Two filters here are load-bearing, and both were missing.

        ``grounded is True`` keeps refusals out. A refusal is stored exactly the
        way a good answer is - status "completed", with REFUSAL_SENTENCE as its
        answer - so the window fed the model its own "I don't have enough
        information in the knowledge base to answer that", which is the single
        most effective way to get that sentence back again. One refusal turned
        into a conversation that could no longer answer anything.

        ``document_ids`` keeps another document's answers out. Turn rows record
        the document scope they were asked under; the window ignored it, so
        changing the selected document left the previous document's questions
        and answers sitting in the prompt, and the model answered from them.
        Turns asked with no document scope stay in - they were asked over the
        whole workspace, so they are not some other document's answer.
        """
        conditions = [
            DipConversationTurn.conversation_id == conversation_id,
            DipConversationTurn.status == "completed",
            DipConversationTurn.grounded.is_(True),
            DipConversationTurn.answer.is_not(None),
        ]
        if document_ids:
            conditions.append(or_(
                DipConversationTurn.document_id.is_(None),
                DipConversationTurn.document_id.in_(document_ids),
            ))
        rows = (
            await self._db.execute(
                select(DipConversationTurn)
                .where(*conditions)
                .order_by(DipConversationTurn.seq.desc())
                .limit(limit)
            )
        ).scalars().all()
        return list(reversed(rows))

    async def chat_turns(
        self, conversation_id: str, limit: int,
    ) -> list[DipConversationTurn]:
        """Recent small-talk turns only, oldest-to-newest.

        General chat gets its own memory, separate from the document window
        above, because the two poison each other in opposite directions.
        Feeding document answers into a greeting is not hypothetical: asked
        "thanks!" with a document answer sitting at the end of the history,
        the model replied by repeating that document answer verbatim. And
        feeding chit-chat into a grounded prompt gives the model uncited text
        to copy, which the validator then throws the whole answer away for.

        They are told apart by the intent recorded on the row, which is the
        same decision that routed the turn in the first place.
        """
        rows = (
            await self._db.execute(
                select(DipConversationTurn)
                .where(
                    DipConversationTurn.conversation_id == conversation_id,
                    DipConversationTurn.status == "completed",
                    DipConversationTurn.intent == "conversational",
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
