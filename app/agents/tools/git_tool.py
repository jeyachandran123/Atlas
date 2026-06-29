"""
Git tool — read-only repository operations in V1.

Uses gitpython for safe, abstracted Git access.
Write operations (commit, push, branch creation) are disabled in V1
and will be added in V2 after the read-only flow is proven reliable.

Security model:
- Read-only in V1: no writes to the repository
- All operations scoped to the configured repository path
- No remote operations (no network calls from this tool)
"""

from __future__ import annotations

from typing import Any, Optional

from app.agents.tools.base import BaseTool, ToolContext, ToolResult


class GitTool(BaseTool):
    """
    Read-only Git operations.

    Operations:
      log(n)              → recent commit history
      diff(from, to)      → unified diff between refs
      blame(path, lines)  → line authorship
      branches()          → list of branches
      status()            → working directory status
      show(commit_sha)    → show a specific commit
    """

    name = "git_tool"
    description = (
        "Read-only access to Git repository history, diffs, and blame. "
        "Cannot make commits or push changes in V1."
    )

    async def _execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        operation = kwargs.get("operation", "log")
        repo_path = context.repo_path

        if not repo_path:
            return ToolResult(self.name, False, error="No repository path configured")

        try:
            import git

            repo = git.Repo(repo_path, search_parent_directories=True)
        except Exception as e:
            return ToolResult(self.name, False, error=f"Not a git repository: {e}")

        if operation == "log":
            return self._log(repo, kwargs.get("n", 20), kwargs.get("branch"))
        elif operation == "diff":
            return self._diff(repo, kwargs.get("from_ref", "HEAD~1"), kwargs.get("to_ref", "HEAD"))
        elif operation == "blame":
            return self._blame(repo, kwargs.get("path", ""), repo_path)
        elif operation == "branches":
            return self._branches(repo)
        elif operation == "status":
            return self._status(repo)
        elif operation == "show":
            return self._show(repo, kwargs.get("commit_sha", "HEAD"))
        else:
            return ToolResult(self.name, False, error=f"Unknown operation: {operation}")

    def _log(self, repo: Any, n: int = 20, branch: Optional[str] = None) -> ToolResult:
        try:
            target = branch or repo.active_branch.name
            commits = list(repo.iter_commits(target, max_count=min(n, 100)))
            output = [
                {
                    "sha": c.hexsha[:8],
                    "message": c.message.strip().split("\n")[0],
                    "author": str(c.author),
                    "date": c.committed_datetime.isoformat(),
                }
                for c in commits
            ]
            return ToolResult(self.name, True, output=output, metadata={"branch": target, "count": len(output)})
        except Exception as e:
            return ToolResult(self.name, False, error=str(e))

    def _diff(self, repo: Any, from_ref: str, to_ref: str) -> ToolResult:
        try:
            diff = repo.git.diff(from_ref, to_ref, unified=3)
            if not diff:
                diff = "No differences found."
            # Truncate very large diffs
            if len(diff) > 50_000:
                diff = diff[:50_000] + "\n... [diff truncated at 50KB]"
            return ToolResult(
                self.name, True,
                output=diff,
                metadata={"from": from_ref, "to": to_ref},
            )
        except Exception as e:
            return ToolResult(self.name, False, error=str(e))

    def _blame(self, repo: Any, file_path: str, repo_path: str) -> ToolResult:
        try:
            blame_output = repo.git.blame("--line-porcelain", file_path)
            # Parse blame into structured format
            lines = []
            current: dict = {}
            for line in blame_output.split("\n"):
                if len(line) == 41 and " " in line:  # SHA line
                    current = {"sha": line.split()[0][:8]}
                elif line.startswith("author "):
                    current["author"] = line[7:]
                elif line.startswith("summary "):
                    current["summary"] = line[8:]
                elif line.startswith("\t"):
                    current["line"] = line[1:]
                    lines.append(dict(current))

            return ToolResult(self.name, True, output=lines[:200], metadata={"file": file_path})
        except Exception as e:
            return ToolResult(self.name, False, error=str(e))

    def _branches(self, repo: Any) -> ToolResult:
        try:
            branches = [b.name for b in repo.branches]
            active = repo.active_branch.name
            return ToolResult(
                self.name, True,
                output={"branches": branches, "active": active},
            )
        except Exception as e:
            return ToolResult(self.name, False, error=str(e))

    def _status(self, repo: Any) -> ToolResult:
        try:
            modified = [item.a_path for item in repo.index.diff(None)]
            untracked = repo.untracked_files
            staged = [item.a_path for item in repo.index.diff("HEAD")]
            return ToolResult(
                self.name, True,
                output={"modified": modified, "untracked": untracked, "staged": staged},
            )
        except Exception as e:
            return ToolResult(self.name, False, error=str(e))

    def _show(self, repo: Any, commit_sha: str) -> ToolResult:
        try:
            show_output = repo.git.show(commit_sha, stat=True)
            if len(show_output) > 20_000:
                show_output = show_output[:20_000] + "\n... [truncated]"
            return ToolResult(self.name, True, output=show_output)
        except Exception as e:
            return ToolResult(self.name, False, error=str(e))
