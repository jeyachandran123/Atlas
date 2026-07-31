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

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import AgentOrchestrator, get_orchestrator_dep
from app.agents.state import initial_state
from app.auth import get_current_user, require_developer
from app.config import get_settings as _get_settings

cfg = _get_settings()
from app.database import get_db
from app.db.models import User, Message, AgentExecution
from app.db.repositories import ConversationRepository, RepositoryRepo
from app.redis_client import get_session_messages, push_session_message
from app.shared.exceptions import ConversationNotFoundError, RepositoryNotFoundError
from app.shared.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationOut,
    MessageDocumentOut,
    MessageImageOut,
    MessageOut,
)
from app.vision.service import get_vision_service
from app.vision.image_storage import ALLOWED_MIME_TYPES, MAX_IMAGE_SIZE, get_image_storage
from app.vision.schemas import ImageAttachment
from app.db.models import MessageImage as MessageImageModel
from app.db.models import MessageDocument as MessageDocumentModel
from app.documents.service import get_document_service
from app.documents.schemas import DocumentAttachment
from app.documents.extractor import DocumentExtractionError, is_supported_document
from app.documents.storage import DocumentStorageError, get_document_storage

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


def _build_image_url(img: MessageImageModel) -> str:
    """Build the serving URL for a message image (relative to API prefix)."""
    return f"/chat/images/{img.id}"


def _build_document_url(doc: MessageDocumentModel) -> str:
    """Build the serving URL for a message document (relative to API prefix)."""
    return f"/chat/documents/{doc.id}"


def _message_to_out(m: Message) -> MessageOut:
    """Convert a Message ORM model to MessageOut with images and documents."""
    images = []
    if hasattr(m, 'images') and m.images:
        images = [
            MessageImageOut(
                id=img.id,
                filename=img.filename,
                mime_type=img.mime_type,
                size_bytes=img.size_bytes,
                width=img.width,
                height=img.height,
                url=_build_image_url(img),
            )
            for img in m.images
        ]
    documents = []
    if hasattr(m, 'documents') and m.documents:
        documents = [
            MessageDocumentOut(
                id=doc.id,
                filename=doc.filename,
                mime_type=doc.mime_type,
                size_bytes=doc.size_bytes,
                page_count=doc.page_count,
                char_count=doc.char_count,
                url=_build_document_url(doc),
            )
            for doc in m.documents
        ]
    return MessageOut(
        id=m.id,
        conversation_id=m.conversation_id,
        role=m.role,
        content=m.content,
        agent_used=m.agent_used,
        tokens_used=m.tokens_used,
        images=images,
        documents=documents,
        created_at=m.created_at,
    )


async def _ensure_document_context(db: AsyncSession, conversation_id: str) -> bool:
    """
    Check whether this conversation has uploaded documents.

    Fast path: Redis/memory context. Fallback: rebuild the context from
    message_documents rows in the DB (Redis TTL is 24h; DB is durable).
    """
    doc_service = get_document_service()
    if await doc_service.has_documents(conversation_id):
        return True

    from sqlalchemy import select as sql_select
    result = await db.execute(
        sql_select(MessageDocumentModel)
        .where(MessageDocumentModel.conversation_id == conversation_id)
        .order_by(MessageDocumentModel.created_at)
    )
    rows = list(result.scalars().all())
    if not rows:
        return False

    attachments = [
        DocumentAttachment(
            id=r.id,
            conversation_id=r.conversation_id,
            message_id=r.message_id,
            filename=r.filename,
            mime_type=r.mime_type,
            size_bytes=r.size_bytes,
            storage_path=r.storage_path,
            text_path=r.text_path,
            doc_hash=r.doc_hash,
            page_count=r.page_count,
            char_count=r.char_count,
            created_at=r.created_at,
        )
        for r in rows
    ]
    await doc_service.rehydrate(conversation_id, attachments)
    return True


@router.get("/images/{image_id}")
async def serve_image(
    image_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve a stored image by ID (from local disk or cloud storage)."""
    from fastapi.responses import Response
    from sqlalchemy import select as sql_select

    result = await db.execute(
        sql_select(MessageImageModel).where(MessageImageModel.id == image_id)
    )
    img = result.scalar_one_or_none()
    if not img:
        raise HTTPException(404, "Image not found")

    # Verify user owns the conversation
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get_by_id(img.conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(403, "Access denied")

    from app.vision.image_storage import ImageStorageError
    try:
        data = await get_image_storage().get_bytes_by_key(img.storage_path)
    except ImageStorageError:
        raise HTTPException(404, "Image file not found")

    return Response(content=data, media_type=img.mime_type)


@router.get("/documents/{document_id}")
async def serve_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve (download) a stored document by ID (from local disk or cloud storage)."""
    from fastapi.responses import Response
    from sqlalchemy import select as sql_select

    result = await db.execute(
        sql_select(MessageDocumentModel).where(MessageDocumentModel.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "Document not found")

    # Verify user owns the conversation
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get_by_id(doc.conversation_id)
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(403, "Access denied")

    try:
        data = await get_document_storage().get_bytes(doc.storage_path)
    except DocumentStorageError:
        raise HTTPException(404, "Document file not found")

    return Response(
        content=data,
        media_type=doc.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'},
    )


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

    return [_message_to_out(m) for m in conv.messages]


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
    clarification_asked = result_state.get("should_clarify", False)
    rewritten_query_used = bool(
        result_state.get("rewritten_query", "") != req.message
    )

    # Build trace dict for debug mode
    trace_data = None
    if cfg.app_debug:
        intel_trace = result_state.get("intelligence_trace")
        if intel_trace:
            try:
                from dataclasses import asdict
                trace_data = asdict(intel_trace)
            except Exception:
                trace_data = {"request_id": getattr(intel_trace, "request_id", "")}

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
        trace=trace_data,
        clarification_asked=clarification_asked,
        rewritten_query_used=rewritten_query_used,
    )


async def _stream_document_response(
    request: Request,
    db: AsyncSession,
    conv_repo: ConversationRepository,
    conv_id: str,
    user_id: str,
    org_id: str,
    message: str,
    repo_id: Optional[str],
    agent_mode: str,
    request_id: str,
    session_messages: list[dict],
) -> StreamingResponse:
    """
    Stream a document-grounded answer via SSE.

    Mirrors the vision pipeline: run the intelligence engine for the base
    system prompt, then stream the LLM answer with extracted document text
    injected into the prompt. Persists the assistant message afterwards.
    """
    import json

    doc_service = get_document_service()

    # Reuse the intelligence engine for the base system prompt (non-blocking)
    system_prompt = ""
    try:
        state = initial_state(
            user_message=message,
            conversation_id=conv_id,
            user_id=user_id,
            org_id=org_id,
            request_id=request_id,
            repo_id=repo_id,
            agent_mode=agent_mode,
        )
        state["session_messages"] = session_messages
        from app.intelligence.engine import get_engine
        engine_result = await get_engine().prepare(state)
        if not engine_result.is_blocked:
            system_prompt = engine_result.system_prompt
    except Exception as e:
        from loguru import logger
        logger.warning(f"Intelligence engine failed for documents (non-blocking): {e}")

    async def document_event_generator() -> AsyncGenerator[str, None]:
        full_response = ""
        start = time.monotonic()
        try:
            async for chunk in doc_service.chat_stream(
                message=message,
                conversation_id=conv_id,
                system_prompt=system_prompt,
                session_messages=session_messages,
                agent_mode=agent_mode,
            ):
                if not chunk:
                    continue
                full_response += chunk
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

            tokens_used = len(full_response) // 4
            latency_ms = int((time.monotonic() - start) * 1000)

            assistant_msg = await conv_repo.add_message(
                conversation_id=conv_id, role="assistant",
                content=full_response, agent_used="document_agent",
                tokens_used=tokens_used, latency_ms=latency_ms,
            )
            await db.commit()

            await push_session_message(user_id, conv_id, "user", message)
            await push_session_message(user_id, conv_id, "assistant", full_response)

            yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id, 'message_id': assistant_msg.id, 'tokens_used': tokens_used, 'latency_ms': latency_ms})}\n\n"

        except Exception as e:
            from loguru import logger
            logger.exception(f"Document stream error: {e}")
            try:
                await db.rollback()
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'error', 'message': str(e), 'conversation_id': conv_id})}\n\n"

    return StreamingResponse(
        document_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
            "Connection": "keep-alive",
        },
    )


def _cognitive_chunks(text: str, size: int = 40):
    for i in range(0, len(text), size):
        yield text[i:i + size]


def _stream_cognitive_response(*, db, conv_repo, conv_id, user_id, message, request_id, delib) -> StreamingResponse:
    """Stream a brain-governed reply token-by-token (TRUE streaming), then persist it.

    The Executive safety gate (in ``delib``) already decided authorize-vs-escalate. If
    escalated, we stream the short hold message; otherwise we stream the answer straight
    from Ollama's ``chat_stream`` so tokens appear progressively (not all at once). The
    'done' frame carries brain metadata additively — the existing frontend is unchanged.
    """
    import json
    import time

    async def event_generator() -> AsyncGenerator[str, None]:
        start = time.monotonic()
        full = ""
        try:
            if delib.escalated:
                for chunk in _cognitive_chunks(delib.hold_message or "Held for review."):
                    full += chunk
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
            else:
                from app.ollama_client import get_ollama_client

                client = get_ollama_client()
                async for chunk in client.chat_stream(
                    delib.user_prompt, system_prompt=delib.system_prompt, model=delib.model
                ):
                    if not chunk:
                        continue
                    full += chunk
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

            tokens_used = max(1, len(full) // 4)
            latency_ms = int((time.monotonic() - start) * 1000)
            assistant_msg = await conv_repo.add_message(
                conversation_id=conv_id, role="assistant", content=full,
                agent_used="cognitive_os", tokens_used=tokens_used, latency_ms=latency_ms,
            )
            await db.commit()
            await push_session_message(user_id, conv_id, "user", message)
            await push_session_message(user_id, conv_id, "assistant", full)
            done = {
                "type": "done", "conversation_id": conv_id, "message_id": assistant_msg.id,
                "tokens_used": tokens_used, "latency_ms": latency_ms,
                # Brain metadata (additive; classic clients ignore unknown fields).
                "brain": True, "decision": delib.decision, "authorized": delib.authorized,
                "escalated": delib.escalated, "confidence": delib.confidence, "intent": delib.intent,
            }
            yield f"data: {json.dumps(done)}\n\n"
        except Exception as e:  # noqa: BLE001
            from loguru import logger
            logger.exception(f"Cognitive stream error: {e}")
            try:
                await db.rollback()
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'error', 'message': str(e), 'conversation_id': conv_id})}\n\n"

    return StreamingResponse(
        event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
                 "X-Request-ID": request_id, "Connection": "keep-alive"},
    )


@router.post("/stream")
async def stream_message(
    req: ChatRequest,
    request: Request,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:  # noqa: C901 — complex but cohesive
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

    # ── Document follow-up routing ────────────────────────────────────────────
    # If this conversation has uploaded documents (PDF/Word/text), answer with
    # the document pipeline so questions about the files keep working across
    # turns and page refreshes.
    if await _ensure_document_context(db, conv.id):
        return await _stream_document_response(
            request=request,
            db=db,
            conv_repo=conv_repo,
            conv_id=conv.id,
            user_id=current_user.id,
            org_id=current_user.org_id,
            message=req.message,
            repo_id=req.repo_id or conv.repo_id,
            agent_mode=req.agent_mode,
            request_id=request_id,
            session_messages=session_messages,
        )

    # ── Cognitive Operating System routing (flag-gated, brain-first with fallback) ──
    # When COGNITIVE_BRAIN_ENABLED is on, route the turn through the Cognitive OS. If the
    # brain has nothing usable (e.g. the LLM is unreachable) it returns None and we fall
    # through to the existing orchestrator — enabling the flag can never break chat.
    from app.cognitive_integration import cognitive_brain_enabled

    if cognitive_brain_enabled():
        from app.cognitive_integration.service import deliberate_turn

        delib = await deliberate_turn(
            req.message, conversation_id=conv.id, user_id=current_user.id,
            org_id=current_user.org_id, history=session_messages,
        )
        if delib is not None:
            return _stream_cognitive_response(
                db=db, conv_repo=conv_repo, conv_id=conv.id, user_id=current_user.id,
                message=req.message, request_id=request_id, delib=delib,
            )

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
            yield f"data: {json.dumps({'type': 'error', 'message': str(e), 'conversation_id': conv_id})}\n\n"

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


# ── Vision-enabled streaming endpoint (multipart/form-data) ──────────────────


@router.post("/stream/vision")
async def stream_vision_message(
    request: Request,
    message: str = Form(...),
    conversation_id: Optional[str] = Form(None),
    repo_id: Optional[str] = Form(None),
    agent_mode: str = Form("auto"),
    images: list[UploadFile] = File(default=[]),
    documents: list[UploadFile] = File(default=[]),
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Vision/document-enabled streaming chat via multipart/form-data.

    Accepts images and/or documents (PDF, Word, text) alongside text.
    - Images present → vision model (with document context appended if any)
    - Documents only → document Q&A pipeline (text LLM + extracted text)
    - Neither, but conversation has prior images/documents → follow-up routing
    - Otherwise → standard text pipeline
    """
    import json

    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    conv_repo = ConversationRepository(db)
    vision_service = get_vision_service()
    doc_service = get_document_service()

    # Validate and read uploaded images
    image_bytes_list: list[bytes] = []
    for img in images:
        if img.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(400, f"Unsupported image type: {img.content_type}")
        data = await img.read()
        if len(data) > MAX_IMAGE_SIZE:
            raise HTTPException(400, f"Image too large: {img.filename}")
        image_bytes_list.append(data)

    # Validate and read uploaded documents
    max_doc_bytes = cfg.document_max_file_size_mb * 1024 * 1024
    if len(documents) > cfg.document_max_per_message:
        raise HTTPException(
            400, f"Too many documents: max {cfg.document_max_per_message} per message"
        )
    document_uploads: list[tuple[str, str, bytes]] = []  # (filename, mime, bytes)
    for doc in documents:
        filename = doc.filename or "document.txt"
        if not is_supported_document(filename):
            raise HTTPException(
                400,
                f"Unsupported document type: {filename}. "
                "Supported: PDF, Word (.docx), and text files.",
            )
        data = await doc.read()
        if len(data) > max_doc_bytes:
            raise HTTPException(
                400,
                f"Document too large: {filename} (max {cfg.document_max_file_size_mb}MB)",
            )
        document_uploads.append(
            (filename, doc.content_type or "application/octet-stream", data)
        )

    # Get or create conversation
    if conversation_id:
        conv = await conv_repo.get_by_id(conversation_id)
        if not conv or conv.user_id != current_user.id:
            raise HTTPException(404, "Conversation not found")
    else:
        conv = await conv_repo.create(user_id=current_user.id, repo_id=repo_id)
        await conv_repo.auto_generate_title(conv.id, message)

    # Store uploaded images in vision context AND persist metadata to DB
    stored_attachments: list[ImageAttachment] = []
    for i, (img, data) in enumerate(zip(images, image_bytes_list)):
        att = await vision_service.process_upload(
            file_bytes=data,
            filename=img.filename or f"image_{i}.png",
            mime_type=img.content_type or "image/png",
            conversation_id=conv.id,
        )
        stored_attachments.append(att)

    # Extract + store uploaded documents (before the user message is created,
    # so extraction failures return a clean 400 with no stray message)
    stored_docs: list[DocumentAttachment] = []
    for filename, mime_type, data in document_uploads:
        try:
            doc_att = await doc_service.process_upload(
                file_bytes=data,
                filename=filename,
                mime_type=mime_type,
                conversation_id=conv.id,
            )
        except (DocumentExtractionError, DocumentStorageError) as e:
            raise HTTPException(400, str(e))
        stored_docs.append(doc_att)

    user_msg = await conv_repo.add_message(conv.id, "user", message)
    await db.commit()

    # Persist image metadata linked to the user message
    for att in stored_attachments:
        db_img = MessageImageModel(
            id=att.id,
            message_id=user_msg.id,
            conversation_id=conv.id,
            filename=att.filename,
            mime_type=att.mime_type,
            size_bytes=att.size_bytes,
            storage_path=att.storage_path,
            image_hash=att.image_hash,
            width=att.width,
            height=att.height,
        )
        db.add(db_img)
    if stored_attachments:
        await db.commit()

    # Persist document metadata linked to the user message
    for doc_att in stored_docs:
        db_doc = MessageDocumentModel(
            id=doc_att.id,
            message_id=user_msg.id,
            conversation_id=conv.id,
            filename=doc_att.filename,
            mime_type=doc_att.mime_type,
            size_bytes=doc_att.size_bytes,
            storage_path=doc_att.storage_path,
            text_path=doc_att.text_path,
            doc_hash=doc_att.doc_hash,
            page_count=doc_att.page_count,
            char_count=doc_att.char_count,
        )
        db.add(db_doc)
    if stored_docs:
        await db.commit()

    # Determine routing: vision, documents, or text
    has_new_images = len(image_bytes_list) > 0
    use_vision = vision_service.should_use_vision(has_new_images, conv.id)
    has_docs = bool(stored_docs) or await _ensure_document_context(db, conv.id)

    if not use_vision:
        # Documents present (new or from earlier turns) → document Q&A pipeline
        if has_docs:
            session_messages = await get_session_messages(current_user.id, conv.id)
            return await _stream_document_response(
                request=request,
                db=db,
                conv_repo=conv_repo,
                conv_id=conv.id,
                user_id=current_user.id,
                org_id=current_user.org_id,
                message=message,
                repo_id=repo_id or conv.repo_id,
                agent_mode=agent_mode,
                request_id=request_id,
                session_messages=session_messages,
            )

        # No images at all — delegate to standard text pipeline
        # Build a ChatRequest and reuse the standard stream logic
        session_messages = await get_session_messages(current_user.id, conv.id)
        state = initial_state(
            user_message=message,
            conversation_id=conv.id,
            user_id=current_user.id,
            org_id=current_user.org_id,
            request_id=request_id,
            repo_id=repo_id or conv.repo_id,
            agent_mode=agent_mode,
        )
        state["session_messages"] = session_messages
        orch = request.app.state.orchestrator

        conv_id = conv.id
        user_id = current_user.id

        async def text_event_generator() -> AsyncGenerator[str, None]:
            full_response = ""
            start = time.monotonic()
            try:
                async for chunk in orch.stream(state):
                    if not chunk:
                        continue
                    full_response += chunk
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

                tokens_used = len(full_response) // 4
                latency_ms = int((time.monotonic() - start) * 1000)
                assistant_msg = await conv_repo.add_message(
                    conversation_id=conv_id, role="assistant",
                    content=full_response, agent_used="coding_agent",
                    tokens_used=tokens_used, latency_ms=latency_ms,
                )
                await db.commit()
                await push_session_message(user_id, conv_id, "user", message)
                await push_session_message(user_id, conv_id, "assistant", full_response)
                yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id, 'message_id': assistant_msg.id, 'tokens_used': tokens_used, 'latency_ms': latency_ms})}\n\n"
            except Exception as e:
                from loguru import logger
                logger.exception(f"Vision text fallback stream error: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': str(e), 'conversation_id': conv_id})}\n\n"

        return StreamingResponse(
            text_event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    # ── Vision pipeline ───────────────────────────────────────────────────────
    session_messages = await get_session_messages(current_user.id, conv.id)

    # Run intelligence engine for system prompt (reuse existing pipeline)
    system_prompt = ""
    try:
        state = initial_state(
            user_message=message,
            conversation_id=conv.id,
            user_id=current_user.id,
            org_id=current_user.org_id,
            request_id=request_id,
            repo_id=repo_id or conv.repo_id,
            agent_mode=agent_mode,
        )
        state["session_messages"] = session_messages
        from app.intelligence.engine import get_engine
        engine_result = await get_engine().prepare(state)
        if not engine_result.is_blocked:
            system_prompt = engine_result.system_prompt
    except Exception as e:
        from loguru import logger
        logger.warning(f"Intelligence engine failed for vision (non-blocking): {e}")

    # Mixed upload (images + documents): give the vision model the extracted
    # document text too, so questions can span both.
    if has_docs:
        try:
            doc_block = await doc_service.build_document_block(conv.id, max_chars=8000)
            if doc_block:
                system_prompt = (
                    (system_prompt + "\n\n") if system_prompt else ""
                ) + doc_block
        except Exception as e:
            from loguru import logger
            logger.warning(f"Document block build failed for vision (non-blocking): {e}")

    conv_id = conv.id
    user_id = current_user.id

    async def vision_event_generator() -> AsyncGenerator[str, None]:
        full_response = ""
        start = time.monotonic()
        try:
            async for chunk in vision_service.chat_stream(
                message=message,
                conversation_id=conv_id,
                image_bytes=image_bytes_list if has_new_images else None,
                system_prompt=system_prompt,
                session_messages=session_messages,
            ):
                if not chunk:
                    continue
                full_response += chunk
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

            tokens_used = len(full_response) // 4
            latency_ms = int((time.monotonic() - start) * 1000)

            assistant_msg = await conv_repo.add_message(
                conversation_id=conv_id, role="assistant",
                content=full_response, agent_used="vision_agent",
                tokens_used=tokens_used, latency_ms=latency_ms,
            )
            await db.commit()

            await push_session_message(user_id, conv_id, "user", message)
            await push_session_message(user_id, conv_id, "assistant", full_response)

            yield f"data: {json.dumps({'type': 'done', 'conversation_id': conv_id, 'message_id': assistant_msg.id, 'tokens_used': tokens_used, 'latency_ms': latency_ms})}\n\n"

        except Exception as e:
            from loguru import logger
            logger.exception(f"Vision stream error: {e}")
            try:
                await db.rollback()
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'error', 'message': str(e), 'conversation_id': conv_id})}\n\n"

    return StreamingResponse(
        vision_event_generator(),
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


@router.delete("/conversations/{conversation_id}/messages/from/{message_id}")
async def truncate_messages_from(
    conversation_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a message and all messages after it in the conversation."""
    from sqlalchemy import delete as sql_delete
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get_by_id(conversation_id)

    if not conv:
        raise HTTPException(404, "Conversation not found")
    if conv.user_id != current_user.id:
        raise HTTPException(403, "Access denied")

    target = next((m for m in conv.messages if m.id == message_id), None)
    if not target:
        raise HTTPException(404, "Message not found")

    # Collect IDs to delete agent_executions, images, and documents first (FK constraint)
    msg_ids = [m.id for m in conv.messages if m.created_at >= target.created_at]
    await db.execute(
        sql_delete(AgentExecution).where(AgentExecution.message_id.in_(msg_ids))
    )
    await db.execute(
        sql_delete(MessageImageModel).where(MessageImageModel.message_id.in_(msg_ids))
    )
    await db.execute(
        sql_delete(MessageDocumentModel).where(MessageDocumentModel.message_id.in_(msg_ids))
    )
    await db.execute(
        sql_delete(Message).where(
            Message.conversation_id == conversation_id,
            Message.created_at >= target.created_at,
        )
    )
    await db.commit()
    return {"deleted_from": message_id}


@router.delete("/conversations/{conversation_id}/messages/{message_id}")
async def delete_single_message(
    conversation_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a single message by ID (and its agent_executions)."""
    from sqlalchemy import delete as sql_delete
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get_by_id(conversation_id)

    if not conv:
        raise HTTPException(404, "Conversation not found")
    if conv.user_id != current_user.id:
        raise HTTPException(403, "Access denied")

    target = next((m for m in conv.messages if m.id == message_id), None)
    if not target:
        raise HTTPException(404, "Message not found")

    # Delete agent_executions, images, and documents first to satisfy FK constraint
    await db.execute(
        sql_delete(AgentExecution).where(AgentExecution.message_id == message_id)
    )
    await db.execute(
        sql_delete(MessageImageModel).where(MessageImageModel.message_id == message_id)
    )
    await db.execute(
        sql_delete(MessageDocumentModel).where(MessageDocumentModel.message_id == message_id)
    )
    await db.execute(sql_delete(Message).where(Message.id == message_id))
    await db.commit()
    return {"deleted": message_id}


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
