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
    ChunkListOut,
    ChunkOut,
    ContentIdentityOut,
    DeleteResponse,
    DocumentImageOut,
    DocumentListOut,
    DocumentOut,
    DownloadLinkOut,
    HealthOut,
    KnowledgeMetadataOut,
    KnowledgeObjectOut,
    LineageOut,
    LineageStepOut,
    ManifestOut,
    ProcessingEventOut,
    ProcessingStateOut,
    ReprocessResponse,
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


@router.get("/{document_id}/processing", response_model=ProcessingStateOut)
async def get_processing_state(
    document_id: str,
    current_user: User = Depends(get_current_user),
    service: DocumentPlatformService = Depends(get_document_platform_service),
):
    """Pipeline status + the full per-stage event timeline for a document."""
    try:
        doc, job, events = await service.processing_state(current_user.id, document_id)
    except DocumentNotFoundError:
        raise HTTPException(404, detail={"code": "not_found", "message": "Document not found."})
    return ProcessingStateOut(
        document_id=doc.id,
        processing_status=doc.processing_status,
        job_status=job.status if job else None,
        current_stage=job.current_stage if job else None,
        attempt=job.attempt if job else None,
        error=job.error if job else None,
        correlation_id=job.correlation_id if job else None,
        events=[
            ProcessingEventOut(
                stage=e.stage,
                status=e.status,
                duration_ms=e.duration_ms,
                detail=json.loads(e.detail_json) if e.detail_json else None,
                created_at=e.created_at,
            )
            for e in events
        ],
    )


@router.get("/{document_id}/knowledge", response_model=KnowledgeObjectOut)
async def get_knowledge_object(
    document_id: str,
    include_structure: bool = Query(False, description="Include the full node tree"),
    current_user: User = Depends(get_current_user),
    service: DocumentPlatformService = Depends(get_document_platform_service),
):
    """The Knowledge Object built from this document."""
    try:
        doc, ko, meta, images = await service.knowledge(current_user.id, document_id)
    except DocumentNotFoundError:
        raise HTTPException(404, detail={"code": "not_found", "message": "Document not found."})
    if ko is None:
        raise HTTPException(
            409,
            detail={
                "code": "not_ready",
                "message": f"Knowledge object not built yet (processing status: {doc.processing_status}).",
            },
        )
    return KnowledgeObjectOut(
        id=ko.id,
        document_id=doc.id,
        title=ko.title,
        doc_type=ko.doc_type,
        language=ko.language,
        confidence=ko.confidence,
        word_count=ko.word_count,
        char_count=ko.char_count,
        chunk_count=ko.chunk_count,
        table_count=ko.table_count,
        image_count=ko.image_count,
        section_count=ko.section_count,
        structure=json.loads(ko.structure_json) if include_structure and ko.structure_json else None,
        metadata=KnowledgeMetadataOut(
            title=meta.title, author=meta.author, language=meta.language,
            page_count=meta.page_count, sheet_count=meta.sheet_count,
            slide_count=meta.slide_count, word_count=meta.word_count,
            char_count=meta.char_count, encoding=meta.encoding,
            custom=json.loads(meta.custom_json) if meta.custom_json else None,
        ) if meta else None,
        images=[
            DocumentImageOut(
                id=i.id, name=i.name, format=i.format, page=i.page,
                width=i.width, height=i.height, size_bytes=i.size_bytes,
            )
            for i in images
        ],
        parser_version=ko.parser_version,
        chunk_version=ko.chunk_version,
        processing_version=ko.processing_version,
        schema_version=ko.schema_version,
        status=ko.status,
        embedding_status=ko.embedding_status,
        index_status=ko.index_status,
        retrieval_status=ko.retrieval_status,
        generation_status=ko.generation_status,
        parent_knowledge_id=ko.parent_knowledge_id,
        created_at=ko.created_at,
        updated_at=ko.updated_at,
    )


@router.get("/{document_id}/chunks", response_model=ChunkListOut)
async def list_chunks(
    document_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    service: DocumentPlatformService = Depends(get_document_platform_service),
):
    """The semantic chunks built from this document, in order."""
    try:
        chunks, total = await service.chunks(current_user.id, document_id, limit, offset)
    except DocumentNotFoundError:
        raise HTTPException(404, detail={"code": "not_found", "message": "Document not found."})
    return ChunkListOut(
        document_id=document_id,
        items=[
            ChunkOut(
                id=c.id, seq=c.seq, content=c.content, token_count=c.token_count,
                node_type=c.node_type, section_path=c.section_path, page=c.page,
                meta=json.loads(c.meta_json) if c.meta_json else None,
            )
            for c in chunks
        ],
        total=total, limit=limit, offset=offset,
    )


@router.get("/{document_id}/manifest", response_model=ManifestOut)
async def get_manifest(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: DocumentPlatformService = Depends(get_document_platform_service),
):
    """The operational dashboard model for this document's Knowledge Object."""
    from app.document_platform.knowledge.repository import KnowledgeManifestRepository

    try:
        await service.get(current_user.id, document_id)  # ownership check
    except DocumentNotFoundError:
        raise HTTPException(404, detail={"code": "not_found", "message": "Document not found."})

    manifest = await KnowledgeManifestRepository(db).get_by_document_id(document_id)
    if manifest is None:
        raise HTTPException(
            409, detail={"code": "not_ready", "message": "No manifest yet — processing may still be running."},
        )
    return ManifestOut(
        document_id=document_id,
        knowledge_id=manifest.knowledge_object_id,
        correlation_id=manifest.correlation_id,
        lifecycle_state=manifest.lifecycle_state,
        parser_name=manifest.parser_name,
        parser_version=manifest.parser_version,
        chunk_version=manifest.chunk_version,
        embedding_version=manifest.embedding_version,
        knowledge_version=manifest.knowledge_version,
        relationship_version=manifest.relationship_version,
        schema_version=manifest.schema_version,
        processing_version=manifest.processing_version,
        validation_status=manifest.validation_status,
        current_stage=manifest.current_stage,
        capabilities=json.loads(manifest.capabilities_json) if manifest.capabilities_json else None,
        warnings=json.loads(manifest.warnings_json) if manifest.warnings_json else [],
        failures=json.loads(manifest.failures_json) if manifest.failures_json else [],
        retry_count=manifest.retry_count,
        content_identity=ContentIdentityOut(**json.loads(manifest.content_identity_json))
        if manifest.content_identity_json else None,
        workspace_id=manifest.workspace_id,
        visibility=manifest.visibility,
        created_at=manifest.created_at,
        updated_at=manifest.updated_at,
    )


@router.get("/{document_id}/health", response_model=HealthOut)
async def get_health(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: DocumentPlatformService = Depends(get_document_platform_service),
):
    """Computed operational health — never stored, always derived fresh."""
    from app.document_platform.knowledge.health import KnowledgeHealthEvaluator
    from app.document_platform.knowledge.lifecycle import KnowledgeLifecycle
    from app.document_platform.knowledge.repository import KnowledgeManifestRepository
    from app.document_platform.processing.persistence import ProcessingRepository
    from app.platform.capabilities import get_capability_registry

    try:
        await service.get(current_user.id, document_id)
    except DocumentNotFoundError:
        raise HTTPException(404, detail={"code": "not_found", "message": "Document not found."})

    manifest = await KnowledgeManifestRepository(db).get_by_document_id(document_id)
    if manifest is None:
        raise HTTPException(409, detail={"code": "not_ready", "message": "No manifest yet."})

    job = await ProcessingRepository(db).latest_job_for(document_id)
    evaluator = KnowledgeHealthEvaluator(get_capability_registry())
    report = evaluator.evaluate(
        lifecycle=KnowledgeLifecycle(manifest.lifecycle_state),
        parser_name=manifest.parser_name,
        parser_version=manifest.parser_version,
        chunk_version=manifest.chunk_version,
        job_status=job.status if job else "unknown",
        job_error=job.error if job else None,
        warnings=json.loads(manifest.warnings_json) if manifest.warnings_json else [],
        retry_count=manifest.retry_count,
    )
    return HealthOut(document_id=document_id, status=report.status.value, reasons=report.reasons)


@router.get("/{document_id}/lineage", response_model=LineageOut)
async def get_lineage(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: DocumentPlatformService = Depends(get_document_platform_service),
):
    """Answers 'where did this knowledge come from?' by walking the provenance graph."""
    from app.document_platform.knowledge.lineage import LineageNodeType, LineageTracker
    from app.document_platform.knowledge.repository import KnowledgeManifestRepository

    try:
        await service.get(current_user.id, document_id)
    except DocumentNotFoundError:
        raise HTTPException(404, detail={"code": "not_found", "message": "Document not found."})

    manifest = await KnowledgeManifestRepository(db).get_by_document_id(document_id)
    if manifest is None:
        return LineageOut(document_id=document_id, chain=[])

    tracker = LineageTracker(KnowledgeManifestRepository(db))
    chain = await tracker.trace_to_origin(LineageNodeType.KNOWLEDGE_OBJECT, manifest.knowledge_object_id)
    return LineageOut(
        document_id=document_id,
        chain=[LineageStepOut(**step) for step in chain],
    )


@router.post("/{document_id}/process", response_model=ReprocessResponse)
async def reprocess_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: DocumentPlatformService = Depends(get_document_platform_service),
):
    """Re-enqueue a document through the processing pipeline (idempotent)."""
    try:
        job_id = await service.reprocess(current_user.id, document_id)
    except DocumentNotFoundError:
        raise HTTPException(404, detail={"code": "not_found", "message": "Document not found."})
    await db.commit()
    return ReprocessResponse(document_id=document_id, job_id=job_id)


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
