"""
User prompt builder — V3 Prompt Intelligence Architecture.

build_user_prompt() assembles the user-turn message sent to the LLM.
The system prompt is built by DynamicPromptComposer (which uses PromptIntelligenceEngine).

This file handles the USER prompt only:
  - Codebase context (from ChromaDB)
  - Conversation history (filtered by PromptIntelligenceEngine, not raw)
  - Tool results
  - Review feedback
  - Truthfulness notes
  - The user's request (clean, no template injection)
"""

from __future__ import annotations

from app.prompts.enhancer import enhance_user_message
from app.shared.schemas import ToolResult


def build_user_prompt(
    message: str,
    context_block: str,
    session_messages: list[dict],
    tool_results: list[ToolResult],
    review_feedback: str = "",
    intent: str = "chat",
    agent_mode: str = "auto",
    truthfulness_warnings: list[str] | None = None,
    self_corrections: list[str] | None = None,
) -> str:
    """
    Build the user-turn prompt for the LLM.

    Structure:
      [CONTEXT]           Retrieved code chunks from ChromaDB
      [CONVERSATION]      Filtered conversation turns (resolved by PromptIntelligenceEngine)
      [TOOL RESULTS]      Results from tools called this turn
      [REVIEW FEEDBACK]   Issues from ReviewAgent (revision passes only)
      [TRUTHFULNESS]      Warnings and self-corrections (if any)
      [REQUEST]           The user's message (clean pass-through)
    """
    parts: list[str] = []

    # 1. Code context
    if context_block and context_block != "No relevant code context found.":
        parts.append(f"### CODEBASE CONTEXT\n{context_block}")

    # 2. Conversation history
    # session_messages here are already filtered by the PromptIntelligenceEngine
    # via the orchestrator's load_memory_node + context resolver.
    if session_messages:
        history_parts = []
        prev_mode = None
        for msg in session_messages[-6:]:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            mode = msg.get("agent_mode", "auto")
            if not content:
                continue
            if mode != prev_mode:
                history_parts.append(f"[Mode: {mode.upper()}]")
                prev_mode = mode
            history_parts.append(f"{role}: {content}")
        if history_parts:
            parts.append("### CONVERSATION HISTORY\n" + "\n\n".join(history_parts))

    # 3. Tool results
    if tool_results:
        tool_parts = []
        for result in tool_results:
            status = "SUCCESS" if result.success else "FAILED"
            output = str(result.output or result.error or "")[:2000]
            tool_parts.append(f"Tool: {result.tool_name} [{status}]\n{output}")
        parts.append("### TOOL RESULTS\n" + "\n\n".join(tool_parts))

    # 4. Review feedback
    if review_feedback:
        parts.append(
            "### REVIEW FEEDBACK\n"
            "A code review identified these issues — address ALL of them:\n"
            f"{review_feedback}"
        )

    # 5. Truthfulness warnings
    warnings = truthfulness_warnings or []
    corrections = self_corrections or []
    if warnings or corrections:
        truth_parts = []
        if corrections:
            truth_parts.append("CORRECTIONS REQUIRED:\n" + "\n".join(f"- {c}" for c in corrections))
        if warnings:
            truth_parts.append("WARNINGS:\n" + "\n".join(f"- {w}" for w in warnings))
        parts.append("### TRUTHFULNESS NOTES\n" + "\n\n".join(truth_parts))

    # 6. User request — clean pass-through (no template injection)
    enhanced = enhance_user_message(message, intent, agent_mode)
    parts.append(f"### REQUEST\n{enhanced}")

    return "\n\n".join(parts)


# Backward-compatibility alias
build_coding_prompt = build_user_prompt


def build_system_prompt(intent: str, agent_mode: str = "auto") -> str:
    """Backward-compatibility shim."""
    from app.prompts.composer import get_composer
    fake_state = {"user_message": "", "intent": intent, "agent_mode": agent_mode}
    return get_composer().compose(fake_state)  # type: ignore[arg-type]
