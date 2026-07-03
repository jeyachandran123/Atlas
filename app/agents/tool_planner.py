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

TOOL_PLANNING_PROMPT = """You are a precise tool planning assistant for a senior software engineering AI.
Your job: decide the MINIMAL set of tools needed to answer the user's request.

Available tools:
1. search_code(query: str)
   - Semantic search across the indexed codebase
   - Use for: "find", "where is", "show me", "how does X work"

2. read_file(file_path: str)
   - Read full content of a specific file
   - Use when you know the exact file path needed

3. write_file(file_path: str, content: str)
   - Create or overwrite a file
   - Use when the user asks to create/modify code

4. git_diff(file_path: str [optional])
   - Show uncommitted changes
   - Use for: "what changed", "show diff", "what did I modify"

5. run_command(command: str)
   - Execute a shell command in the repo directory
   - Use for: running tests, checking versions, listing files
   - NEVER use for destructive operations

User request: {user_message}
Intent: {intent}
Repository: {repo_id}
Context already available: {has_context}
Previous tool calls this turn: {prev_tool_count}

Decision rules:
- If context already answers the request → return []
- If prev_tool_count >= 3 → return [] (avoid over-tooling)
- Only call tools that directly contribute to answering the request
- Order tools so each result can inform the next
- Prefer search_code over read_file when you don't know the exact path

Respond ONLY with a valid JSON array. No explanation, no markdown.

Examples:
[]
[{{"tool": "search_code", "args": {{"query": "authentication middleware"}}, "rationale": "Find auth implementation"}}]
[{{"tool": "read_file", "args": {{"file_path": "app/auth.py"}}, "rationale": "Read auth module"}}, {{"tool": "search_code", "args": {{"query": "JWT token validation"}}, "rationale": "Find token logic"}}]

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
