"""
CodingAgent — the primary V1 agent.

Handles: code generation, bug fixing, refactoring, explanation, test generation.
All these tasks use the same LLM with different prompt templates.

Why one agent for all these tasks:
Modern instruction-following models (qwen2.5-coder, deepseek-coder) handle
all these task types well with appropriate prompts. Creating separate agents
for "generate" vs "fix" vs "explain" would add coordination overhead without
measurable quality improvement. V1 uses one agent; we split only when evidence
shows a specific task type needs specialised handling.
"""

from __future__ import annotations

import time
from typing import Optional

from app.agents.state import AgentState
from app.ollama_client import OllamaClient, get_ollama_client
from app.prompts.coding import build_coding_prompt, build_system_prompt
from app.shared.schemas import ToolResult


class CodingAgent:
    """
    The primary coding agent. Handles all code-related tasks in V1.

    Called as a LangGraph node:
        state = await coding_agent.run(state)
    """

    def __init__(self, ollama: Optional[OllamaClient] = None) -> None:
        self._ollama = ollama or get_ollama_client()

    async def run(self, state: AgentState) -> AgentState:
        """
        Execute the coding agent.

        Reads: user_message, context_block, session_messages, intent, tool_results
        Writes: draft_output, tokens_used
        """
        start = time.monotonic()

        system_prompt = build_system_prompt(state["intent"])
        user_prompt = build_coding_prompt(
            message=state["user_message"],
            context_block=state["context_block"],
            session_messages=state["session_messages"],
            tool_results=state["tool_results"],
            review_feedback=state["review_feedback"],
            intent=state["intent"],
        )

        try:
            response = await self._ollama.chat(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.1,  # Low temperature for code: deterministic, accurate
            )

            latency_ms = int((time.monotonic() - start) * 1000)

            # Rough token estimate
            tokens = (len(user_prompt) + len(response)) // 4

            return {
                **state,
                "draft_output": response,
                "tokens_used": state["tokens_used"] + tokens,
            }

        except Exception as e:
            return {
                **state,
                "error": f"CodingAgent failed: {str(e)}",
                "draft_output": "",
            }

    async def stream(self, state: AgentState):
        """
        Streaming version of run(). Yields text chunks.
        Used by the chat endpoint for real-time response streaming.
        """
        system_prompt = build_system_prompt(state["intent"])
        user_prompt = build_coding_prompt(
            message=state["user_message"],
            context_block=state["context_block"],
            session_messages=state["session_messages"],
            tool_results=state["tool_results"],
            review_feedback=state["review_feedback"],
            intent=state["intent"],
        )

        async for chunk in self._ollama.chat_stream(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.1,
        ):
            yield chunk
