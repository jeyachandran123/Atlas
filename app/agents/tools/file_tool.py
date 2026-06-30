"""
File tool — read, write, and patch files in the repository.

Security model:
- All paths are normalised with os.path.realpath()
- Paths must be within the validated repo directory (no path traversal)
- Binary files are never written
- File size limits enforced on reads and writes
- All writes logged to AuditLog
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional

from app.agents.tools.base import BaseTool, ToolContext, ToolResult
from app.shared.exceptions import FileSafetyError, PathTraversalError

MAX_READ_BYTES = 5 * 1024 * 1024   # 5 MB
MAX_WRITE_BYTES = 1 * 1024 * 1024  # 1 MB


def _safe_resolve(repo_path: str, relative_path: str) -> str:
    """
    Resolve a path safely within the repo directory.
    Raises PathTraversalError if the resolved path escapes the repo root.
    """
    # Normalise the repo root
    root = os.path.realpath(repo_path)

    # Join and normalise the target path
    target = os.path.realpath(os.path.join(root, relative_path))

    # Ensure target is inside the repo
    if not target.startswith(root + os.sep) and target != root:
        raise PathTraversalError(
            f"Path '{relative_path}' would escape the repository root."
        )

    return target


def _is_binary(content: bytes, sample: int = 8192) -> bool:
    return b"\x00" in content[:sample]


class FileTool(BaseTool):
    """
    Provides file operations within a repository.

    Operations:
      read(path)                 → file content as string
      write(path, content)       → lines written
      apply_patch(path, diff)    → lines changed
      list_directory(path)       → directory tree
      search_in_file(path, q)    → matching lines
    """

    name = "file_tool"
    description = (
        "Read and write files within the current repository. "
        "Paths are relative to the repository root."
    )

    async def _execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        operation = kwargs.get("operation", "read")
        path = kwargs.get("path", "")

        if not context.repo_path:
            return ToolResult(self.name, False, error="No repository path available")

        if operation == "read":
            return await self._read(context.repo_path, path)
        elif operation == "write":
            return await self._write(context.repo_path, path, kwargs.get("content", ""))
        elif operation == "apply_patch":
            return await self._apply_patch(context.repo_path, path, kwargs.get("diff", ""))
        elif operation == "list_directory":
            return await self._list_directory(context.repo_path, path, kwargs.get("depth", 2))
        elif operation == "search_in_file":
            return await self._search_in_file(context.repo_path, path, kwargs.get("query", ""))
        else:
            return ToolResult(self.name, False, error=f"Unknown operation: {operation}")

    async def _read(self, repo_path: str, relative_path: str) -> ToolResult:
        try:
            abs_path = _safe_resolve(repo_path, relative_path)
        except PathTraversalError as e:
            return ToolResult(self.name, False, error=str(e))

        if not os.path.isfile(abs_path):
            return ToolResult(self.name, False, error=f"File not found: {relative_path}")

        size = os.path.getsize(abs_path)
        if size > MAX_READ_BYTES:
            return ToolResult(
                self.name, False,
                error=f"File too large to read ({size // 1024}KB). Max {MAX_READ_BYTES // 1024}KB."
            )

        with open(abs_path, "rb") as f:
            raw = f.read()

        if _is_binary(raw):
            return ToolResult(self.name, False, error="Cannot read binary file")

        content = raw.decode("utf-8", errors="replace")
        line_count = content.count("\n") + 1

        return ToolResult(
            self.name,
            True,
            output=content,
            metadata={"path": relative_path, "lines": line_count, "size_bytes": size},
        )

    async def _write(self, repo_path: str, relative_path: str, content: str) -> ToolResult:
        try:
            abs_path = _safe_resolve(repo_path, relative_path)
        except PathTraversalError as e:
            return ToolResult(self.name, False, error=str(e))

        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            return ToolResult(
                self.name, False,
                error=f"Content too large to write. Max {MAX_WRITE_BYTES // 1024}KB."
            )

        # Create parent directories if needed
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)

        line_count = content.count("\n") + 1
        return ToolResult(
            self.name,
            True,
            output=f"Written {line_count} lines to {relative_path}",
            metadata={"path": relative_path, "lines": line_count},
        )

    async def _apply_patch(self, repo_path: str, relative_path: str, diff: str) -> ToolResult:
        """Apply a diff patch to a file using robust diff applier."""
        try:
            abs_path = _safe_resolve(repo_path, relative_path)
        except PathTraversalError as e:
            return ToolResult(self.name, False, error=str(e))

        if not os.path.isfile(abs_path):
            return ToolResult(self.name, False, error=f"File not found: {relative_path}")

        with open(abs_path, encoding="utf-8", errors="replace") as f:
            original = f.read()

        # Use robust diff applier
        from app.agents.diff_applier import get_diff_applier
        
        applier = get_diff_applier()
        result = applier.apply(original, diff, dry_run=False)
        
        if not result.success:
            error_msg = result.error or "Unknown patch error"
            if result.details:
                error_msg += "\n" + "\n".join(result.details)
            return ToolResult(self.name, False, error=f"Patch failed: {error_msg}")

        # Write patched content
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(result.patched_content)

        original_lines = original.count("\n") + 1
        patched_lines = result.patched_content.count("\n") + 1
        changed = abs(patched_lines - original_lines)
        
        # Build success message
        success_msg = f"Patch applied to {relative_path}. Lines changed: ~{changed}"
        if result.strategy_used:
            success_msg += f" (strategy: {result.strategy_used.value})"
        if result.details:
            success_msg += "\n" + "\n".join(result.details)

        return ToolResult(
            self.name,
            True,
            output=success_msg,
            metadata={
                "path": relative_path,
                "original_lines": original_lines,
                "new_lines": patched_lines,
                "strategy": result.strategy_used.value if result.strategy_used else None,
                "hunks_applied": result.hunks_applied,
            },
        )

    async def _list_directory(self, repo_path: str, relative_path: str, depth: int = 2) -> ToolResult:
        try:
            abs_path = _safe_resolve(repo_path, relative_path or ".")
        except PathTraversalError as e:
            return ToolResult(self.name, False, error=str(e))

        if not os.path.isdir(abs_path):
            return ToolResult(self.name, False, error=f"Directory not found: {relative_path}")

        tree = self._build_tree(abs_path, repo_path, max_depth=depth)
        return ToolResult(
            self.name, True,
            output=tree,
            metadata={"path": relative_path, "depth": depth},
        )

    async def _search_in_file(self, repo_path: str, relative_path: str, query: str) -> ToolResult:
        read_result = await self._read(repo_path, relative_path)
        if not read_result.success:
            return read_result

        content = str(read_result.output)
        lines = content.split("\n")
        matches = []

        pattern = re.compile(re.escape(query), re.IGNORECASE)
        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                # Include 1 line of context around each match
                context_start = max(0, i - 2)
                context_end = min(len(lines), i + 1)
                context = "\n".join(f"{j+1}: {lines[j]}" for j in range(context_start, context_end))
                matches.append({"line": i, "content": line.strip(), "context": context})

        return ToolResult(
            self.name, True,
            output=matches,
            metadata={"path": relative_path, "query": query, "match_count": len(matches)},
        )

    @staticmethod
    def _build_tree(abs_path: str, repo_root: str, max_depth: int, current_depth: int = 0) -> str:
        """Build a simple text directory tree."""
        if current_depth >= max_depth:
            return ""

        lines = []
        indent = "  " * current_depth

        try:
            entries = sorted(os.scandir(abs_path), key=lambda e: (not e.is_dir(), e.name))
        except PermissionError:
            return ""

        skip = {".git", "__pycache__", "node_modules", ".venv", "venv"}
        for entry in entries:
            if entry.name in skip:
                continue
            if entry.is_dir():
                lines.append(f"{indent}{entry.name}/")
                sub = FileTool._build_tree(
                    entry.path, repo_root, max_depth, current_depth + 1
                )
                if sub:
                    lines.append(sub)
            else:
                lines.append(f"{indent}{entry.name}")

        return "\n".join(lines)


