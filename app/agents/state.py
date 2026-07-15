"""
LangGraph agent state — V3 Execution Pipeline Architecture.

AgentState is the single shared object passed through every node.
Agents read from it and write to it. They never call each other directly.

V3 additions:
- rewritten_query: enriched query from QueryRewriter (replaces raw message to LLM)
- should_clarify: set by ConfidenceEvaluator — triggers clarification short-circuit
- clarification_question: pre-built question to return to user
- execution_plan_summary: human-readable plan from ExecutionPlanner
- intelligence_context: full IntelligenceContext from the engine
- intelligence_trace: full IntelligenceTrace for observability
- intelligence_reasoning_result: ReasoningResult from ReasoningEngine
- refused: set by PolicyEngine BLOCK — triggers immediate short-circuit
"""

from __future__ import annotations

from typing import Any, Optional
from typing_extensions import TypedDict

from app.shared.schemas import SearchResult, ToolCall, ToolResult


class AgentState(TypedDict):
    """
    State shared across all nodes in the LangGraph graph.

    Field lifecycle:
    - Input:          set at graph entry, never modified
    - Intelligence:   populated by intelligence_prepare_node
    - Composition:    system_prompt built by DynamicPromptComposer
    - Execution:      modified by agents as they work
    - Output:         set at terminal node, returned to caller
    """

    # ── Input (set once at graph entry) ──────────────────────────────────────
    user_message: str
    conversation_id: str
    user_id: str
    org_id: str
    repo_id: Optional[str]
    request_id: str

    # ── Mode (set by user in UI) ──────────────────────────────────────────────
    # "auto" | "code" | "business"
    agent_mode: str

    # ── Intent (set by intelligence engine) ───────────────────────────────────
    # Legacy string: "code" | "fix" | "review" | "explain" | "test" | "search" | "chat"
    intent: str

    # ── V3: Intelligence Engine Outputs ───────────────────────────────────────

    # Enriched query from QueryRewriter — used as the actual message sent to LLM
    # Falls back to user_message if rewriter produces no enrichments
    rewritten_query: str

    # Clarification short-circuit — set by ConfidenceEvaluator
    should_clarify: bool
    clarification_question: str

    # Human-readable execution plan from ExecutionPlanner
    execution_plan_summary: str

    # Full intelligence engine outputs (typed loosely to avoid import chain)
    intelligence_context: Any   # IntelligenceContext | None
    intelligence_trace: Any     # IntelligenceTrace | None
    intelligence_reasoning_result: Any  # ReasoningResult | None

    # Policy block short-circuit
    refused: bool

    # ── Context Detection (legacy fallback fields) ────────────────────────────
    # Populated by detect_context node when intelligence engine is unavailable.
    detected_language: str
    detected_framework: str
    detected_database: str
    detected_cloud: str
    detected_business_domain: str
    detected_architecture: str
    detected_testing: str
    detected_security: bool
    detected_ai_domain: bool

    # ── Composed Prompt (set by intelligence engine or compose_prompt node) ───
    system_prompt: str

    # ── Memory & Retrieval Context ────────────────────────────────────────────
    code_context: list[SearchResult]
    session_messages: list[dict]
    context_block: str
    memory_context: str

    # ── Execution (modified by agents) ────────────────────────────────────────
    tool_calls: list[ToolCall]
    tool_results: list[ToolResult]
    current_step: int
    max_steps: int
    draft_output: str
    revision_count: int
    max_revisions: int
    review_feedback: str
    review_status: str  # "pending" | "approved" | "needs_revision" | "skipped"

    # ── Truthfulness & Self-Correction ────────────────────────────────────────
    confidence_score: float
    verified_facts: list[str]
    detected_contradictions: list[str]
    truthfulness_warnings: list[str]
    self_corrections: list[str]
    uncertainty_level: str

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
    agent_mode: str = "auto",
) -> AgentState:
    """Create a fresh AgentState with all required defaults."""
    return AgentState(
        # Input
        user_message=user_message,
        conversation_id=conversation_id,
        user_id=user_id,
        org_id=org_id,
        repo_id=repo_id,
        request_id=request_id,
        agent_mode=agent_mode,
        # Intent
        intent="chat",
        # V3 intelligence outputs
        rewritten_query=user_message,  # default: raw message until rewriter runs
        should_clarify=False,
        clarification_question="",
        execution_plan_summary="",
        intelligence_context=None,
        intelligence_trace=None,
        intelligence_reasoning_result=None,
        refused=False,
        # Detection (legacy fallback — all empty)
        detected_language="",
        detected_framework="",
        detected_database="",
        detected_cloud="",
        detected_business_domain="",
        detected_architecture="",
        detected_testing="",
        detected_security=False,
        detected_ai_domain=False,
        # Composed prompt
        system_prompt="",
        # Memory & retrieval
        code_context=[],
        session_messages=[],
        context_block="",
        memory_context="",
        # Execution
        tool_calls=[],
        tool_results=[],
        current_step=0,
        max_steps=5,
        draft_output="",
        revision_count=0,
        max_revisions=2,
        review_feedback="",
        review_status="pending",
        # Truthfulness
        confidence_score=1.0,
        verified_facts=[],
        detected_contradictions=[],
        truthfulness_warnings=[],
        self_corrections=[],
        uncertainty_level="none",
        # Output
        final_response="",
        files_modified=[],
        context_chunks_used=0,
        tokens_used=0,
        error=None,
    )
