"""
Chat API — the primary user-facing interface.

Endpoints:
  POST /api/v1/chat/message          → single request/response
  POST /api/v1/chat/stream           → server-sent events (SSE) streaming
  GET  /api/v1/chat/conversations    → list conversations
  GET  /api/v1/chat/conversations/{id}/messages → message history
  POST /api/v1/chat/conversations    → create new conversation
"""

from __future__ import annotations

import time
import uuid
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import AgentOrchestrator ,get_orchestrator_dep
from app.agents.state import initial_state
from app.auth import get_current_user, require_developer
from app.database import get_db
from app.db.models import User
from app.db.repositories import ConversationRepository, RepositoryRepo
from app.redis_client import get_session_messages, push_session_message
from app.shared.exceptions import ConversationNotFoundError, RepositoryNotFoundError
from app.shared.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationOut,
    MessageOut,
)

router = APIRouter(prefix="/chat", tags=["Chat"])


class CreateConversationRequest(BaseModel):
    repo_id: Optional[str] = None
    title: str = Field(default="New Conversation", max_length=255)


@router.post("/conversations", response_model=ConversationOut)
async def create_conversation(
    req: CreateConversationRequest,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> ConversationOut:
    """Create a new conversation, optionally linked to a repository."""
    conv_repo = ConversationRepository(db)
    repo_repo = RepositoryRepo(db)

    # Validate repo access if provided
    if req.repo_id:
        repo = await repo_repo.get_by_id(req.repo_id)
        if not repo:
            raise HTTPException(404, "Repository not found")
        has_access = await repo_repo.has_access(current_user.id, req.repo_id)
        if not has_access:
            raise HTTPException(403, "Access denied to repository")

    conv = await conv_repo.create(
        user_id=current_user.id,
        repo_id=req.repo_id,
        title=req.title,
    )

    return ConversationOut(
        id=conv.id,
        title=conv.title,
        repo_id=conv.repo_id,
        total_tokens=conv.total_tokens,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.get("/conversations", response_model=dict)
async def list_conversations(
    limit: int = 15,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List the current user's conversations with pagination."""
    conv_repo = ConversationRepository(db)
    convs, total = await conv_repo.list_for_user(current_user.id, limit=limit, offset=offset)
    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "repo_id": c.repo_id,
                "total_tokens": c.total_tokens,
                "is_pinned": c.is_pinned,
                "pin_order": c.pin_order,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
            }
            for c in convs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    """Get message history for a conversation."""
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get_by_id(conversation_id)

    if not conv:
        raise HTTPException(404, "Conversation not found")
    if conv.user_id != current_user.id:
        raise HTTPException(403, "Access denied")

    return [
        MessageOut(
            id=m.id,
            conversation_id=m.conversation_id,
            role=m.role,
            content=m.content,
            agent_used=m.agent_used,
            tokens_used=m.tokens_used,
            created_at=m.created_at,
        )
        for m in conv.messages
    ]


@router.post("/message", response_model=ChatResponse)
async def send_message(
    req: ChatRequest,   
    request: Request,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
    orchestrator: AgentOrchestrator = Depends(get_orchestrator_dep),  # injected via app state
) -> ChatResponse:
    """
    Send a message and receive a complete response.
    For streaming, use POST /chat/stream instead.
    """
    start = time.monotonic()
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    conv_repo = ConversationRepository(db)

    # Get or create conversation
    if req.conversation_id:
        conv = await conv_repo.get_by_id(req.conversation_id)
        if not conv or conv.user_id != current_user.id:
            raise HTTPException(404, "Conversation not found")
    else:
        conv = await conv_repo.create(
            user_id=current_user.id,
            repo_id=req.repo_id,
        )

    # Save user message
    user_msg = await conv_repo.add_message(
        conversation_id=conv.id,
        role="user",
        content=req.message,
    )

    # Load session memory from Redis
    session_messages = await get_session_messages(current_user.id, conv.id)

    # Build initial agent state
    state = initial_state(
        user_message=req.message,
        conversation_id=conv.id,
        user_id=current_user.id,
        org_id=current_user.org_id,
        request_id=request_id,
        repo_id=req.repo_id or conv.repo_id,
        agent_mode=req.agent_mode,
    )
    state["session_messages"] = session_messages

    # Run the agent
    orch = orchestrator
    result_state = await orch.run(state)

    final_response = result_state.get("final_response", "")
    tokens_used = result_state.get("tokens_used", 0)
    context_chunks = result_state.get("context_chunks_used", 0)
    latency_ms = int((time.monotonic() - start) * 1000)

    # Save assistant message
    assistant_msg = await conv_repo.add_message(
        conversation_id=conv.id,
        role="assistant",
        content=final_response,
        agent_used="coding_agent",
        tokens_used=tokens_used,
        latency_ms=latency_ms,
    )

    # Record agent execution
    await conv_repo.record_agent_execution(
        message_id=assistant_msg.id,
        agent_name="coding_agent",
        status="completed",
        output_tokens=tokens_used,
        duration_ms=latency_ms,
    )

    # Update session memory in Redis
    await push_session_message(current_user.id, conv.id, "user", req.message)
    await push_session_message(current_user.id, conv.id, "assistant", final_response)

    return ChatResponse(
        conversation_id=conv.id,
        message_id=assistant_msg.id,
        content=final_response,
        agent_used="coding_agent",
        tokens_used=tokens_used,
        latency_ms=latency_ms,
        context_chunks_used=context_chunks,
    )


@router.post("/stream")
async def stream_message(
    req: ChatRequest,
    request: Request,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Send a message and receive a streaming response via Server-Sent Events.

    Event format:
        data: {"type": "token", "content": "Hello"}
        data: {"type": "done", "conversation_id": "...", "tokens_used": 42}
        data: {"type": "error", "message": "..."}
    """
    import json

    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    conv_repo = ConversationRepository(db)

    # Get or create conversation BEFORE entering the generator
    # (generator runs outside the request context in some ASGI servers)
    if req.conversation_id:
        conv = await conv_repo.get_by_id(req.conversation_id)
        if not conv or conv.user_id != current_user.id:
            raise HTTPException(404, "Conversation not found")
    else:
        conv = await conv_repo.create(
            user_id=current_user.id,
            repo_id=req.repo_id,
        )
        await conv_repo.auto_generate_title(conv.id, req.message)

    await conv_repo.add_message(conv.id, "user", req.message)
    await db.commit()

    session_messages = await get_session_messages(current_user.id, conv.id)

    state = initial_state(
        user_message=req.message,
        conversation_id=conv.id,
        user_id=current_user.id,
        org_id=current_user.org_id,
        request_id=request_id,
        repo_id=req.repo_id or conv.repo_id,
        agent_mode=req.agent_mode,
    )
    state["session_messages"] = session_messages

    orch = request.app.state.orchestrator

    # Capture these for use inside the generator (avoid closure over mutable `conv`)
    conv_id = conv.id
    user_id = current_user.id

    async def event_generator() -> AsyncGenerator[str, None]:
        full_response = ""
        start = time.monotonic()
        try:
            async for chunk in orch.stream(state):
                if not chunk:
                    continue
                full_response += chunk
                # Each SSE frame must end with double newline to be flushed immediately
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

            tokens_used = len(full_response) // 4
            latency_ms = int((time.monotonic() - start) * 1000)

            # Persist assistant message after streaming completes
            assistant_msg = await conv_repo.add_message(
                conversation_id=conv_id,
                role="assistant",
                content=full_response,
                agent_used="coding_agent",
                tokens_used=tokens_used,
                latency_ms=latency_ms,
            )
            await db.commit()

            await push_session_message(user_id, conv_id, "user", req.message)
            await push_session_message(user_id, conv_id, "assistant", full_response)

            yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id, 'message_id': assistant_msg.id, 'tokens_used': tokens_used, 'latency_ms': latency_ms})}\n\n"

        except Exception as e:
            from loguru import logger
            logger.exception(f"Stream error: {e}")
            try:
                await db.rollback()
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
            "Connection": "keep-alive",
        },
    )



class UpdateConversationRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


@router.patch("/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    req: UpdateConversationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update conversation title."""
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get_by_id(conversation_id)
    
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if conv.user_id != current_user.id:
        raise HTTPException(403, "Access denied")
    
    await conv_repo.update_title(conversation_id, req.title)
    await db.commit()
    
    return {"id": conversation_id, "title": req.title}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a conversation and all its messages."""
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get_by_id(conversation_id)
    
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if conv.user_id != current_user.id:
        raise HTTPException(403, "Access denied")
    
    await conv_repo.delete_conversation(conversation_id)
    await db.commit()
    
    return {"id": conversation_id, "deleted": True}


@router.post("/conversations/{conversation_id}/pin")
async def pin_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Pin a conversation to the top."""
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get_by_id(conversation_id)
    
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if conv.user_id != current_user.id:
        raise HTTPException(403, "Access denied")
    
    await conv_repo.pin_conversation(conversation_id, current_user.id)
    await db.commit()
    
    return {"id": conversation_id, "is_pinned": True}


@router.delete("/conversations/{conversation_id}/pin")
async def unpin_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Unpin a conversation."""
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get_by_id(conversation_id)
    
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if conv.user_id != current_user.id:
        raise HTTPException(403, "Access denied")
    
    await conv_repo.unpin_conversation(conversation_id)
    await db.commit()
    
    return {"id": conversation_id, "is_pinned": False}
