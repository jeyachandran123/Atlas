"""
Repository scanner.

Walks the file tree, applies .gitignore rules, computes SHA256 hashes,
and determines which files need (re-)indexing based on hash comparison.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import get_settings

cfg = get_settings()

# File extensions we know how to chunk
SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
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
    ".sql": "sql",
    ".sh": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".md": "markdown",
    ".rst": "rst",
}

# Directories always skipped regardless of .gitignore
ALWAYS_SKIP_DIRS = {
    ".git",
    ".svn",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".env",
    "env",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "target",  # Rust/Maven
    ".gradle",
    ".idea",
    ".vscode",
    "vendor",  # Go/PHP
}


@dataclass
class FileRecord:
    """Represents a file discovered during scanning."""

    path: str  # absolute path
    relative_path: str  # relative to repo root
    language: str
    file_hash: str
    size_bytes: int
    is_new: bool  # True if not in IndexedFiles, or hash changed


def _compute_sha256(path: str) -> str:
    """Compute SHA256 hash of a file's content."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_binary(content_or_path, sample: int = 8192) -> bool:
    """Detect binary files by looking for null bytes in the first 8KB.
    
    Accepts either raw bytes or a file path string.
    """
    if isinstance(content_or_path, (bytes, bytearray)):
        return b"\x00" in content_or_path[:sample]
    # It's a file path
    try:
        with open(content_or_path, "rb") as f:
            chunk = f.read(sample)
        return b"\x00" in chunk
    except OSError:
        return True


def _load_gitignore_patterns(repo_path: str) -> set[str]:
    """
    Load patterns from .gitignore in the repo root.
    Returns a set of patterns (simplified — not full gitignore spec).
    For production-quality gitignore parsing, use the `gitpython` library.
    """
    gitignore_path = os.path.join(repo_path, ".gitignore")
    patterns: set[str] = set()

    if not os.path.exists(gitignore_path):
        return patterns

    with open(gitignore_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                # Remove trailing slashes for directory patterns
                patterns.add(line.rstrip("/"))

    return patterns


def _matches_pattern(name: str, patterns: set[str]) -> bool:
    """Check if a file/directory name matches any gitignore pattern."""
    import fnmatch

    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
        if fnmatch.fnmatch(name, f"*/{pattern}"):
            return True
    return False


class RepositoryScanner:
    """
    Scans a repository and returns a list of FileRecords.

    Skips:
    - Binary files
    - Files larger than max_file_size_mb
    - Files matching .gitignore patterns
    - Files in always-skip directories
    - Unsupported extensions

    Uses SHA256 hashing to detect file changes for incremental indexing.
    """

    def __init__(
        self,
        repo_path: str,
        existing_hashes: Optional[dict[str, str]] = None,
        max_file_size_mb: Optional[int] = None,
    ) -> None:
        """
        Args:
            repo_path: Absolute path to the repository root.
            existing_hashes: Dict of {relative_path: sha256_hash} from IndexedFiles.
                             If provided, only new/changed files are marked is_new=True.
            max_file_size_mb: Maximum file size to index. Defaults to config value.
        """
        self.repo_path = os.path.realpath(repo_path)
        self.existing_hashes = existing_hashes or {}
        self.max_file_size_bytes = (max_file_size_mb or cfg.index_max_file_size_mb) * 1024 * 1024
        self.skip_patterns = cfg.index_skip_patterns_list
        self._gitignore_patterns: set[str] = set()

    def scan(self) -> list[FileRecord]:
        """
        Walk the repository and return all indexable files.
        Returns ALL files (both new and unchanged) so callers can
        track which files still exist (for deletion detection).
        """
        self._gitignore_patterns = _load_gitignore_patterns(self.repo_path)
        records: list[FileRecord] = []

        for dirpath, dirnames, filenames in os.walk(self.repo_path, topdown=True):
            # Prune directories in-place (modifies dirnames to control recursion)
            dirnames[:] = [
                d
                for d in dirnames
                if not self._should_skip_dir(d, dirpath)
            ]

            for filename in filenames:
                record = self._process_file(dirpath, filename)
                if record is not None:
                    records.append(record)

        return records

    def scan_changed_only(self) -> list[FileRecord]:
        """Return only new or changed files (is_new=True). Faster for incremental indexing."""
        return [r for r in self.scan() if r.is_new]

    def _should_skip_dir(self, dirname: str, parent: str) -> bool:
        if dirname in ALWAYS_SKIP_DIRS:
            return True
        if _matches_pattern(dirname, self._gitignore_patterns):
            return True
        for pattern in self.skip_patterns:
            if dirname == pattern or pattern in dirname:
                return True
        return False

    def _process_file(self, dirpath: str, filename: str) -> Optional[FileRecord]:
        # Check extension
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return None

        abs_path = os.path.join(dirpath, filename)
        rel_path = os.path.relpath(abs_path, self.repo_path)

        # Check gitignore
        if _matches_pattern(rel_path, self._gitignore_patterns):
            return None
        if _matches_pattern(filename, self._gitignore_patterns):
            return None

        # Check size
        try:
            size = os.path.getsize(abs_path)
        except OSError:
            return None

        if size > self.max_file_size_bytes:
            return None
        if size == 0:
            return None

        # Check binary
        if _is_binary(abs_path):
            return None

        # Compute hash
        try:
            file_hash = _compute_sha256(abs_path)
        except OSError:
            return None

        # Determine if new/changed
        existing_hash = self.existing_hashes.get(rel_path)
        is_new = existing_hash != file_hash

        return FileRecord(
            path=abs_path,
            relative_path=rel_path,
            language=SUPPORTED_EXTENSIONS[ext],
            file_hash=file_hash,
            size_bytes=size,
            is_new=is_new,
        )
