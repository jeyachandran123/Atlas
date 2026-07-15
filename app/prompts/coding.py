"""
User prompt builder — V3 Execution Pipeline.

build_user_prompt() assembles the user-turn message sent to the LLM.

V3 changes:
  - Accepts rewritten_query (enriched by QueryRewriter) as the primary message
  - raw_message is used only for safety guards (adult content, mode guards)
  - Removes enhance_user_message() from the prompt layer — safety guards
    are applied here directly, enrichment is owned by QueryRewriter
  - execution_plan_summary injected when present (from ExecutionPlanner)

Structure:
  [CODEBASE CONTEXT]    Retrieved code chunks from ChromaDB
  [CONVERSATION]        Filtered conversation turns (resolved by ContextResolutionEngine)
  [TOOL RESULTS]        Results from tools called this turn
  [REVIEW FEEDBACK]     Issues from ReviewAgent (revision passes only)
  [REQUEST]             The enriched query (or raw message if no enrichment)
"""

from __future__ import annotations

from app.intelligence.prompting.enhancer_bridge import (
    _is_adult_content,
    _is_non_code_topic,
    _is_off_topic_for_business,
)
from app.shared.schemas import ToolResult


def build_user_prompt(
    message: str,
    context_block: str,
    session_messages: list[dict],
    tool_results: list[ToolResult],
    review_feedback: str = "",
    intent: str = "chat",
    agent_mode: str = "auto",
    raw_message: str = "",
    execution_plan_summary: str = "",
    repo_file_tree: str = "",
    # Legacy params kept for backward compat — no longer used for enrichment
    truthfulness_warnings: list[str] | None = None,
    self_corrections: list[str] | None = None,
) -> str:
    """
    Build the user-turn prompt for the LLM.

    Args:
        message: The enriched query from QueryRewriter (or raw message if no enrichment).
        raw_message: The original user message — used only for safety guards.
        context_block: Retrieved code chunks from ChromaDB.
        session_messages: Filtered conversation turns from ContextResolutionEngine.
        tool_results: Results from tools executed this turn.
        review_feedback: Issues from ReviewAgent (revision passes only).
        intent: Detected intent string.
        agent_mode: "auto" | "code" | "business".
        execution_plan_summary: Human-readable plan from ExecutionPlanner.
    """
    # Safety guards operate on the raw message, not the enriched query
    guard_target = raw_message.strip() if raw_message else message.strip()

    # 18+ guard (all modes)
    if _is_adult_content(guard_target):
        return (
            "I'm not able to help with that type of content. "
            "Please ask me something else — I'm happy to help with "
            "coding, business questions, or general topics."
        )

    # Code mode: refuse non-code topics
    if agent_mode == "code" and _is_non_code_topic(guard_target):
        return (
            "I'm in **Code mode**, which is focused on programming and software engineering.\n\n"
            "Your question appears to be about a non-coding topic. Please switch to:\n"
            "- **Auto mode** — for general questions, pop culture, history, science, etc.\n"
            "- **Business mode** — for business operations and ERP/POS/hotel systems\n\n"
            "Is there a coding question I can help you with?"
        )

    # Business mode: redirect off-topic queries
    if agent_mode == "business" and _is_off_topic_for_business(guard_target):
        return (
            "I'm in Business mode, which focuses on hotel management, ERP, POS, "
            "stock management, and business operations.\n\n"
            "Your question appears to be off-topic for this mode. Please switch to:\n"
            "- **Auto mode** — for general questions, history, science, pop culture, etc.\n"
            "- **Code mode** — for programming and technical implementation\n\n"
            "Is there a business operations question I can help you with instead?"
        )

    parts: list[str] = []

    # 1. Repo file tree (injected when repo is selected — gives AI accurate structure)
    if repo_file_tree:
        parts.append(f"### REPOSITORY FILE TREE\n{repo_file_tree}")

    # 2. Code context
    if context_block and context_block != "No relevant code context found.":
        parts.append(f"### CODEBASE CONTEXT\n{context_block}")

    # 2. Conversation history (already filtered by ContextResolutionEngine)
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

    # 4. Review feedback (revision passes only)
    if review_feedback:
        parts.append(
            "### REVIEW FEEDBACK\n"
            "A code review identified these issues — address ALL of them:\n"
            f"{review_feedback}"
        )

    # 5. Execution plan (when present — helps LLM follow the backend's plan)
    if execution_plan_summary:
        parts.append(f"### EXECUTION PLAN\n{execution_plan_summary}")

    # 6. The request — use enriched query; fall back to raw message
    final_message = message.strip() if message.strip() else guard_target
    parts.append(f"### REQUEST\n{final_message}")

    return "\n\n".join(parts)


# Backward-compatibility alias
build_coding_prompt = build_user_prompt


def build_system_prompt(intent: str, agent_mode: str = "auto") -> str:
    """Backward-compatibility shim."""
    from app.intelligence.prompt.composer import get_dynamic_prompt_composer
    from app.intelligence.models import (
        IntelligenceContext, IntentAnalysis, DetectedIntent,
        Intent, ComplexityAnalysis, Complexity, ResponseStrategy,
        ConversationAnalysis, ConversationTurn, PolicyResult, PolicyDecision,
        Persona,
    )
    # Minimal context for shim usage
    _intent_map = {
        "code": Intent.CODING, "fix": Intent.DEBUGGING, "chat": Intent.GENERAL_CHAT,
        "explain": Intent.LEARNING, "test": Intent.TESTING, "search": Intent.REPOSITORY_QUESTION,
    }
    intel = _intent_map.get(intent, Intent.GENERAL_CHAT)
    ctx = IntelligenceContext(
        user_message="",
        conversation_id="",
        user_id="",
        org_id="",
        repo_id=None,
        agent_mode=agent_mode,
        intent_analysis=IntentAnalysis(
            primary=DetectedIntent(intel, 0.9, []),
            raw_message="",
        ),
        complexity=ComplexityAnalysis(
            level=Complexity.SIMPLE,
            expected_response_length="medium",
            reasoning_depth="moderate",
            estimated_tool_calls=0,
            estimated_context_tokens=0,
            expected_token_budget=2000,
            response_strategy_hint=ResponseStrategy.DIRECT_ANSWER,
        ),
        conversation=ConversationAnalysis(
            turn_type=ConversationTurn.NEW_TOPIC,
            topic_summary="",
            user_goal="",
            is_continuation=False,
            referenced_prior_turn=False,
        ),
        policy=PolicyResult(decision=PolicyDecision.ALLOW),
        persona=Persona.SENIOR_ENGINEER,
        strategy=ResponseStrategy.DIRECT_ANSWER,
    )
    prompt, _ = get_dynamic_prompt_composer().compose(ctx)
    return prompt
