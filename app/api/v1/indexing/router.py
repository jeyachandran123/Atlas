"""
Indexing API.

Endpoints:
  GET  /api/v1/indexing/jobs/{job_id}          → job details from MSSQL
  GET  /api/v1/indexing/jobs/{job_id}/progress → live progress from Redis
  GET  /api/v1/indexing/repos/{repo_id}/jobs   → all jobs for a repo
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_developer
from app.database import get_db
from app.db.models import User
from app.db.repositories import IndexJobRepository, RepositoryRepo
from app.redis_client import get_index_progress
from app.shared.schemas import IndexJobOut

router = APIRouter(prefix="/indexing", tags=["Indexing"])


@router.get("/jobs/{job_id}", response_model=IndexJobOut)
async def get_job(
    job_id: str,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> IndexJobOut:
    """Get indexing job details from MSSQL."""
    job_repo = IndexJobRepository(db)
    job = await job_repo.get_by_id(job_id)
    if not job:
        raise HTTPException(404, "Index job not found")

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


@router.get("/jobs/{job_id}/progress")
async def get_job_progress(
    job_id: str,
    current_user: User = Depends(require_developer),
) -> dict:
    """
    Get live indexing progress from Redis.
    Returns real-time counters — clients should poll this every 2 seconds.
    Falls back to MSSQL data if Redis entry has expired.
    """
    progress = await get_index_progress(job_id)
    if not progress:
        return {"status": "unknown", "message": "No progress data available. Job may have completed."}
    
    # Convert string values from Redis to proper types
    parsed_progress = {
        "status": progress.get("status", "unknown"),
        "total": int(progress.get("total", 0)),
        "processed": int(progress.get("processed", 0)),
        "chunks": int(progress.get("chunks", 0)),
    }
    
    # Add current_file if present
    if "current_file" in progress:
        parsed_progress["current_file"] = progress["current_file"]
    
    return parsed_progress


@router.get("/repos/{repo_id}/jobs", response_model=list[IndexJobOut])
async def list_repo_jobs(
    repo_id: str,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> list[IndexJobOut]:
    """List all indexing jobs for a repository."""
    repo_repo = RepositoryRepo(db)

    repo = await repo_repo.get_by_id(repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")

    has_access = await repo_repo.has_access(current_user.id, repo_id)
    if not has_access:
        raise HTTPException(403, "Access denied")

    from sqlalchemy import select
    from app.db.models import IndexJob

    result = await db.execute(
        select(IndexJob)
        .where(IndexJob.repo_id == repo_id)
        .order_by(IndexJob.created_at.desc())
        .limit(20)
    )
    jobs = list(result.scalars().all())

    return [
        IndexJobOut(
            id=j.id,
            repo_id=j.repo_id,
            job_type=j.job_type,
            status=j.status,
            files_total=j.files_total,
            files_processed=j.files_processed,
            chunks_created=j.chunks_created,
            error_message=j.error_message,
            started_at=j.started_at,
            completed_at=j.completed_at,
            created_at=j.created_at,
        )
        for j in jobs
    ]
