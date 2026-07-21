"""Intelligent Content Generation endpoints (Phase 5)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.db.models import GenerationArtifact, User
from app.document_platform.generation.builders.factory import (
    UnknownFormatError,
    get_builder_factory,
)
from app.document_platform.generation.gateway import GenerationGateway
from app.document_platform.generation.repository import GenerationRepository
from app.document_platform.generation.schemas import (
    ArtifactOut,
    DownloadOut,
    FormatsOut,
    GenerateIn,
    GenerationEventOut,
)

router = APIRouter(prefix="/generations", tags=["Generation"])


def _artifact_out(a: GenerationArtifact) -> ArtifactOut:
    return ArtifactOut(
        id=a.id, status=a.status, format=a.format, title=a.title,
        filename=a.filename, content_type=a.content_type, checksum=a.checksum,
        size_bytes=a.size_bytes, grounded=a.grounded,
        builder_name=a.builder_name, builder_version=a.builder_version,
        spec_version=a.spec_version, schema_version=a.schema_version,
        source_document_id=a.source_document_id,
        source_knowledge_ids_json=a.source_knowledge_ids_json,
        llm_provider=a.llm_provider, llm_model=a.llm_model,
        planning_ms=a.planning_ms, transform_ms=a.transform_ms,
        build_ms=a.build_ms, store_ms=a.store_ms, total_ms=a.total_ms,
        prompt_tokens=a.prompt_tokens, completion_tokens=a.completion_tokens,
        error=a.error, correlation_id=a.correlation_id,
        created_at=a.created_at, finished_at=a.finished_at,
    )


@router.get("/formats", response_model=FormatsOut)
async def supported_formats(current_user: User = Depends(get_current_user)):
    return FormatsOut(formats=get_builder_factory().supported_formats())


@router.post("", response_model=ArtifactOut, status_code=201)
async def generate(
    body: GenerateIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    gateway = GenerationGateway(db)
    try:
        artifact = await gateway.generate(
            current_user.id, current_user.org_id, body.prompt,
            body.format, body.document_id,
        )
    except UnknownFormatError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _artifact_out(artifact)


@router.post("/stream")
async def generate_stream(
    body: GenerateIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """SSE progress stream: meta → stage* → done. Same pipeline, registry,
    and lifecycle as POST /generations — plus live visibility."""
    gateway = GenerationGateway(db)
    return StreamingResponse(
        gateway.generate_stream(
            current_user.id, current_user.org_id, body.prompt,
            body.format, body.document_id,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("", response_model=list[ArtifactOut])
async def list_generations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await GenerationRepository(db).list_artifacts(current_user.id)
    return [_artifact_out(a) for a in rows]


@router.get("/{artifact_id}", response_model=ArtifactOut)
async def get_generation(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    artifact = await GenerationRepository(db).get_artifact(artifact_id, current_user.id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return _artifact_out(artifact)


@router.get("/{artifact_id}/download")
async def download_generation(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = GenerationRepository(db)
    artifact = await repo.get_artifact(artifact_id, current_user.id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if artifact.status != "ready":
        raise HTTPException(status_code=409, detail=f"Artifact is {artifact.status}, not ready")
    info, data = await GenerationGateway(db).download(artifact)
    if info.mode == "signed_url":
        return DownloadOut(**info.__dict__)
    return Response(
        content=data, media_type=info.content_type,
        headers={"Content-Disposition": f'attachment; filename="{info.filename}"'},
    )


@router.get("/{artifact_id}/events", response_model=list[GenerationEventOut])
async def generation_events(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = GenerationRepository(db)
    artifact = await repo.get_artifact(artifact_id, current_user.id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    events = await repo.events_for_artifact(artifact_id)
    return [
        GenerationEventOut(
            id=e.id, event_type=e.event_type, status=e.status,
            duration_ms=e.duration_ms, detail_json=e.detail_json,
            created_at=e.created_at,
        )
        for e in events
    ]
