"""
Document Intelligence Platform — Phase 1 REST API.

Endpoints:
  POST   /api/v1/documents/upload           → upload one document
  GET    /api/v1/documents                  → list (pagination, search, filters)
  GET    /api/v1/documents/{id}             → metadata
  GET    /api/v1/documents/{id}/download    → signed URL (falls back to proxy)
  DELETE /api/v1/documents/{id}             → soft delete

Controllers do HTTP only: parse input, call the service, map errors.
No storage, SQL, or validation logic lives here.
"""
from __future__ import annotations

import json
import uuid as uuid_module
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.db.models import User
from app.document_platform.audit import DocumentAuditLogger
from app.document_platform.repository import DocumentRepository
from app.document_platform.schemas import (
    DeleteResponse,
    DocumentListOut,
    DocumentOut,
    DownloadLinkOut,
    UploadResponse,
)
from app.document_platform.service import (
    DocumentNotFoundError,
    DocumentPlatformService,
    DuplicateDocumentError,
)
from app.document_platform.validation import DocumentValidationError

router = APIRouter(prefix="/documents", tags=["Documents"])


# ── Dependency injection ─────────────────────────────────────────────────────


def get_document_platform_service(
    db: AsyncSession = Depends(get_db),
) -> DocumentPlatformService:
    """Per-request service wired to the request's DB session."""
    return DocumentPlatformService(
        repository=DocumentRepository(db),
        audit=DocumentAuditLogger(db),
    )


def _validation_http_error(e: DocumentValidationError) -> HTTPException:
    status = 413 if e.code == "file_too_large" else 422
    return HTTPException(status_code=status, detail={"code": e.code, "message": str(e)})


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/upload", response_model=UploadResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    tags: Optional[str] = Form(None, description="JSON array of tags"),
    allow_duplicate: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: DocumentPlatformService = Depends(get_document_platform_service),
):
    request_id = str(uuid_module.uuid4())
    content = await file.read()

    parsed_tags: Optional[list[str]] = None
    if tags:
        try:
            raw = json.loads(tags)
            if isinstance(raw, list):
                parsed_tags = [str(t)[:50] for t in raw][:20]
        except ValueError:
            raise HTTPException(422, detail={"code": "invalid_tags", "message": "tags must be a JSON array"})

    try:
        doc, duplicate_of = await service.upload(
            org_id=current_user.org_id,
            user_id=current_user.id,
            filename=file.filename,
            content=content,
            declared_mime=file.content_type,
            tags=parsed_tags,
            allow_duplicate=allow_duplicate,
            request_id=request_id,
        )
    except DocumentValidationError as e:
        raise _validation_http_error(e)
    except DuplicateDocumentError as e:
        await db.commit()  # persist the duplicate_rejected audit row
        raise HTTPException(
            409,
            detail={
                "code": "duplicate_document",
                "message": "An identical file already exists.",
                "existing_id": e.existing_id,
            },
        )
    except Exception:
        await db.commit()  # persist the failed row + audit for observability
        raise HTTPException(502, detail={"code": "storage_error", "message": "Upload to storage failed."})

    await db.commit()
    return UploadResponse(document=DocumentOut.from_model(doc), duplicate_of=duplicate_of)


@router.get("", response_model=DocumentListOut)
async def list_documents(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None, max_length=200, description="Search by filename"),
    extension: Optional[str] = Query(None, max_length=10),
    status: Optional[str] = Query(None, pattern="^(uploading|completed|failed)$"),
    current_user: User = Depends(get_current_user),
    service: DocumentPlatformService = Depends(get_document_platform_service),
):
    items, total = await service.list(
        current_user.id, limit=limit, offset=offset,
        search=q, extension=extension, status=status,
    )
    return DocumentListOut(
        items=[DocumentOut.from_model(d) for d in items],
        total=total, limit=limit, offset=offset,
    )


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    service: DocumentPlatformService = Depends(get_document_platform_service),
):
    try:
        doc = await service.get(current_user.id, document_id)
    except DocumentNotFoundError:
        raise HTTPException(404, detail={"code": "not_found", "message": "Document not found."})
    return DocumentOut.from_model(doc)


@router.get("/{document_id}/download")
async def download_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: DocumentPlatformService = Depends(get_document_platform_service),
):
    """
    Returns a signed, time-limited URL when the storage backend supports it
    (S3); otherwise streams the bytes through the API. Either way the raw
    storage location is never exposed unsigned.
    """
    try:
        link = await service.download_link(current_user.org_id, current_user.id, document_id)
        if link is not None:
            url, ttl = link
            await db.commit()
            return DownloadLinkOut(document_id=document_id, url=url, expires_in_seconds=ttl)

        doc, data = await service.download_bytes(current_user.org_id, current_user.id, document_id)
    except DocumentNotFoundError:
        raise HTTPException(404, detail={"code": "not_found", "message": "Document not found."})

    await db.commit()
    safe_name = doc.original_filename.replace('"', "")
    return Response(
        content=data,
        media_type=doc.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "Content-Length": str(len(data)),
        },
    )


@router.delete("/{document_id}", response_model=DeleteResponse)
async def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: DocumentPlatformService = Depends(get_document_platform_service),
):
    try:
        await service.delete(current_user.org_id, current_user.id, document_id)
    except DocumentNotFoundError:
        raise HTTPException(404, detail={"code": "not_found", "message": "Document not found."})
    await db.commit()
    return DeleteResponse(id=document_id, deleted=True)
