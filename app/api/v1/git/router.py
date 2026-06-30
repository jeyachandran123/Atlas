"""
Git API router.

Provides REST endpoints for Git operations within repositories.
All operations are read-only for safety (no commits, pushes, pulls).

Endpoints:
  GET /api/v1/git/{repo_id}/status      → git status
  GET /api/v1/git/{repo_id}/diff        → git diff
  GET /api/v1/git/{repo_id}/log         → git log
  GET /api/v1/git/{repo_id}/branches    → list branches
  GET /api/v1/git/{repo_id}/show        → show specific commit
  GET /api/v1/git/{repo_id}/blame       → git blame for file
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_developer
from app.database import get_db
from app.db.models import User
from app.db.repositories import RepositoryRepo

router = APIRouter(prefix="/git", tags=["Git"])


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────────────────────


class GitStatusResponse(BaseModel):
    """Response for git status."""
    branch: str
    is_clean: bool
    staged: list[str]
    modified: list[str]
    untracked: list[str]
    ahead: int = 0  # Commits ahead of remote
    behind: int = 0  # Commits behind remote


class GitDiffResponse(BaseModel):
    """Response for git diff."""
    diff: str
    files_changed: int
    insertions: int
    deletions: int


class GitCommit(BaseModel):
    """A single git commit."""
    sha: str
    author: str
    email: str
    date: str
    message: str


class GitLogResponse(BaseModel):
    """Response for git log."""
    commits: list[GitCommit]
    total: int


class GitBranch(BaseModel):
    """A git branch."""
    name: str
    is_current: bool
    last_commit_sha: str
    last_commit_message: str


class GitBranchesResponse(BaseModel):
    """Response for git branches."""
    branches: list[GitBranch]
    current_branch: str


class GitShowResponse(BaseModel):
    """Response for git show."""
    commit: GitCommit
    diff: str


class GitBlameLine(BaseModel):
    """A line with blame information."""
    line_number: int
    content: str
    commit_sha: str
    author: str
    date: str


class GitBlameResponse(BaseModel):
    """Response for git blame."""
    file_path: str
    lines: list[GitBlameLine]


# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────


def _validate_is_git_repo(repo_path: str) -> None:
    """Check if directory is a git repository."""
    git_dir = os.path.join(repo_path, '.git')
    if not os.path.exists(git_dir):
        raise HTTPException(400, "Not a git repository")


def _parse_git_status(status_output: str) -> tuple[list[str], list[str], list[str]]:
    """Parse git status --short output."""
    staged = []
    modified = []
    untracked = []
    
    for line in status_output.strip().split('\n'):
        if not line:
            continue
        
        status = line[:2]
        file_path = line[3:].strip()
        
        if status[0] in ['M', 'A', 'D', 'R']:
            staged.append(file_path)
        if status[1] == 'M':
            modified.append(file_path)
        if status == '??':
            untracked.append(file_path)
    
    return staged, modified, untracked


def _parse_git_log(log_output: str) -> list[GitCommit]:
    """Parse git log output."""
    commits = []
    
    # Split by commit delimiter
    commit_blocks = log_output.strip().split('\n---COMMIT---\n')
    
    for block in commit_blocks:
        if not block.strip():
            continue
        
        lines = block.strip().split('\n')
        if len(lines) < 4:
            continue
        
        try:
            commits.append(GitCommit(
                sha=lines[0],
                author=lines[1],
                email=lines[2],
                date=lines[3],
                message='\n'.join(lines[4:]) if len(lines) > 4 else "",
            ))
        except Exception:
            continue
    
    return commits


def _parse_diff_stats(diff_output: str) -> tuple[int, int, int]:
    """Parse git diff --stat output to get files changed, insertions, deletions."""
    files_changed = 0
    insertions = 0
    deletions = 0
    
    # Look for summary line like: "2 files changed, 10 insertions(+), 5 deletions(-)"
    lines = diff_output.strip().split('\n')
    for line in lines:
        if 'file' in line and 'changed' in line:
            parts = line.split(',')
            for part in parts:
                if 'file' in part and 'changed' in part:
                    files_changed = int(part.split()[0])
                elif 'insertion' in part:
                    insertions = int(part.split()[0])
                elif 'deletion' in part:
                    deletions = int(part.split()[0])
    
    return files_changed, insertions, deletions


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{repo_id}/status", response_model=GitStatusResponse)
async def get_git_status(
    repo_id: str,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> GitStatusResponse:
    """
    Get git status for repository.
    
    Shows current branch, staged/modified/untracked files.
    """
    repo_repo = RepositoryRepo(db)
    
    # Check access
    repo = await repo_repo.get_by_id(repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")
    
    has_access = await repo_repo.has_access(current_user.id, repo_id)
    if not has_access:
        raise HTTPException(403, "Access denied")
    
    _validate_is_git_repo(repo.local_path)
    
    try:
        from git import Repo as GitRepo
        
        git_repo = GitRepo(repo.local_path)
        
        # Get current branch
        try:
            current_branch = git_repo.active_branch.name
        except Exception:
            current_branch = "HEAD (detached)"
        
        # Get status
        status_output = git_repo.git.status('--short')
        staged, modified, untracked = _parse_git_status(status_output)
        
        is_clean = not staged and not modified and not untracked
        
        # Check if ahead/behind remote
        ahead = 0
        behind = 0
        try:
            if git_repo.active_branch.tracking_branch():
                ahead = len(list(git_repo.iter_commits(
                    f'{git_repo.active_branch.tracking_branch()}..{git_repo.active_branch}'
                )))
                behind = len(list(git_repo.iter_commits(
                    f'{git_repo.active_branch}..{git_repo.active_branch.tracking_branch()}'
                )))
        except Exception:
            pass
        
        return GitStatusResponse(
            branch=current_branch,
            is_clean=is_clean,
            staged=staged,
            modified=modified,
            untracked=untracked,
            ahead=ahead,
            behind=behind,
        )
        
    except Exception as e:
        raise HTTPException(500, f"Git operation failed: {str(e)}")


@router.get("/{repo_id}/diff", response_model=GitDiffResponse)
async def get_git_diff(
    repo_id: str,
    file_path: Optional[str] = Query(None, description="Specific file to diff"),
    staged: bool = Query(False, description="Show staged changes instead of unstaged"),
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> GitDiffResponse:
    """
    Get git diff for repository.
    
    Shows uncommitted changes (or staged changes if staged=True).
    Can be filtered to a specific file.
    """
    repo_repo = RepositoryRepo(db)
    
    # Check access
    repo = await repo_repo.get_by_id(repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")
    
    has_access = await repo_repo.has_access(current_user.id, repo_id)
    if not has_access:
        raise HTTPException(403, "Access denied")
    
    _validate_is_git_repo(repo.local_path)
    
    try:
        from git import Repo as GitRepo
        
        git_repo = GitRepo(repo.local_path)
        
        # Build diff command
        if staged:
            diff = git_repo.git.diff('--cached', file_path) if file_path else git_repo.git.diff('--cached')
            diff_stat = git_repo.git.diff('--cached', '--stat', file_path) if file_path else git_repo.git.diff('--cached', '--stat')
        else:
            diff = git_repo.git.diff(file_path) if file_path else git_repo.git.diff()
            diff_stat = git_repo.git.diff('--stat', file_path) if file_path else git_repo.git.diff('--stat')
        
        if not diff:
            diff = "No changes"
        
        # Parse stats
        files_changed, insertions, deletions = _parse_diff_stats(diff_stat)
        
        return GitDiffResponse(
            diff=diff,
            files_changed=files_changed,
            insertions=insertions,
            deletions=deletions,
        )
        
    except Exception as e:
        raise HTTPException(500, f"Git operation failed: {str(e)}")


@router.get("/{repo_id}/log", response_model=GitLogResponse)
async def get_git_log(
    repo_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
    file_path: Optional[str] = Query(None, description="Filter by file path"),
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> GitLogResponse:
    """
    Get git commit history.
    
    Returns the most recent commits with pagination support.
    """
    repo_repo = RepositoryRepo(db)
    
    # Check access
    repo = await repo_repo.get_by_id(repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")
    
    has_access = await repo_repo.has_access(current_user.id, repo_id)
    if not has_access:
        raise HTTPException(403, "Access denied")
    
    _validate_is_git_repo(repo.local_path)
    
    try:
        from git import Repo as GitRepo
        
        git_repo = GitRepo(repo.local_path)
        
        # Build log command with custom format
        log_format = '%H%n%an%n%ae%n%ai%n%s%n%b---COMMIT---'
        
        log_cmd = [
            'log',
            f'--format={log_format}',
            f'--max-count={limit}',
            f'--skip={skip}',
        ]
        
        if file_path:
            log_cmd.extend(['--', file_path])
        
        log_output = git_repo.git.execute(log_cmd)
        
        commits = _parse_git_log(log_output)
        
        return GitLogResponse(
            commits=commits,
            total=len(commits),
        )
        
    except Exception as e:
        raise HTTPException(500, f"Git operation failed: {str(e)}")


@router.get("/{repo_id}/branches", response_model=GitBranchesResponse)
async def get_git_branches(
    repo_id: str,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> GitBranchesResponse:
    """
    List all git branches in repository.
    
    Shows local branches with current branch highlighted.
    """
    repo_repo = RepositoryRepo(db)
    
    # Check access
    repo = await repo_repo.get_by_id(repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")
    
    has_access = await repo_repo.has_access(current_user.id, repo_id)
    if not has_access:
        raise HTTPException(403, "Access denied")
    
    _validate_is_git_repo(repo.local_path)
    
    try:
        from git import Repo as GitRepo
        
        git_repo = GitRepo(repo.local_path)
        
        current_branch_name = git_repo.active_branch.name
        
        branches = []
        for branch in git_repo.branches:
            last_commit = branch.commit
            
            branches.append(GitBranch(
                name=branch.name,
                is_current=(branch.name == current_branch_name),
                last_commit_sha=last_commit.hexsha[:8],
                last_commit_message=last_commit.message.split('\n')[0],
            ))
        
        return GitBranchesResponse(
            branches=branches,
            current_branch=current_branch_name,
        )
        
    except Exception as e:
        raise HTTPException(500, f"Git operation failed: {str(e)}")


@router.get("/{repo_id}/show", response_model=GitShowResponse)
async def get_git_show(
    repo_id: str,
    commit_sha: str = Query(..., min_length=4, max_length=40),
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> GitShowResponse:
    """
    Show details of a specific commit.
    
    Returns commit info and diff.
    """
    repo_repo = RepositoryRepo(db)
    
    # Check access
    repo = await repo_repo.get_by_id(repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")
    
    has_access = await repo_repo.has_access(current_user.id, repo_id)
    if not has_access:
        raise HTTPException(403, "Access denied")
    
    _validate_is_git_repo(repo.local_path)
    
    try:
        from git import Repo as GitRepo
        
        git_repo = GitRepo(repo.local_path)
        
        # Get commit
        try:
            commit = git_repo.commit(commit_sha)
        except Exception:
            raise HTTPException(404, f"Commit not found: {commit_sha}")
        
        # Get diff
        diff = git_repo.git.show(commit_sha)
        
        return GitShowResponse(
            commit=GitCommit(
                sha=commit.hexsha,
                author=commit.author.name,
                email=commit.author.email,
                date=commit.authored_datetime.isoformat(),
                message=commit.message,
            ),
            diff=diff,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Git operation failed: {str(e)}")


@router.get("/{repo_id}/blame", response_model=GitBlameResponse)
async def get_git_blame(
    repo_id: str,
    file_path: str = Query(..., description="File path relative to repository root"),
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> GitBlameResponse:
    """
    Get git blame for a file.
    
    Shows who last modified each line.
    """
    repo_repo = RepositoryRepo(db)
    
    # Check access
    repo = await repo_repo.get_by_id(repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")
    
    has_access = await repo_repo.has_access(current_user.id, repo_id)
    if not has_access:
        raise HTTPException(403, "Access denied")
    
    _validate_is_git_repo(repo.local_path)
    
    try:
        from git import Repo as GitRepo
        
        git_repo = GitRepo(repo.local_path)
        
        # Check file exists
        full_path = os.path.join(repo.local_path, file_path)
        if not os.path.exists(full_path):
            raise HTTPException(404, f"File not found: {file_path}")
        
        # Get blame
        blame_output = git_repo.git.blame('--line-porcelain', file_path)
        
        lines = []
        line_number = 0
        current_sha = None
        current_author = None
        current_date = None
        
        for line in blame_output.split('\n'):
            if line.startswith('\t'):
                # This is the actual code line
                line_number += 1
                lines.append(GitBlameLine(
                    line_number=line_number,
                    content=line[1:],  # Remove leading tab
                    commit_sha=current_sha[:8] if current_sha else "",
                    author=current_author or "",
                    date=current_date or "",
                ))
            elif len(line) == 40 and line[0].isalnum():
                # This is a commit SHA (40 hex chars)
                current_sha = line.split()[0]
            elif line.startswith('author '):
                current_author = line[7:]
            elif line.startswith('author-time '):
                from datetime import datetime
                timestamp = int(line.split()[1])
                current_date = datetime.fromtimestamp(timestamp).isoformat()
        
        return GitBlameResponse(
            file_path=file_path,
            lines=lines,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Git operation failed: {str(e)}")
