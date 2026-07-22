"""
Conversational Knowledge Intelligence endpoints (Phase 4).

Deliberately its own router — the legacy /chat surface is frozen. Auth stays
here (routers authenticate); everything else is the ConversationGateway's
job. Streaming uses the same SSE pattern as the legacy chat router.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.db.models import User
from app.document_platform.conversation.gateway import ConversationGateway
from app.document_platform.conversation.repository import ConversationRepository
from app.document_platform.conversation.schemas import (
    AskIn,
    ConversationCreateIn,
    ConversationEventOut,
    ConversationOut,
    TurnHistoryOut,
    TurnOut,
)

router = APIRouter(prefix="/conversations", tags=["Conversations"])


async def _owned_conversation(repo: ConversationRepository, conversation_id: str, user: User):
    conv = await repo.get_conversation(conversation_id, user.id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.post("", response_model=ConversationOut, status_code=201)
async def create_conversation(
    body: ConversationCreateIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    gateway = ConversationGateway(db)
    conv = await gateway.start_conversation(current_user.id, current_user.org_id, body.title)
    return ConversationOut(
        id=conv.id, title=conv.title, status=conv.status,
        correlation_id=conv.correlation_id, created_at=conv.created_at,
    )


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await ConversationRepository(db).list_conversations(current_user.id)
    return [
        ConversationOut(
            id=c.id, title=c.title, status=c.status,
            correlation_id=c.correlation_id, created_at=c.created_at,
        )
        for c in rows
    ]


@router.post("/{conversation_id}/ask", response_model=TurnOut)
async def ask(
    conversation_id: str,
    body: AskIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    gateway = ConversationGateway(db)
    conv = await _owned_conversation(ConversationRepository(db), conversation_id, current_user)
    result = await gateway.ask(conv, body.question, body.document_ids or body.document_id)
    return TurnOut(**result.__dict__)


@router.post("/{conversation_id}/ask/stream")
async def ask_stream(
    conversation_id: str,
    body: AskIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    gateway = ConversationGateway(db)
    conv = await _owned_conversation(ConversationRepository(db), conversation_id, current_user)
    return StreamingResponse(
        gateway.ask_stream(conv, body.question, body.document_ids or body.document_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{conversation_id}/turns", response_model=list[TurnHistoryOut])
async def list_turns(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = ConversationRepository(db)
    await _owned_conversation(repo, conversation_id, current_user)
    turns = await repo.list_turns(conversation_id)
    return [
        TurnHistoryOut(
            id=t.id, seq=t.seq, question=t.question, answer=t.answer,
            intent=t.intent, status=t.status, grounded=t.grounded,
            grounding_score=t.grounding_score, citation_count=t.citation_count,
            citations_json=t.citations_json,
            total_ms=t.total_ms, total_tokens=t.total_tokens, created_at=t.created_at,
        )
        for t in turns
    ]


@router.get("/{conversation_id}/turns/{turn_id}/events",
            response_model=list[ConversationEventOut])
async def turn_events(
    conversation_id: str,
    turn_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = ConversationRepository(db)
    await _owned_conversation(repo, conversation_id, current_user)
    turn = await repo.get_turn(turn_id)
    if turn is None or turn.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="Turn not found")
    events = await repo.events_for_turn(turn_id)
    return [
        ConversationEventOut(
            id=e.id, event_type=e.event_type, status=e.status,
            duration_ms=e.duration_ms, detail_json=e.detail_json,
            created_at=e.created_at,
        )
        for e in events
    ]
