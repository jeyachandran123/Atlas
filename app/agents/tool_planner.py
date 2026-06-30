"""
Tool planning agent.

Analyzes user requests and decides which tools to call.
Uses a lightweight LLM call to generate structured tool calls.
"""

from __future__ import annotations

import json
from typing import Optional

from app.agents.state import AgentState
from app.ollama_client import OllamaClient, get_ollama_client
from app.shared.schemas import ToolCall

TOOL_PLANNING_PROMPT = """You are a tool planning assistant. Your job is to decide which tools to call based on the user's request.

Available tools:
1. search_code(query: str) -> list[CodeChunk]
   - Search for code by semantic meaning
   - Use when user asks "find", "where is", "show me"
   
2. read_file(file_path: str) -> str
   - Read the full content of a file
   - Use when user asks to see specific files
   
3. write_file(file_path: str, content: str, create_backup: bool = True) -> bool
   - Write or modify a file
   - Use when user asks to create/modify code
   
4. git_diff(repo_path: str, file_path: Optional[str] = None) -> str
   - Get git diff showing uncommitted changes
   - Use when user asks "what changed", "show diff"
   
5. run_command(command: str, cwd: str) -> str
   - Execute a shell command (read-only operations preferred)
   - Use for: running tests, checking versions, listing files

User request: {user_message}

Current context summary:
- Intent: {intent}
- Repository ID: {repo_id}
- Context available: {has_context}
- Previous tool results: {prev_tool_count}

Instructions:
1. If the user's request can be answered with existing context, return []
2. If tools are needed, return a JSON array of tool calls
3. Order matters - tools execute sequentially
4. Keep tool calls minimal - only what's necessary

Respond ONLY with valid JSON array. Examples:

[]

[{{"tool": "search_code", "args": {{"query": "authentication function"}}, "rationale": "Need to find auth code"}}]

[{{"tool": "read_file", "args": {{"file_path": "app/main.py"}}, "rationale": "User asked to see main.py"}}, {{"tool": "search_code", "args": {{"query": "database connection"}}, "rationale": "Find DB setup code"}}]

Your response:"""


class ToolPlanner:
    """
    Decides which tools to call based on user request and current state.
    """

    def __init__(self, ollama: Optional[OllamaClient] = None) -> None:
        self._ollama = ollama or get_ollama_client()

    async def plan(self, state: AgentState) -> list[ToolCall]:
        """
        Analyze the state and return a list of tool calls to execute.
        Returns empty list if no tools needed.
        """
        # Don't plan tools if we're past max steps
        if state["current_step"] >= state["max_steps"]:
            return []

        # Build the prompt
        prompt = TOOL_PLANNING_PROMPT.format(
            user_message=state["user_message"],
            intent=state["intent"],
            repo_id=state.get("repo_id", "None"),
            has_context=bool(state["context_block"]),
            prev_tool_count=len(state["tool_results"]),
        )

        try:
            # Get LLM response
            response = await self._ollama.chat(
                prompt=prompt,
                system_prompt="You are a precise tool planning assistant. Respond only with valid JSON.",
                temperature=0.0,  # Deterministic for tool planning
            )

            # Parse JSON response
            tool_calls = self._parse_tool_calls(response)
            return tool_calls

        except Exception as e:
            # If planning fails, return empty list (agent can still respond with context)
            from loguru import logger
            logger.warning(f"Tool planning failed: {e}")
            return []

    def _parse_tool_calls(self, response: str) -> list[ToolCall]:
        """Parse LLM response into ToolCall objects using structured output."""
        # Clean response (remove markdown code blocks if present)
        cleaned = response.strip()
        if cleaned.startswith("```"):
            # Extract content between ``` markers
            lines = cleaned.split("\n")
            # Handle both ```json and ``` markers
            start_idx = 1
            end_idx = -1
            if len(lines) > 2:
                cleaned = "\n".join(lines[start_idx:end_idx])
            else:
                cleaned = cleaned.strip("`")

        # Remove json prefix if present
        cleaned = cleaned.strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

        try:
            parsed = json.loads(cleaned)
            
            if not isinstance(parsed, list):
                return []

            tool_calls = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                
                tool_name = item.get("tool")
                args = item.get("args", {})
                rationale = item.get("rationale")

                if tool_name and isinstance(args, dict):
                    tool_calls.append(
                        ToolCall(
                            tool_name=tool_name,
                            args=args,
                            rationale=rationale,
                        )
                    )

            return tool_calls

        except json.JSONDecodeError as e:
            # If JSON parsing fails, log and return empty list
            from loguru import logger
            logger.warning(f"Failed to parse tool calls JSON: {e}. Response: {cleaned[:200]}")
            return []


# Singleton instance
_planner: ToolPlanner | None = None


def get_tool_planner() -> ToolPlanner:
    """Get the singleton tool planner instance."""
    global _planner
    if _planner is None:
        _planner = ToolPlanner()
    return _planner
