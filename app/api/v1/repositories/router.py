"""
Repository management API.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_developer
from app.database import get_db
from app.db.models import User
from app.db.repositories import IndexJobRepository, IndexedFileRepository, RepositoryRepo
from app.redis_client import enqueue_index_job
from app.shared.schemas import IndexJobOut, RepoOut
from app.vector_store.chroma_client import get_chroma_store
from app.vector_store.base import VectorStore

router = APIRouter(prefix="/repositories", tags=["Repositories"])


class ConnectRepoRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    local_path: Optional[str] = Field(default=None, max_length=1000)
    provider: str = Field(default="local")
    remote_url: Optional[str] = None
    default_branch: str = Field(default="main")


@router.post("", response_model=RepoOut, status_code=201)
async def connect_repository(
    req: ConnectRepoRequest,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> RepoOut:
    repo_repo = RepositoryRepo(db)

    if not req.local_path and not req.remote_url:
        raise HTTPException(400, "Either local_path or remote_url is required")

    if req.local_path:
        try:
            local_path = os.path.realpath(req.local_path)
        except Exception:
            local_path = req.local_path
        if not os.path.isdir(local_path):
            from loguru import logger
            logger.warning(f"Repository path not found on server: {local_path!r} — registering anyway")
    else:
        local_path = req.remote_url or ""

    try:
        repo = await repo_repo.create(
            org_id=current_user.org_id,
            name=req.name,
            provider=req.provider,
            local_path=local_path,
            remote_url=req.remote_url,
            default_branch=req.default_branch,
        )
        await repo_repo.grant_access(repo.id, current_user.id, permission="admin")
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "A repository with this path is already registered in your organization")

    job_repo = IndexJobRepository(db)
    job = await job_repo.create(
        repo_id=repo.id,
        triggered_by=current_user.id,
        job_type="full",
        status="queued",
    )

    try:
        await enqueue_index_job({
            "job_id": job.id,
            "repo_id": repo.id,
            "repo_path": local_path,
            "job_type": "full",
        })
    except Exception:
        from loguru import logger
        logger.warning(f"Redis unavailable — job {job.id} queued in DB but not enqueued")
        # Repo is still created; worker will pick it up on reconnect

    return RepoOut(
        id=repo.id,
        name=repo.name,
        local_path=repo.local_path,
        provider=repo.provider,
        index_status=repo.index_status,
        file_count=repo.file_count,
        chunk_count=repo.chunk_count,
        last_indexed_at=repo.last_indexed_at,
        created_at=repo.created_at,
    )


@router.get("", response_model=list[RepoOut])
async def list_repositories(
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> list[RepoOut]:
    repo_repo = RepositoryRepo(db)
    repos = await repo_repo.list_for_user(current_user.id)
    return [
        RepoOut(
            id=r.id,
            name=r.name,
            local_path=r.local_path,
            provider=r.provider,
            index_status=r.index_status,
            file_count=r.file_count,
            chunk_count=r.chunk_count,
            last_indexed_at=r.last_indexed_at,
            created_at=r.created_at,
        )
        for r in repos
    ]


@router.post("/{repo_id}/sync", response_model=IndexJobOut)
async def sync_repository(
    repo_id: str,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> IndexJobOut:
    repo_repo = RepositoryRepo(db)
    job_repo = IndexJobRepository(db)

    repo = await repo_repo.get_by_id(repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")

    has_access = await repo_repo.has_access(current_user.id, repo_id, "write")
    if not has_access:
        raise HTTPException(403, "Write access required to trigger re-indexing")

    job = await job_repo.create(
        repo_id=repo_id,
        triggered_by=current_user.id,
        job_type="incremental",
        status="queued",
    )

    await enqueue_index_job({
        "job_id": job.id,
        "repo_id": repo_id,
        "repo_path": repo.local_path,
        "job_type": "incremental",
    })

    return IndexJobOut(
        id=job.id,
        repo_id=job.repo_id,
        job_type=job.job_type,
        status=job.status,
        files_total=job.files_total,
        files_processed=job.files_processed,
        chunks_created=job.chunks_created,
        error_message=job.error_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )


@router.get("/{repo_id}", response_model=RepoOut)
async def get_repository(
    repo_id: str,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> RepoOut:
    repo_repo = RepositoryRepo(db)

    repo = await repo_repo.get_by_id(repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")

    has_access = await repo_repo.has_access(current_user.id, repo_id)
    if not has_access:
        raise HTTPException(403, "Access denied")

    return RepoOut(
        id=repo.id,
        name=repo.name,
        local_path=repo.local_path,
        provider=repo.provider,
        index_status=repo.index_status,
        file_count=repo.file_count,
        chunk_count=repo.chunk_count,
        last_indexed_at=repo.last_indexed_at,
        created_at=repo.created_at,
    )


@router.delete("/{repo_id}", status_code=204)
async def delete_repository(
    repo_id: str,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> Response:
    repo_repo = RepositoryRepo(db)
    file_repo = IndexedFileRepository(db)

    repo = await repo_repo.get_by_id(repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")

    has_access = await repo_repo.has_access(current_user.id, repo_id, "admin")
    if not has_access:
        raise HTTPException(403, "Admin access required to delete repository")

    try:
        vs = await get_chroma_store()
        await vs.delete_collection(VectorStore.code_collection(repo_id))
    except Exception:
        pass

    await file_repo.delete_all_for_repo(repo_id)

    from sqlalchemy import delete as sa_delete
    from app.db.models import IndexJob, RepositoryAccess, Repository
    await db.execute(sa_delete(IndexJob).where(IndexJob.repo_id == repo_id))
    await db.execute(sa_delete(RepositoryAccess).where(RepositoryAccess.repo_id == repo_id))
    await db.execute(sa_delete(Repository).where(Repository.id == repo_id))
    await db.commit()

    return Response(status_code=204)
