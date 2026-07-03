"""
CodingAgent — V2 Dynamic Prompt Architecture.

Uses state["system_prompt"] (composed by PromptComposer node) instead of
the old static SYSTEM_PROMPTS dict. This makes the agent prompt-agnostic:
it executes whatever system prompt the composer assembled.
"""

from __future__ import annotations

import time
from typing import Optional

from app.agents.state import AgentState
from app.config import get_settings
from app.ollama_client import OllamaClient, get_ollama_client
from app.prompts.coding import build_user_prompt

_settings = get_settings()

_PROSE_INTENTS = {"chat", "explain", "search"}


def _temperature_for_intent(intent: str, agent_mode: str = "auto") -> float:
    if agent_mode == "code" and intent not in _PROSE_INTENTS:
        return _settings.ollama_code_temperature
    return _settings.ollama_chat_temperature


class CodingAgent:
    """
    Primary agent node. Executes the LLM call using the composed system prompt.

    Called as a LangGraph node:
        state = await coding_agent.run(state)
    """

    def __init__(self, ollama: Optional[OllamaClient] = None) -> None:
        self._ollama = ollama or get_ollama_client()

    def _get_temperature(self, intent: str, agent_mode: str = "auto") -> float:
        return _temperature_for_intent(intent, agent_mode)

    def _get_model(self, agent_mode: str) -> str:
        cfg = _settings
        return {
            "code":     cfg.ollama_chat_model,
            "auto":     cfg.ollama_auto_model,
            "business": cfg.ollama_business_model,
        }.get(agent_mode, cfg.ollama_auto_model)

    async def run(self, state: AgentState) -> AgentState:
        """
        Execute the coding agent.

        Reads:  system_prompt (from PromptComposer), user_message,
                context_block, session_messages, intent, tool_results
        Writes: draft_output, tokens_used
        """
        start = time.monotonic()
        agent_mode = state.get("agent_mode", "auto")

        # Use the dynamically composed system prompt from state
        system_prompt = state.get("system_prompt") or ""
        user_prompt = build_user_prompt(
            message=state["user_message"],
            context_block=state["context_block"],
            session_messages=state["session_messages"],
            tool_results=state["tool_results"],
            review_feedback=state["review_feedback"],
            intent=state["intent"],
            agent_mode=agent_mode,
            truthfulness_warnings=state.get("truthfulness_warnings", []),
            self_corrections=state.get("self_corrections", []),
        )

        try:
            response = await self._ollama.chat(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model=self._get_model(agent_mode),
                temperature=_temperature_for_intent(state["intent"], agent_mode),
            )
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
        """Streaming version — yields text chunks."""
        agent_mode = state.get("agent_mode", "auto")
        system_prompt = state.get("system_prompt") or ""
        user_prompt = build_user_prompt(
            message=state["user_message"],
            context_block=state["context_block"],
            session_messages=state["session_messages"],
            tool_results=state["tool_results"],
            review_feedback=state["review_feedback"],
            intent=state["intent"],
            agent_mode=agent_mode,
            truthfulness_warnings=state.get("truthfulness_warnings", []),
            self_corrections=state.get("self_corrections", []),
        )
        async for chunk in self._ollama.chat_stream(
            prompt=user_prompt,
            system_prompt=system_prompt,
            model=self._get_model(agent_mode),
            temperature=_temperature_for_intent(state["intent"], agent_mode),
        ):
            yield chunk
