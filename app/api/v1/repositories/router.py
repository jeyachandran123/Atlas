"""
Repository management API.

Endpoints:
  POST   /api/v1/repositories          → connect a repository
  GET    /api/v1/repositories          → list accessible repositories
  GET    /api/v1/repositories/{id}     → get repository details
  DELETE /api/v1/repositories/{id}     → disconnect repository
  POST   /api/v1/repositories/{id}/sync → trigger re-index
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin, require_developer
from app.database import get_db
from app.db.models import User
from app.db.repositories import IndexJobRepository, RepositoryRepo
from app.redis_client import enqueue_index_job
from app.shared.schemas import IndexJobOut, RepoOut

router = APIRouter(prefix="/repositories", tags=["Repositories"])


class ConnectRepoRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    local_path: str = Field(..., min_length=1, max_length=1000)
    provider: str = Field(default="local")
    remote_url: Optional[str] = None
    default_branch: str = Field(default="main")


@router.post("", response_model=RepoOut, status_code=201)
async def connect_repository(
    req: ConnectRepoRequest,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> RepoOut:
    """Connect a local or remote repository."""
    repo_repo = RepositoryRepo(db)

    # Validate local path exists
    if not os.path.isdir(req.local_path):
        raise HTTPException(400, f"Directory not found: {req.local_path}")

    # Normalise path
    local_path = os.path.realpath(req.local_path)

    repo = await repo_repo.create(
        org_id=current_user.org_id,
        name=req.name,
        provider=req.provider,
        local_path=local_path,
        remote_url=req.remote_url,
        default_branch=req.default_branch,
    )

    # Grant the creator admin access
    await repo_repo.grant_access(repo.id, current_user.id, permission="admin")

    # Auto-trigger initial indexing
    job_repo = IndexJobRepository(db)
    job = await job_repo.create(
        repo_id=repo.id,
        triggered_by=current_user.id,
        job_type="full",
        status="queued",
    )

    await enqueue_index_job({
        "job_id": job.id,
        "repo_id": repo.id,
        "repo_path": local_path,
        "job_type": "full",
    })

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
    """List repositories the current user has access to."""
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


@router.get("/{repo_id}", response_model=RepoOut)
async def get_repository(
    repo_id: str,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> RepoOut:
    """Get details of a specific repository."""
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


@router.post("/{repo_id}/sync", response_model=IndexJobOut)
async def sync_repository(
    repo_id: str,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> IndexJobOut:
    """Trigger incremental re-indexing of a repository."""
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
