"""
LangGraph agent state.

AgentState is the single shared object passed through every node
in the LangGraph StateGraph. Agents read from it and write to it.
They never call each other directly.

Design: TypedDict (not Pydantic) because LangGraph uses dict-based state.
Pydantic schemas (schemas.py) are used at the API boundary.
"""

from __future__ import annotations

from typing import Annotated, Optional

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.shared.schemas import SearchResult, ToolCall, ToolResult


class AgentState(TypedDict):
    """
    State shared across all nodes in the LangGraph graph.

    Fields are grouped by lifecycle:
    - Input: set at graph entry, never modified
    - Context: populated by retrieval before agent runs
    - Execution: modified by agents as they work
    - Output: set at terminal node, returned to caller
    - Telemetry: for observability
    """

    # ── Input (set once at graph entry) ──────────────────────────────────────
    user_message: str
    conversation_id: str
    user_id: str
    org_id: str
    repo_id: Optional[str]
    request_id: str

    # ── Context (populated by retrieval node) ─────────────────────────────────
    code_context: list[SearchResult]
    session_messages: list[dict]  # last N conversation turns
    context_block: str  # formatted context_builder output

    # ── Routing ───────────────────────────────────────────────────────────────
    intent: str  # "code" | "review" | "explain" | "search" | "chat"

    # ── Execution (modified by agents) ────────────────────────────────────────
    tool_calls: list[ToolCall]  # Planned tool calls from LLM
    tool_results: list[ToolResult]  # Results from executed tools
    current_step: int  # Current iteration in tool loop
    max_steps: int  # Maximum iterations to prevent infinite loops
    draft_output: str
    revision_count: int
    review_feedback: str

    # ── Output (set at terminal node) ─────────────────────────────────────────
    final_response: str
    files_modified: list[str]
    context_chunks_used: int
    tokens_used: int
    error: Optional[str]


def initial_state(
    user_message: str,
    conversation_id: str,
    user_id: str,
    org_id: str,
    request_id: str,
    repo_id: Optional[str] = None,
) -> AgentState:
    """Create a fresh AgentState with all required defaults."""
    return AgentState(
        user_message=user_message,
        conversation_id=conversation_id,
        user_id=user_id,
        org_id=org_id,
        repo_id=repo_id,
        request_id=request_id,
        code_context=[],
        session_messages=[],
        context_block="",
        intent="code",
        tool_calls=[],
        tool_results=[],
        current_step=0,
        max_steps=5,
        draft_output="",
        revision_count=0,
        review_feedback="",
        final_response="",
        files_modified=[],
        context_chunks_used=0,
        tokens_used=0,
        error=None,
    )
