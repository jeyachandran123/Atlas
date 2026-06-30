"""
Files API router.

Provides REST endpoints for file operations within repositories.
All operations are scoped to repositories the user has access to.

Endpoints:
  GET    /api/v1/files/{repo_id}/tree        → list directory tree
  GET    /api/v1/files/{repo_id}/content     → read file content
  POST   /api/v1/files/{repo_id}/content     → write/create file
  DELETE /api/v1/files/{repo_id}/content     → delete file
  POST   /api/v1/files/{repo_id}/search      → search files by name
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_developer
from app.database import get_db
from app.db.models import User
from app.db.repositories import RepositoryRepo
from app.shared.exceptions import ToolExecutionError

router = APIRouter(prefix="/files", tags=["Files"])


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────────────────────


class FileTreeNode(BaseModel):
    """A node in the directory tree."""
    name: str
    path: str
    type: str  # file | directory
    size: Optional[int] = None  # bytes, only for files
    children: Optional[list[FileTreeNode]] = None  # only for directories


class FileContentResponse(BaseModel):
    """Response for file read operations."""
    path: str
    content: str
    size: int
    language: Optional[str] = None


class WriteFileRequest(BaseModel):
    """Request to write or create a file."""
    path: str = Field(..., min_length=1, max_length=2000)
    content: str = Field(..., max_length=5_000_000)  # 5MB max
    create_backup: bool = Field(default=True)


class WriteFileResponse(BaseModel):
    """Response for file write operations."""
    path: str
    size: int
    backup_path: Optional[str] = None


class FileSearchResult(BaseModel):
    """A file matching the search query."""
    path: str
    name: str
    size: int
    type: str


class FileSearchResponse(BaseModel):
    """Response for file search."""
    results: list[FileSearchResult]
    total: int
    query: str


# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────


def _get_language_from_extension(file_path: str) -> Optional[str]:
    """Detect programming language from file extension."""
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".java": "java",
        ".cs": "csharp",
        ".go": "go",
        ".rs": "rust",
        ".cpp": "cpp",
        ".c": "c",
        ".h": "c",
        ".hpp": "cpp",
        ".rb": "ruby",
        ".php": "php",
        ".swift": "swift",
        ".kt": "kotlin",
        ".scala": "scala",
        ".sh": "bash",
        ".sql": "sql",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".xml": "xml",
        ".html": "html",
        ".css": "css",
        ".md": "markdown",
    }
    
    ext = Path(file_path).suffix.lower()
    return ext_map.get(ext)


def _validate_path(repo_path: str, file_path: str) -> str:
    """
    Validate and resolve file path within repository.
    
    Protects against path traversal attacks.
    Returns absolute path if valid, raises HTTPException otherwise.
    """
    # Resolve to absolute paths
    repo_abs = Path(repo_path).resolve()
    
    # Handle both absolute and relative paths
    if os.path.isabs(file_path):
        file_abs = Path(file_path).resolve()
    else:
        file_abs = (repo_abs / file_path).resolve()
    
    # Check if file is within repo
    try:
        file_abs.relative_to(repo_abs)
    except ValueError:
        raise HTTPException(
            403,
            f"Access denied: path escapes repository boundary"
        )
    
    return str(file_abs)


def _is_binary_file(file_path: str) -> bool:
    """Check if file is binary (not text)."""
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)
            # Check for null bytes (indicator of binary)
            return b'\x00' in chunk
    except Exception:
        return False


def _build_tree(
    root_path: str,
    current_path: str,
    max_depth: int = 3,
    current_depth: int = 0,
) -> FileTreeNode:
    """Recursively build directory tree."""
    # Resolve both paths to avoid Windows short name issues
    root_path_obj = Path(root_path).resolve()
    path_obj = Path(current_path).resolve()
    
    # Calculate relative path
    try:
        rel_path = str(path_obj.relative_to(root_path_obj))
    except ValueError:
        # If relative_to fails, use the name
        rel_path = path_obj.name
    
    if path_obj.is_file():
        return FileTreeNode(
            name=path_obj.name,
            path=rel_path,
            type="file",
            size=path_obj.stat().st_size,
        )
    
    # Directory
    children = []
    if current_depth < max_depth:
        try:
            for item in sorted(path_obj.iterdir()):
                # Skip hidden files and common ignore patterns
                if item.name.startswith('.'):
                    continue
                if item.name in ['node_modules', '__pycache__', 'dist', 'build', 'target']:
                    continue
                
                children.append(
                    _build_tree(root_path, str(item), max_depth, current_depth + 1)
                )
        except PermissionError:
            pass
    
    return FileTreeNode(
        name=path_obj.name,
        path=rel_path,
        type="directory",
        children=children if children else None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{repo_id}/tree", response_model=FileTreeNode)
async def get_file_tree(
    repo_id: str,
    path: str = Query(default="", description="Subdirectory to list (relative to repo root)"),
    max_depth: int = Query(default=3, ge=1, le=5, description="Maximum depth to traverse"),
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> FileTreeNode:
    """
    Get directory tree for a repository.
    
    Returns a hierarchical structure of files and directories.
    """
    repo_repo = RepositoryRepo(db)
    
    # Check access
    repo = await repo_repo.get_by_id(repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")
    
    has_access = await repo_repo.has_access(current_user.id, repo_id)
    if not has_access:
        raise HTTPException(403, "Access denied")
    
    # Validate path
    target_path = _validate_path(repo.local_path, path or ".")
    
    if not os.path.exists(target_path):
        raise HTTPException(404, f"Path not found: {path}")
    
    # Build tree
    tree = _build_tree(repo.local_path, target_path, max_depth)
    
    return tree


@router.get("/{repo_id}/content", response_model=FileContentResponse)
async def read_file(
    repo_id: str,
    path: str = Query(..., description="File path relative to repository root"),
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> FileContentResponse:
    """
    Read file content from repository.
    
    Returns the full content of the file as text.
    Binary files are rejected.
    """
    repo_repo = RepositoryRepo(db)
    
    # Check access
    repo = await repo_repo.get_by_id(repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")
    
    has_access = await repo_repo.has_access(current_user.id, repo_id)
    if not has_access:
        raise HTTPException(403, "Access denied")
    
    # Validate path
    file_path = _validate_path(repo.local_path, path)
    
    if not os.path.exists(file_path):
        raise HTTPException(404, f"File not found: {path}")
    
    if not os.path.isfile(file_path):
        raise HTTPException(400, f"Path is not a file: {path}")
    
    # Check file size (max 5MB)
    file_size = os.path.getsize(file_path)
    if file_size > 5 * 1024 * 1024:
        raise HTTPException(400, f"File too large: {file_size} bytes (max 5MB)")
    
    # Check if binary
    if _is_binary_file(file_path):
        raise HTTPException(400, "Cannot read binary file")
    
    # Read content
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        raise HTTPException(400, "File encoding not supported (not UTF-8)")
    except Exception as e:
        raise HTTPException(500, f"Failed to read file: {str(e)}")
    
    return FileContentResponse(
        path=path,
        content=content,
        size=file_size,
        language=_get_language_from_extension(path),
    )


@router.post("/{repo_id}/content", response_model=WriteFileResponse)
async def write_file(
    repo_id: str,
    req: WriteFileRequest,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> WriteFileResponse:
    """
    Write or create a file in the repository.
    
    If the file exists and create_backup=True, a backup is created.
    Creates parent directories if needed.
    """
    repo_repo = RepositoryRepo(db)
    
    # Check access (write permission required)
    repo = await repo_repo.get_by_id(repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")
    
    has_access = await repo_repo.has_access(current_user.id, repo_id, "write")
    if not has_access:
        raise HTTPException(403, "Write access required")
    
    # Validate path
    file_path = _validate_path(repo.local_path, req.path)
    
    # Create backup if file exists
    backup_path = None
    if os.path.exists(file_path) and req.create_backup:
        import time
        timestamp = int(time.time())
        backup_path = f"{file_path}.backup.{timestamp}"
        try:
            import shutil
            shutil.copy2(file_path, backup_path)
        except Exception as e:
            raise HTTPException(500, f"Failed to create backup: {str(e)}")
    
    # Create parent directories
    parent_dir = os.path.dirname(file_path)
    if not os.path.exists(parent_dir):
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except Exception as e:
            raise HTTPException(500, f"Failed to create directory: {str(e)}")
    
    # Write file
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(req.content)
    except Exception as e:
        raise HTTPException(500, f"Failed to write file: {str(e)}")
    
    file_size = os.path.getsize(file_path)
    
    return WriteFileResponse(
        path=req.path,
        size=file_size,
        backup_path=backup_path,
    )


@router.delete("/{repo_id}/content")
async def delete_file(
    repo_id: str,
    path: str = Query(..., description="File path relative to repository root"),
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Delete a file from the repository.
    
    Requires write access.
    """
    repo_repo = RepositoryRepo(db)
    
    # Check access (write permission required)
    repo = await repo_repo.get_by_id(repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")
    
    has_access = await repo_repo.has_access(current_user.id, repo_id, "write")
    if not has_access:
        raise HTTPException(403, "Write access required")
    
    # Validate path
    file_path = _validate_path(repo.local_path, path)
    
    if not os.path.exists(file_path):
        raise HTTPException(404, f"File not found: {path}")
    
    if not os.path.isfile(file_path):
        raise HTTPException(400, f"Path is not a file: {path}")
    
    # Delete file
    try:
        os.remove(file_path)
    except Exception as e:
        raise HTTPException(500, f"Failed to delete file: {str(e)}")
    
    return {"status": "success", "message": f"File deleted: {path}"}


@router.post("/{repo_id}/search", response_model=FileSearchResponse)
async def search_files(
    repo_id: str,
    query: str = Query(..., min_length=1, max_length=200, description="File name pattern to search"),
    max_results: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
) -> FileSearchResponse:
    """
    Search for files by name pattern.
    
    Performs case-insensitive substring matching on file names.
    """
    repo_repo = RepositoryRepo(db)
    
    # Check access
    repo = await repo_repo.get_by_id(repo_id)
    if not repo:
        raise HTTPException(404, "Repository not found")
    
    has_access = await repo_repo.has_access(current_user.id, repo_id)
    if not has_access:
        raise HTTPException(403, "Access denied")
    
    # Search files
    results = []
    query_lower = query.lower()
    
    for root, dirs, files in os.walk(repo.local_path):
        # Filter out ignored directories
        dirs[:] = [d for d in dirs if d not in ['.git', 'node_modules', '__pycache__', 'dist', 'build']]
        
        for file in files:
            if query_lower in file.lower():
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, repo.local_path)
                
                try:
                    size = os.path.getsize(file_path)
                    results.append(
                        FileSearchResult(
                            path=rel_path,
                            name=file,
                            size=size,
                            type="file",
                        )
                    )
                except Exception:
                    continue
                
                if len(results) >= max_results:
                    break
        
        if len(results) >= max_results:
            break
    
    return FileSearchResponse(
        results=results,
        total=len(results),
        query=query,
    )
