"""Knowledge Workspace endpoints (Phase 5.5) — the Product Experience API."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.db.models import User
from app.document_platform.validation import DocumentValidationError
from app.workspace.export import EXPORT_FORMATS, export_conversation
from app.workspace.intelligence import WorkspaceIntelligence, rule_based_suggestions
from app.workspace.schemas import (
    AddDocumentIn,
    ArtifactEventIn,
    AttachDocumentIn,
    BookmarkIn,
    BookmarkOut,
    ConversationCreateIn,
    ConversationModeIn,
    ConversationRenameIn,
    DashboardOut,
    RelatedOut,
    SaveKnowledgeOut,
    SearchOut,
    TimelineEventOut,
    WorkspaceArtifactOut,
    WorkspaceAskIn,
    WorkspaceConversationOut,
    WorkspaceCreateIn,
    WorkspaceDocumentOut,
    WorkspaceGenerateIn,
    WorkspaceOut,
    WorkspaceUpdateIn,
)
from app.workspace.search import WorkspaceSearch
from app.workspace.service import (
    DuplicateInWorkspaceError,
    WorkspaceNotFoundError,
    WorkspaceService,
)

router = APIRouter(prefix="/workspaces", tags=["Workspace"])


def content_disposition(disposition: str, filename: str) -> str:
    """
    RFC 6266-safe Content-Disposition. HTTP header values must be Latin-1
    encodable; a filename with non-Latin-1 characters (CJK, emoji, Cyrillic —
    common in auto-generated conversation titles) would otherwise raise
    UnicodeEncodeError in the ASGI layer and 500 the response. We emit an
    ASCII-safe `filename` fallback plus an RFC 5987 `filename*` with the real
    UTF-8 name, exactly as browsers expect.
    """
    from urllib.parse import quote

    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii").replace('"', "")
    ascii_fallback = ascii_fallback.strip() or "download"
    utf8_encoded = quote(filename, safe="")
    return f"{disposition}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{utf8_encoded}"


def _ws_out(ws) -> WorkspaceOut:
    return WorkspaceOut(
        id=ws.id, name=ws.name, description=ws.description, icon=ws.icon,
        is_default=ws.is_default, status=ws.status, created_at=ws.created_at,
    )


def _doc_out(d) -> WorkspaceDocumentOut:
    return WorkspaceDocumentOut(
        id=d.id, filename=d.original_filename, extension=d.extension,
        size_bytes=d.size_bytes, processing_status=d.processing_status,
        created_at=d.created_at,
    )


def _conv_out(wc) -> WorkspaceConversationOut:
    return WorkspaceConversationOut(
        conversation_id=wc.conversation_id, title=wc.title,
        title_generated=wc.title_generated, retrieval_mode=wc.retrieval_mode,
        created_at=wc.created_at, updated_at=wc.updated_at,
    )


def _artifact_out(a, conversation_id) -> WorkspaceArtifactOut:
    return WorkspaceArtifactOut(
        id=a.id, title=a.title, filename=a.filename, format=a.format,
        status=a.status, size_bytes=a.size_bytes, grounded=a.grounded,
        conversation_id=conversation_id, created_at=a.created_at,
        prompt=a.prompt, error=a.error,
    )


async def _require(service: WorkspaceService, workspace_id: str, user: User):
    try:
        return await service.require(workspace_id, user)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Workspace not found")


# ── Workspace CRUD ───────────────────────────────────────────────────────────

@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    await service.ensure_default(current_user)  # lazy bootstrap + adoption
    return [_ws_out(w) for w in await service.repo.list_for_user(current_user.id)]


@router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    body: WorkspaceCreateIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    await service.ensure_default(current_user)
    ws = await service.create_workspace(current_user, body.name, body.description, body.icon)
    return _ws_out(ws)


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    return _ws_out(await _require(service, workspace_id, current_user))


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(
    workspace_id: str,
    body: WorkspaceUpdateIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    if body.name is not None:
        ws.name = body.name[:120]
    if body.description is not None:
        ws.description = body.description[:500]
    if body.icon is not None:
        ws.icon = body.icon[:30]
    await db.commit()
    return _ws_out(ws)


@router.delete("/{workspace_id}")
async def archive_workspace(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    if ws.is_default:
        raise HTTPException(422, detail="The default workspace cannot be archived")
    await service.repo.delete_workspace(ws)
    await db.commit()
    return {"id": workspace_id, "archived": True}


# ── Dashboard / intelligence ─────────────────────────────────────────────────

@router.get("/{workspace_id}/dashboard", response_model=DashboardOut)
async def dashboard(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    repo = service.repo
    stats = await repo.stats(ws.id)
    summary_row = await repo.get_summary(ws.id)
    suggestions = (
        json.loads(summary_row.suggestions_json)
        if summary_row and summary_row.suggestions_json
        else rule_based_suggestions(stats)
    )
    return DashboardOut(
        workspace=_ws_out(ws),
        stats=stats,
        summary=summary_row.summary if summary_row else "",
        suggestions=suggestions,
        summary_generated_at=summary_row.generated_at if summary_row else None,
        recent_conversations=[_conv_out(c) for c in (await repo.conversations_for(ws.id))[:5]],
        recent_documents=[_doc_out(d) for d in (await repo.documents_for(ws.id))[:5]],
        recent_artifacts=[
            _artifact_out(a, cid) for a, cid in (await repo.artifacts_for(ws.id))[:5]
        ],
        recent_activity=[
            TimelineEventOut(
                id=e.id, event_type=e.event_type, title=e.title,
                ref_type=e.ref_type, ref_id=e.ref_id,
                detail_json=e.detail_json, created_at=e.created_at,
            )
            for e in await repo.timeline_for(ws.id, limit=8)
        ],
    )


@router.post("/{workspace_id}/summary/refresh")
async def refresh_summary(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Regenerates the AI summary synchronously (an LLM call — the UI calls
    this in the background and updates when it lands)."""
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    result = await WorkspaceIntelligence(service.repo).refresh_summary(ws.id, ws.name)
    await db.commit()
    return result


# ── Documents ────────────────────────────────────────────────────────────────

@router.get("/{workspace_id}/documents", response_model=list[WorkspaceDocumentOut])
async def workspace_documents(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    return [_doc_out(d) for d in await service.repo.documents_for(ws.id)]


@router.post("/{workspace_id}/upload", status_code=201)
async def upload_document(
    workspace_id: str,
    file: UploadFile = File(...),
    conversation_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Atomic workspace upload: one request uploads, links, and (optionally)
    attaches to a conversation — no client-side upload-then-link race (which
    caused the duplicate-context bug). Per-workspace duplicate policy: the
    same file is rejected here but allowed in another workspace.
    """
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    content = await file.read()
    max_bytes = get_settings().dip_max_file_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(413, detail={"code": "too_large", "message": "File exceeds the size limit."})
    try:
        result = await service.upload_document(
            ws, content, file.filename, file.content_type, conversation_id,
        )
    except DuplicateInWorkspaceError as e:
        raise HTTPException(409, detail={
            "code": "duplicate_in_workspace",
            "message": f"“{e.filename}” already exists in this workspace.",
            "existing_id": e.existing_id,
        })
    except DocumentValidationError as e:
        raise HTTPException(422, detail={"code": "invalid_file", "message": str(e)})
    doc = result["document"]
    return {
        "document": _doc_out(doc).model_dump(mode="json"),
        "attached_to_conversation": result["attached_to_conversation"],
    }


@router.get("/{workspace_id}/documents/{document_id}/content")
async def document_content(
    workspace_id: str,
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Inline document bytes for the in-app viewer — same-origin, so no S3
    CORS. The Download button still uses the signed-URL flow separately."""
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    try:
        data, mime, filename = await service.document_content(ws, document_id)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Document not found")
    await db.commit()
    return Response(
        content=data, media_type=mime,
        headers={"Content-Disposition": content_disposition("inline", filename),
                 "Cache-Control": "private, max-age=300"},
    )


@router.get("/{workspace_id}/artifacts/{artifact_id}/content")
async def artifact_content(
    workspace_id: str,
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    try:
        data, mime, filename = await service.artifact_content(ws, artifact_id)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Artifact not found")
    return Response(
        content=data, media_type=mime,
        headers={"Content-Disposition": content_disposition("inline", filename),
                 "Cache-Control": "private, max-age=300"},
    )


@router.delete("/{workspace_id}/documents/{document_id}")
async def delete_document(
    workspace_id: str,
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Complete deletion (Objective 5): purges vectors, embeddings, semantic
    records, chunks, knowledge, workspace/conversation links, and bookmarks —
    then soft-deletes the document. No orphans remain."""
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    try:
        return await service.delete_document(ws, document_id)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Document not found")


@router.post("/{workspace_id}/documents")
async def add_document(
    workspace_id: str,
    body: AddDocumentIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Links an already-uploaded document (via the existing /documents/upload)
    into this workspace — optionally attaching it to a live conversation so
    its context expands without a restart."""
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    try:
        return await service.add_document(ws, body.document_id, body.conversation_id)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Document not found")


# ── Conversations ────────────────────────────────────────────────────────────

@router.get("/{workspace_id}/conversations", response_model=list[WorkspaceConversationOut])
async def workspace_conversations(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    return [_conv_out(c) for c in await service.repo.conversations_for(ws.id)]


@router.post("/{workspace_id}/conversations", status_code=201)
async def start_conversation(
    workspace_id: str,
    body: ConversationCreateIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    conv, title = await service.start_conversation(ws, body.title)
    return {"conversation_id": conv.id, "title": title,
            "correlation_id": conv.correlation_id}


@router.get("/{workspace_id}/conversations/{conversation_id}")
async def restore_conversation(
    workspace_id: str,
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The full-restore payload: turns with citations, attached documents,
    artifacts — everything needed to continue exactly where the user left off."""
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    try:
        return await service.restore_payload(ws, conversation_id)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Conversation not found")


@router.post("/{workspace_id}/conversations/{conversation_id}/ask/stream")
async def workspace_ask_stream(
    workspace_id: str,
    conversation_id: str,
    body: WorkspaceAskIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    try:
        await service.conversation_in_workspace(ws, conversation_id)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Conversation not found")
    return StreamingResponse(
        service.ask_stream(ws, conversation_id, body.question, body.document_ids),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.patch("/{workspace_id}/conversations/{conversation_id}")
async def rename_conversation(
    workspace_id: str,
    conversation_id: str,
    body: ConversationRenameIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    try:
        title = await service.rename_conversation(ws, conversation_id, body.title)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Conversation not found")
    return {"conversation_id": conversation_id, "title": title}


@router.patch("/{workspace_id}/conversations/{conversation_id}/mode")
async def set_conversation_mode(
    workspace_id: str,
    conversation_id: str,
    body: ConversationModeIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Switch retrieval mode (all|selected). Scope changes immediately for the
    next question; history is untouched (Objective 2/6)."""
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    try:
        return await service.set_conversation_mode(ws, conversation_id, body.mode)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Conversation not found")
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@router.delete("/{workspace_id}/conversations/{conversation_id}")
async def delete_conversation(
    workspace_id: str,
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft delete (Objective 4) — the conversation drops out of every list;
    its turns and citations are preserved (auditable, no orphans)."""
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    try:
        await service.delete_conversation(ws, conversation_id)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Conversation not found")
    return {"conversation_id": conversation_id, "deleted": True}


@router.post("/{workspace_id}/conversations/{conversation_id}/documents")
async def attach_document(
    workspace_id: str,
    conversation_id: str,
    body: AttachDocumentIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    try:
        return await service.add_document(ws, body.document_id, conversation_id)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Document not found")


@router.delete("/{workspace_id}/conversations/{conversation_id}/documents/{document_id}")
async def remove_document_from_conversation(
    workspace_id: str,
    conversation_id: str,
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a document from this conversation's context ONLY (Objective 9).
    The document remains in the workspace."""
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    try:
        removed = await service.remove_document_from_conversation(ws, conversation_id, document_id)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Conversation not found")
    return {"document_id": document_id, "removed": removed}


@router.post("/{workspace_id}/conversations/{conversation_id}/save-as-knowledge",
             response_model=SaveKnowledgeOut)
async def save_as_knowledge(
    workspace_id: str,
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    try:
        result = await service.save_as_knowledge(ws, conversation_id)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Conversation not found")
    return SaveKnowledgeOut(**result)


@router.get("/{workspace_id}/conversations/{conversation_id}/export")
async def export_conversation_endpoint(
    workspace_id: str,
    conversation_id: str,
    format: str = "markdown",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if format not in EXPORT_FORMATS:
        raise HTTPException(422, detail=f"format must be one of {sorted(EXPORT_FORMATS)}")
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    try:
        wc, _ = await service.conversation_in_workspace(ws, conversation_id)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Conversation not found")
    turns = await service.repo.turns_for_conversation(conversation_id)
    data, content_type, ext = export_conversation(wc.title, turns, format)
    base = (wc.title[:60].strip() or "conversation")
    return Response(
        content=data, media_type=content_type,
        headers={"Content-Disposition": content_disposition("attachment", f"{base}.{ext}")},
    )


# ── Generation ───────────────────────────────────────────────────────────────

@router.post("/{workspace_id}/generate/stream")
async def workspace_generate_stream(
    workspace_id: str,
    body: WorkspaceGenerateIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    if body.conversation_id:
        try:
            await service.conversation_in_workspace(ws, body.conversation_id)
        except WorkspaceNotFoundError:
            raise HTTPException(404, detail="Conversation not found")
    return StreamingResponse(
        service.generate_stream(ws, body.prompt, body.format, body.conversation_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{workspace_id}/artifacts", response_model=list[WorkspaceArtifactOut])
async def workspace_artifacts(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    return [_artifact_out(a, cid) for a, cid in await service.repo.artifacts_for(ws.id)]


@router.delete("/{workspace_id}/artifacts/{artifact_id}")
async def delete_artifact(
    workspace_id: str,
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full lifecycle deletion of a generated document (Objective: no orphans).
    Removes the S3 object, event log, registry row, workspace + conversation
    reference, and bookmarks; search and the panel drop it automatically."""
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    try:
        return await service.delete_artifact(ws, artifact_id)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Artifact not found")


@router.post("/{workspace_id}/artifacts/{artifact_id}/event")
async def record_artifact_event(
    workspace_id: str,
    artifact_id: str,
    body: ArtifactEventIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a View / Download of a generated document on the timeline. The
    download itself still goes through the existing generation download flow."""
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    try:
        await service.record_artifact_event(ws, artifact_id, body.action)
    except WorkspaceNotFoundError:
        raise HTTPException(404, detail="Artifact not found")
    return {"recorded": body.action}


# ── Timeline / bookmarks / search / related ──────────────────────────────────

@router.get("/{workspace_id}/timeline", response_model=list[TimelineEventOut])
async def workspace_timeline(
    workspace_id: str,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    return [
        TimelineEventOut(
            id=e.id, event_type=e.event_type, title=e.title,
            ref_type=e.ref_type, ref_id=e.ref_id,
            detail_json=e.detail_json, created_at=e.created_at,
        )
        for e in await service.repo.timeline_for(ws.id, limit=min(limit, 200))
    ]


@router.post("/{workspace_id}/bookmarks", response_model=BookmarkOut, status_code=201)
async def add_bookmark(
    workspace_id: str,
    body: BookmarkIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    bm = await service.repo.add_bookmark(
        ws.id, current_user.id, body.target_type, body.target_id, body.note,
    )
    await service.repo.add_timeline(
        ws.id, "bookmark_added", f"Bookmarked a {body.target_type}",
        ref_type=body.target_type, ref_id=body.target_id,
    )
    await db.commit()
    return BookmarkOut(
        id=bm.id, target_type=bm.target_type, target_id=bm.target_id,
        note=bm.note, created_at=bm.created_at,
    )


@router.get("/{workspace_id}/bookmarks", response_model=list[BookmarkOut])
async def list_bookmarks(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    return [
        BookmarkOut(
            id=b.id, target_type=b.target_type, target_id=b.target_id,
            note=b.note, created_at=b.created_at,
        )
        for b in await service.repo.bookmarks_for(ws.id)
    ]


@router.delete("/{workspace_id}/bookmarks/{bookmark_id}")
async def delete_bookmark(
    workspace_id: str,
    bookmark_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    deleted = await service.repo.delete_bookmark(ws.id, bookmark_id)
    await db.commit()
    if not deleted:
        raise HTTPException(404, detail="Bookmark not found")
    return {"id": bookmark_id, "deleted": True}


@router.get("/{workspace_id}/search", response_model=SearchOut)
async def workspace_search(
    workspace_id: str,
    q: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not q.strip():
        raise HTTPException(422, detail="q must not be empty")
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    results = await WorkspaceSearch(service.repo).search(ws.id, ws.org_id, q.strip())
    return SearchOut(query=q.strip(), results=results)


@router.get("/{workspace_id}/related", response_model=RelatedOut)
async def workspace_related(
    workspace_id: str,
    q: str,
    conversation_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WorkspaceService(db)
    ws = await _require(service, workspace_id, current_user)
    result = await service.related(ws, q, conversation_id)
    return RelatedOut(**result)
