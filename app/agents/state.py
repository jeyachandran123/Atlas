"""
LangGraph agent state — V2 Dynamic Prompt Architecture.

AgentState is the single shared object passed through every node.
Agents read from it and write to it. They never call each other directly.

V2 additions:
- system_prompt: composed dynamically by PromptComposer node
- detected_* fields: populated by context detector nodes
- Truthfulness fields: confidence, verified_facts, contradictions, self_corrections
"""

from __future__ import annotations

from typing import Optional
from typing_extensions import TypedDict

from app.shared.schemas import SearchResult, ToolCall, ToolResult


class AgentState(TypedDict):
    """
    State shared across all nodes in the LangGraph graph.

    Field lifecycle:
    - Input:       set at graph entry, never modified
    - Detection:   populated by detector nodes (intent, context, language, framework)
    - Composition: system_prompt built by PromptComposer node
    - Execution:   modified by agents as they work
    - Truthfulness:populated by fact-verification and self-correction nodes
    - Output:      set at terminal node, returned to caller
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
    # Drives persona selection and model routing in PromptComposer + orchestrator
    agent_mode: str

    # ── Intent (detected by route_intent node) ────────────────────────────────
    # "code" | "fix" | "review" | "explain" | "test" | "search" | "chat"
    intent: str

    # ── Context Detection (populated by detect_context node) ─────────────────
    # These fields drive PromptComposer module selection.
    # Detected from user message via keyword analysis.
    detected_language: str        # e.g. "typescript", "python", ""
    detected_framework: str       # e.g. "nextjs", "fastapi", ""
    detected_database: str        # e.g. "postgresql", "mongodb", ""
    detected_cloud: str           # e.g. "aws", "docker", ""
    detected_business_domain: str # e.g. "hotel", "erp", "pos", ""
    detected_architecture: str    # e.g. "clean_architecture", "microservices", ""
    detected_testing: str         # e.g. "pytest", "unit_testing", ""
    detected_security: bool       # True if security-related request
    detected_ai_domain: bool      # True if AI/agent-related request

    # ── Composed Prompt (set by compose_prompt node) ──────────────────────────
    # The dynamically assembled system prompt — replaces static SYSTEM_PROMPTS dict.
    # Built by PromptComposer from detected_* fields + intent + agent_mode.
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
    # confidence_score: 0.0–1.0, estimated by self_correction node
    # 1.0 = fully confident, 0.0 = completely uncertain
    confidence_score: float

    # verified_facts: list of claims the agent confirmed as accurate
    verified_facts: list[str]

    # detected_contradictions: inconsistencies found between current response
    # and previous conversation turns or retrieved context
    detected_contradictions: list[str]

    # truthfulness_warnings: non-blocking warnings injected into the prompt
    # e.g. "User referenced a potentially non-existent library"
    truthfulness_warnings: list[str]

    # self_corrections: explicit corrections made during this turn
    # e.g. "My earlier response incorrectly stated X. The correct answer is Y."
    self_corrections: list[str]

    # uncertainty_level: "high" | "medium" | "low" | "none"
    # Drives whether uncertainty language is injected into the response
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
        # Detection (all empty — populated by detect_context node)
        detected_language="",
        detected_framework="",
        detected_database="",
        detected_cloud="",
        detected_business_domain="",
        detected_architecture="",
        detected_testing="",
        detected_security=False,
        detected_ai_domain=False,
        # Composed prompt (empty — set by compose_prompt node)
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
