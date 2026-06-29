"""
Updated tool implementations for tool-use loop.

These wrap the existing tool implementations with the new context-based interface.
"""

from __future__ import annotations

from typing import Any

from app.agents.tools.base import BaseTool as OldBaseTool
from app.agents.tools.file_tool import FileTool as OldFileTool
from app.agents.tools.search_tool import SearchTool as OldSearchTool
from app.shared.exceptions import ToolExecutionError


class BaseTool:
    """
    New base tool interface for tool-use loop.
    Simpler signature: execute(**args, context=dict)
    """

    name: str = "base_tool"
    description: str = "Base tool"
    parameters: dict = {}

    async def execute(self, context: dict, **kwargs: Any) -> Any:
        """
        Execute the tool with given arguments and context.
        
        Args:
            context: Dict with user_id, org_id, repo_id, repo_path, etc.
            **kwargs: Tool-specific arguments
        
        Returns:
            Tool-specific output (str, dict, list, etc.)
        
        Raises:
            ToolExecutionError: On execution failure
        """
        raise NotImplementedError


class FileReadTool(BaseTool):
    """Read file content from the repository."""

    name = "read_file"
    description = "Read the full content of a file in the repository"
    parameters = {
        "file_path": {
            "type": "string",
            "description": "Path to the file relative to repository root",
            "required": True,
        }
    }

    async def execute(self, context: dict, **kwargs: Any) -> str:
        file_path = kwargs.get("file_path")
        if not file_path:
            raise ToolExecutionError("file_path is required")

        repo_path = context.get("repo_path")
        if not repo_path:
            raise ToolExecutionError("No repository path in context")

        # Use the old FileTool implementation
        from app.agents.tools.base import ToolContext as OldContext
        old_context = OldContext(
            user_id=context["user_id"],
            org_id=context["org_id"],
            repo_id=context.get("repo_id"),
            conversation_id=context.get("conversation_id", ""),
            request_id=context.get("request_id", ""),
            repo_path=repo_path,
        )

        old_tool = OldFileTool()
        result = await old_tool._execute(
            old_context, operation="read", path=file_path
        )

        if not result.success:
            raise ToolExecutionError(result.error or "File read failed")

        return str(result.output)


class FileWriteTool(BaseTool):
    """Write content to a file in the repository."""

    name = "write_file"
    description = "Write or create a file in the repository"
    parameters = {
        "file_path": {
            "type": "string",
            "description": "Path to the file relative to repository root",
            "required": True,
        },
        "content": {
            "type": "string",
            "description": "Content to write to the file",
            "required": True,
        },
    }

    async def execute(self, context: dict, **kwargs: Any) -> str:
        file_path = kwargs.get("file_path")
        content = kwargs.get("content")

        if not file_path:
            raise ToolExecutionError("file_path is required")
        if content is None:
            raise ToolExecutionError("content is required")

        repo_path = context.get("repo_path")
        if not repo_path:
            raise ToolExecutionError("No repository path in context")

        from app.agents.tools.base import ToolContext as OldContext
        old_context = OldContext(
            user_id=context["user_id"],
            org_id=context["org_id"],
            repo_id=context.get("repo_id"),
            conversation_id=context.get("conversation_id", ""),
            request_id=context.get("request_id", ""),
            repo_path=repo_path,
        )

        old_tool = OldFileTool()
        result = await old_tool._execute(
            old_context, operation="write", path=file_path, content=content
        )

        if not result.success:
            raise ToolExecutionError(result.error or "File write failed")

        return str(result.output)


class SearchCodeTool(BaseTool):
    """Search for code by semantic meaning."""

    name = "search_code"
    description = "Search the codebase for code matching a semantic query"
    parameters = {
        "query": {
            "type": "string",
            "description": "Natural language description of what code to find",
            "required": True,
        },
        "top_k": {
            "type": "integer",
            "description": "Number of results to return (default: 5)",
            "required": False,
        },
    }

    async def execute(self, context: dict, **kwargs: Any) -> list[dict]:
        query = kwargs.get("query")
        if not query:
            raise ToolExecutionError("query is required")

        top_k = kwargs.get("top_k", 5)
        repo_id = context.get("repo_id")

        if not repo_id:
            raise ToolExecutionError("No repository in context")

        # Get vector store and create retriever
        from app.vector_store.chroma_client import get_chroma_store
        from app.retrieval.retriever import CodeRetriever

        try:
            vector_store = await get_chroma_store()
            retriever = CodeRetriever(vector_store)

            results = await retriever.retrieve(
                query=query,
                repo_id=repo_id,
                top_k=min(int(top_k), 10),
            )

            return [
                {
                    "file": r.chunk.file_path,
                    "lines": f"{r.chunk.start_line}-{r.chunk.end_line}",
                    "type": r.chunk.chunk_type.value,
                    "name": r.chunk.function_name or r.chunk.class_name or "",
                    "score": round(r.score, 3),
                    "content": r.chunk.content[:500]
                    + ("..." if len(r.chunk.content) > 500 else ""),
                }
                for r in results
            ]

        except Exception as e:
            raise ToolExecutionError(f"Search failed: {str(e)}")


class GitDiffTool(BaseTool):
    """Get git diff showing uncommitted changes."""

    name = "git_diff"
    description = "Show git diff of uncommitted changes in the repository"
    parameters = {
        "file_path": {
            "type": "string",
            "description": "Optional: specific file to show diff for",
            "required": False,
        }
    }

    async def execute(self, context: dict, **kwargs: Any) -> str:
        repo_path = context.get("repo_path")
        if not repo_path:
            raise ToolExecutionError("No repository path in context")

        file_path = kwargs.get("file_path")

        try:
            from git import Repo

            repo = Repo(repo_path)

            if file_path:
                # Diff for specific file
                diff = repo.git.diff("HEAD", file_path)
            else:
                # Diff for all files
                diff = repo.git.diff("HEAD")

            if not diff:
                return "No uncommitted changes found"

            return diff

        except Exception as e:
            raise ToolExecutionError(f"Git diff failed: {str(e)}")


class RunCommandTool(BaseTool):
    """Execute a shell command (read-only operations preferred)."""

    name = "run_command"
    description = "Execute a shell command in the repository directory"
    parameters = {
        "command": {
            "type": "string",
            "description": "Shell command to execute",
            "required": True,
        },
    }

    async def execute(self, context: dict, **kwargs: Any) -> str:
        command = kwargs.get("command")
        if not command:
            raise ToolExecutionError("command is required")

        repo_path = context.get("repo_path")
        if not repo_path:
            raise ToolExecutionError("No repository path in context")

        # Safety: Block dangerous commands
        dangerous = [
            "rm ",
            "del ",
            "format",
            "mkfs",
            "> /dev/",
            "dd if=",
            "shutdown",
            "reboot",
        ]
        for pattern in dangerous:
            if pattern in command.lower():
                raise ToolExecutionError(
                    f"Command blocked for safety: contains '{pattern}'"
                )

        try:
            import asyncio

            # Run command with timeout
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=repo_path,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=30.0
                )
            except asyncio.TimeoutError:
                process.kill()
                raise ToolExecutionError("Command timed out after 30 seconds")

            output = stdout.decode("utf-8", errors="replace")
            errors = stderr.decode("utf-8", errors="replace")

            if process.returncode != 0:
                return f"Command failed (exit code {process.returncode}):\n{errors}"

            return output if output else "(command completed with no output)"

        except Exception as e:
            raise ToolExecutionError(f"Command execution failed: {str(e)}")
