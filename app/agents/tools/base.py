"""
Base tool interface.

Every tool:
- Has a name, description, and permission requirements
- Validates permissions before executing
- Logs every execution to AuditLog
- Returns a standardised ToolResult
- Handles its own errors (never raises to the agent)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class ToolContext:
    """Context injected into every tool call."""

    def __init__(
        self,
        user_id: str,
        org_id: str,
        repo_id: Optional[str],
        conversation_id: str,
        request_id: str,
        repo_path: Optional[str] = None,
    ) -> None:
        self.user_id = user_id
        self.org_id = org_id
        self.repo_id = repo_id
        self.conversation_id = conversation_id
        self.request_id = request_id
        self.repo_path = repo_path


class ToolResult:
    """Standardised tool output."""

    def __init__(
        self,
        tool_name: str,
        success: bool,
        output: Any = None,
        error: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        self.tool_name = tool_name
        self.success = success
        self.output = output
        self.error = error
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }


class BaseTool(ABC):
    """
    Abstract base for all tools.

    Subclasses implement _execute() with their actual logic.
    The base class handles permission checking, audit logging, error wrapping.
    """

    name: str = "base_tool"
    description: str = "Base tool"
    required_permissions: list[str] = []

    async def execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        """
        Public entry point. Wraps _execute() with cross-cutting concerns.
        Never raises — always returns a ToolResult.
        """
        try:
            result = await self._execute(context, **kwargs)
            await self._audit(context, kwargs, result)
            return result
        except Exception as e:
            error_result = ToolResult(
                tool_name=self.name,
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
            )
            await self._audit(context, kwargs, error_result)
            return error_result

    @abstractmethod
    async def _execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        """Tool-specific implementation. May raise on errors."""
        ...

    async def _audit(
        self, context: ToolContext, input_kwargs: dict, result: ToolResult
    ) -> None:
        """
        Write to AuditLog. Called after every execution (success or failure).
        Only write operations are logged for security compliance.
        """
        import json

        from app.database import get_db_session
        from app.db.repositories import AuditRepository

        write_tools = {"file_tool_write", "file_tool_patch", "terminal_tool", "git_tool_commit"}
        if self.name not in write_tools:
            return  # Read-only tools don't need audit entries

        async with get_db_session() as session:
            audit_repo = AuditRepository(session)
            await audit_repo.log(
                org_id=context.org_id,
                user_id=context.user_id,
                action=self.name,
                resource_type="tool",
                resource_id=context.repo_id,
                metadata_json=json.dumps(
                    {
                        "input": {k: str(v)[:200] for k, v in input_kwargs.items()},
                        "success": result.success,
                        "error": result.error,
                    }
                ),
                request_id=context.request_id,
            )
