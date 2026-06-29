"""
Tool executor.

Executes ToolCall objects using the registered tools.
Handles errors gracefully and returns standardized ToolResult objects.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from loguru import logger

from app.agents.tool_registry import get_tool_registry
from app.shared.exceptions import ToolExecutionError
from app.shared.schemas import ToolCall, ToolResult


class ToolExecutor:
    """
    Executes tool calls and returns results.
    
    Design:
    - Async execution (tools can do I/O)
    - Error isolation (one tool failure doesn't crash the pipeline)
    - Timeout protection (tools must complete within limit)
    - Audit logging (all tool executions are logged)
    """

    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds
        self._registry = get_tool_registry()

    async def execute(self, tool_call: ToolCall, context: dict) -> ToolResult:
        """
        Execute a single tool call.
        
        Args:
            tool_call: The tool to execute with its arguments
            context: Additional context (user_id, org_id, repo_id, etc.)
        
        Returns:
            ToolResult with success/failure and output/error
        """
        logger.info(f"Executing tool: {tool_call.tool_name} with args: {tool_call.args}")

        try:
            # Get tool from registry
            tool = self._registry.get(tool_call.tool_name)
            if tool is None:
                return ToolResult(
                    tool_name=tool_call.tool_name,
                    success=False,
                    error=f"Tool '{tool_call.tool_name}' not found in registry",
                )

            # Execute with timeout
            result = await asyncio.wait_for(
                tool.execute(**tool_call.args, context=context),
                timeout=self.timeout_seconds,
            )

            logger.info(f"Tool {tool_call.tool_name} completed successfully")
            
            return ToolResult(
                tool_name=tool_call.tool_name,
                success=True,
                output=result,
                metadata={"rationale": tool_call.rationale},
            )

        except asyncio.TimeoutError:
            error_msg = f"Tool execution timed out after {self.timeout_seconds}s"
            logger.error(f"{error_msg}: {tool_call.tool_name}")
            return ToolResult(
                tool_name=tool_call.tool_name,
                success=False,
                error=error_msg,
            )

        except ToolExecutionError as e:
            logger.error(f"Tool execution failed: {tool_call.tool_name} - {e}")
            return ToolResult(
                tool_name=tool_call.tool_name,
                success=False,
                error=str(e),
            )

        except Exception as e:
            logger.exception(f"Unexpected error executing tool: {tool_call.tool_name}")
            return ToolResult(
                tool_name=tool_call.tool_name,
                success=False,
                error=f"Unexpected error: {str(e)}",
            )

    async def execute_batch(
        self, tool_calls: list[ToolCall], context: dict
    ) -> list[ToolResult]:
        """
        Execute multiple tool calls sequentially.
        
        Sequential execution allows later tools to use results from earlier ones.
        For parallel execution, use execute_parallel().
        """
        results = []
        for tool_call in tool_calls:
            result = await self.execute(tool_call, context)
            results.append(result)
            
            # If a critical tool fails, we might want to stop
            # For now, continue executing all tools
        
        return results

    async def execute_parallel(
        self, tool_calls: list[ToolCall], context: dict
    ) -> list[ToolResult]:
        """
        Execute multiple tool calls in parallel.
        
        Use this when tools are independent and don't need each other's results.
        """
        tasks = [self.execute(call, context) for call in tool_calls]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results


# Singleton instance
_executor: ToolExecutor | None = None


def get_tool_executor() -> ToolExecutor:
    """Get the singleton tool executor instance."""
    global _executor
    if _executor is None:
        _executor = ToolExecutor()
    return _executor
