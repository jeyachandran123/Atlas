"""Voice agent API.

    GET  /chat/voice/config   → is voice on, and its session limits
    POST /chat/voice/session  → a short-lived token for one Gemini Live session
    POST /chat/voice/search   → run a web search the voice model asked for
    POST /chat/voice/turns    → save finished turns as normal chat messages

(No `from __future__ import annotations`: FastAPI must resolve real annotation objects.)
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_developer
from app.database import get_db
from app.db.models import Message, User
from app.db.repositories import ConversationRepository
from app.documents.service import get_document_service
from app.rate_limit import limiter
from app.redis_client import push_session_message
from app.voice.persona import MAX_DOCUMENT_CHARS, build_system_instruction
from app.voice.search import TOOL_DECLARATION, voice_search
from app.voice.service import (
    IDLE_TIMEOUT_SECONDS,
    MAX_SESSION_SECONDS,
    VoiceNotConfigured,
    VoiceProviderError,
    mint_live_token,
    voice_enabled,
)
from app.web_search.service import web_search_available

router = APIRouter(prefix="/chat/voice", tags=["Voice"])

DevDep = Annotated[User, Depends(require_developer)]
DbDep = Annotated[AsyncSession, Depends(get_db)]

_HISTORY_MESSAGES = 40
_VOICE_AGENT = "voice_agent"


class SessionIn(BaseModel):
    conversation_id: str | None = None
    # Set when reconnecting a dropped session, so it continues with its context.
    resume_handle: str | None = Field(default=None, max_length=4096)


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)


class TurnIn(BaseModel):
    # The client's id becomes the message's id, so a retried save can't duplicate it.
    id: UUID
    role: Literal["user", "assistant"]
    text: str = Field(max_length=50_000)


class TurnsIn(BaseModel):
    # Client-generated for a new chat, so a retried first save can't make two chats.
    conversation_id: UUID
    turns: list[TurnIn] = Field(max_length=50)


async def _owned_conversation(repo: ConversationRepository, conversation_id: str, user: User):
    conversation = await repo.get_by_id(conversation_id)
    if conversation is not None and conversation.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    return conversation


async def _context(db: AsyncSession, conversation_id: str) -> tuple[list[tuple[str, str]], str]:
    rows = (
        await db.execute(
            select(Message.role, Message.content)
            .where(Message.conversation_id == conversation_id)
            .where(Message.role.in_(("user", "assistant")))
            .order_by(Message.created_at.desc())
            .limit(_HISTORY_MESSAGES)
        )
    ).all()
    history = [(role, content) for role, content in reversed(rows)]
    try:
        documents = await get_document_service().build_document_block(
            conversation_id, max_chars=MAX_DOCUMENT_CHARS
        )
    except Exception as exc:  # noqa: BLE001 — a file that won't load must not stop the call
        logger.warning(f"Voice session continuing without attachments: {exc}")
        documents = ""
    return history, documents


@router.get("/config")
async def voice_config(current_user: DevDep) -> dict:
    return {
        "enabled": voice_enabled(),
        "max_session_seconds": MAX_SESSION_SECONDS,
        "idle_timeout_seconds": IDLE_TIMEOUT_SECONDS,
    }


@router.post("/session")
@limiter.limit("20/minute")
async def start_session(
    request: Request, body: SessionIn, current_user: DevDep, db: DbDep
) -> dict:
    history: list[tuple[str, str]] = []
    documents = ""
    if body.conversation_id:
        repo = ConversationRepository(db)
        if await _owned_conversation(repo, body.conversation_id, current_user) is None:
            raise HTTPException(404, "Conversation not found")
        history, documents = await _context(db, body.conversation_id)

    can_search = web_search_available()
    try:
        live = await mint_live_token(
            build_system_instruction(history, documents, can_search=can_search),
            body.resume_handle,
            tools=[TOOL_DECLARATION] if can_search else None,
        )
    except VoiceNotConfigured as exc:
        raise HTTPException(503, "voice_not_configured") from exc
    except VoiceProviderError as exc:
        # Gemini's own rate limit reaches the person as a rate limit, not a mystery.
        status = 429 if exc.upstream_status == 429 else 502
        raise HTTPException(status, "voice_provider_error") from exc

    return {
        "token": live.token,
        "model": live.model,
        "websocket_url": live.websocket_url,
        "expires_at": live.expires_at,
    }


@router.post("/search")
@limiter.limit("30/minute")
async def search(request: Request, body: SearchIn, current_user: DevDep) -> dict:
    """Run the web search the voice model asked for. Always a result, never an error."""
    return await voice_search(body.query)


@router.post("/turns")
@limiter.limit("120/minute")
async def save_turns(request: Request, body: TurnsIn, current_user: DevDep, db: DbDep) -> dict:
    conversation_id = str(body.conversation_id)
    turns = [t for t in body.turns if t.text.strip()]
    repo = ConversationRepository(db)
    conversation = await _owned_conversation(repo, conversation_id, current_user)
    if not turns:
        return {"conversation_id": conversation_id, "saved": 0}

    if conversation is None:
        conversation = await repo.create(id=conversation_id, user_id=current_user.id)
        first = next((t for t in turns if t.role == "user"), turns[0])
        await repo.auto_generate_title(conversation_id, first.text)

    ids = [str(t.id) for t in turns]
    taken = set(
        (await db.execute(select(Message.id).where(Message.id.in_(ids)))).scalars().all()
    )
    fresh = [t for t in turns if str(t.id) not in taken]
    for t in fresh:
        await repo.add_message(
            conversation_id,
            t.role,
            t.text.strip(),
            agent_used=_VOICE_AGENT,
            message_id=str(t.id),
        )
    await db.commit()

    try:
        for t in fresh:
            await push_session_message(current_user.id, conversation_id, t.role, t.text.strip())
    except Exception as exc:  # noqa: BLE001 — the saved chat is the record; memory is a cache
        logger.warning(f"Voice turns saved but not added to session memory: {exc}")

    return {"conversation_id": conversation_id, "saved": len(fresh)}
