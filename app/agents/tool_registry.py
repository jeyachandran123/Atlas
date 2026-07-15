"""
Tool registry.

Central registry for all available tools.
Tools register themselves here and can be discovered by the tool planner.
"""

from __future__ import annotations

from typing import Optional

from app.agents.tools.tool_impls import (
    BaseTool,
    FileReadTool,
    FileWriteTool,
    GitDiffTool,
    ListDirectoryTool,
    RunCommandTool,
    SearchCodeTool,
)


class ToolRegistry:
    """
    Registry of all available tools.
    
    Tools are registered at startup and can be retrieved by name.
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register all default tools."""
        # File operations
        self.register(FileReadTool())
        self.register(FileWriteTool())
        self.register(ListDirectoryTool())
        
        # Code search
        self.register(SearchCodeTool())
        
        # Git operations
        self.register(GitDiffTool())
        
        # Terminal
        self.register(RunCommandTool())

    def register(self, tool: BaseTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """List all registered tools."""
        return list(self._tools.values())

    def get_tool_descriptions(self) -> list[dict]:
        """Get descriptions of all tools for the LLM."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in self._tools.values()
        ]


# Singleton instance
_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Get the singleton tool registry instance."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
