"""
ReviewAgent — adversarial code review agent.

Introduced in V1.2 (Priority #6) to catch bugs before the user sees them.

Design decisions:
- Runs ONLY for fix/test intents or when user explicitly requests review
- Uses a separate adversarial prompt (not collaborative like CodingAgent)
- Max 2 revision cycles to prevent infinite loops
- Reviews draft_output + files_modified + tool_results (not just the text)
- Returns either APPROVED or NEEDS_REVISION with specific feedback

Why adversarial:
Collaborative agents tend to rubber-stamp their own output. We want this agent
to actively look for problems: bugs, security issues, logic errors, missing edge cases.

Integration:
Called as a LangGraph node after CodingAgent completes, before finalise.
  coding_agent → should_review → [review_agent | finalise]
"""

from __future__ import annotations

import time
from typing import Optional

from app.agents.state import AgentState
from app.ollama_client import OllamaClient, get_ollama_client
from app.prompts.review import (
    REVIEW_SYSTEM_PROMPT,
    build_review_prompt,
    parse_review_response,
)


class ReviewAgent:
    """
    Adversarial code review agent.

    Called as a LangGraph node:
        state = await review_agent.run(state)

    Reads:
        - draft_output: The code/response to review
        - user_message: Original request
        - files_modified: Which files were changed
        - tool_results: What actions were taken
        - code_context: Relevant codebase chunks

    Writes:
        - review_status: "approved" | "needs_revision"
        - review_feedback: Specific issues to fix (if needs_revision)
        - tokens_used: Updated token count
    """

    def __init__(self, ollama: Optional[OllamaClient] = None) -> None:
        self._ollama = ollama or get_ollama_client()

    async def run(self, state: AgentState) -> AgentState:
        """
        Execute the review agent.

        Returns updated state with review_status and review_feedback.
        """
        start = time.monotonic()

        # Skip review if no draft output to review
        if not state.get("draft_output"):
            return {
                **state,
                "review_status": "skipped",
                "review_feedback": "",
            }

        # Format tool results for review
        tool_results_text = []
        for result in state["tool_results"]:
            status = "✓" if result.success else "✗"
            output = str(result.output or result.error or "")[:500]  # Limit length
            tool_results_text.append(f"[{status}] {result.tool_name}: {output}")

        # Build review prompt
        user_prompt = build_review_prompt(
            draft_output=state["draft_output"],
            user_request=state["user_message"],
            files_modified=state["files_modified"],
            code_context=state["context_block"],
            tool_results=tool_results_text,
        )

        try:
            # Call LLM for review
            response = await self._ollama.chat(
                prompt=user_prompt,
                system_prompt=REVIEW_SYSTEM_PROMPT,
                temperature=0.0,  # Deterministic for review
            )

            # Parse response
            review_status, review_feedback = parse_review_response(response)

            # Token estimation
            tokens = (len(user_prompt) + len(response)) // 4

            return {
                **state,
                "review_status": review_status,
                "review_feedback": review_feedback,
                "tokens_used": state["tokens_used"] + tokens,
            }

        except Exception as e:
            from loguru import logger
            logger.error(f"ReviewAgent failed: {e}")
            # On error, skip review and proceed (don't block the pipeline)
            return {
                **state,
                "review_status": "skipped",
                "review_feedback": "",
                "error": f"Review failed: {str(e)}",
            }

    def should_run_review(self, state: AgentState) -> bool:
        """
        Determine if review should run based on intent and state.

        Review runs when:
        1. Intent is "fix" or "test" (code changes that need validation)
        2. Intent is "review" (user explicitly asked for review)
        3. Files were modified (code was actually changed)

        Review DOES NOT run when:
        - Intent is "explain", "search", "chat" (no code changes)
        - No files were modified (just text response)
        - We've already done max_revisions cycles
        """
        # Check revision limit
        if state["revision_count"] >= state["max_revisions"]:
            return False

        # Check intent
        intent = state.get("intent", "code")
        if intent in ["fix", "test", "review"]:
            return True

        # Check if files were actually modified
        if state.get("files_modified"):
            return True

        # Otherwise skip review
        return False


def should_review_decision(state: AgentState) -> str:
    """
    Conditional edge function for LangGraph.
    Returns "review" or "skip" to route the graph.
    """
    agent = ReviewAgent()
    should_review = agent.should_run_review(state)
    return "review" if should_review else "skip"


def check_revision_decision(state: AgentState) -> str:
    """
    Conditional edge after review.
    Returns "revise" (loop back to coding_agent) or "finalise" (done).
    """
    review_status = state.get("review_status", "approved")
    revision_count = state.get("revision_count", 0)
    max_revisions = state.get("max_revisions", 2)

    # If approved or skipped, we're done
    if review_status in ["approved", "skipped"]:
        return "finalise"

    # If needs revision but we've hit the limit, finalize anyway
    if review_status == "needs_revision" and revision_count >= max_revisions:
        return "finalise"

    # Otherwise, revise
    return "revise"
