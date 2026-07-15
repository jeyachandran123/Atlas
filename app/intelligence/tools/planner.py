"""
Intelligence Tool Planner.

Decides BEFORE calling the LLM:
- Should tools be used at all?
- Which tools, in what order?
- Which tools can run in parallel?
- Can the answer be produced without tools?

This is distinct from the existing LLM-based ToolPlanner in agents/.
That planner asks the LLM to decide. This planner uses deterministic rules
based on intent and context — faster, cheaper, and more predictable.

The LLM-based planner is used as a fallback for ambiguous cases.
"""

from __future__ import annotations

from app.intelligence.interfaces import AbstractToolPlanner
from app.intelligence.models import (
    Complexity,
    ComplexityAnalysis,
    IntelligenceContext,
    Intent,
    ToolPlan,
)

# Intent → tools that are almost always needed
_INTENT_TOOL_HINTS: dict[Intent, list[str]] = {
    Intent.REPOSITORY_QUESTION: ["search_code", "read_file"],
    Intent.DEBUGGING:           ["search_code", "read_file"],
    Intent.REFACTORING:         ["search_code", "read_file"],
    Intent.GIT_OPERATIONS:      ["git_diff"],
    Intent.TOOL_EXECUTION:      ["run_command"],
    Intent.CODING:              [],
    Intent.TESTING:             ["search_code"],
}

# Keywords that indicate a directory listing is needed
_LIST_DIR_KEYWORDS = {
    "structure", "list files", "list directory", "show files", "show directory",
    "what files", "folder structure", "directory structure", "file tree",
    "what's in", "what is in", "show me the repo", "repo structure",
}

# Tools that can safely run in parallel
_PARALLEL_SAFE = {"search_code", "git_diff"}


class IntelligenceToolPlanner(AbstractToolPlanner):
    """
    Deterministic tool planning based on intent and context.
    No LLM call required for common cases.
    """

    def plan(self, context: IntelligenceContext) -> ToolPlan:
        intent = context.intent_analysis.primary.intent
        has_repo = bool(context.repo_id)
        has_code_context = bool(context.code_context_block)
        complexity = context.complexity.level
        message = context.user_message.lower() if context.user_message else ""

        # No repo → no file/search tools
        if not has_repo:
            return ToolPlan(
                should_use_tools=False,
                can_answer_without_tools=True,
                rationale="No repository selected — tools not applicable",
            )

        # Directory listing request — always use list_directory
        if any(kw in message for kw in _LIST_DIR_KEYWORDS):
            return ToolPlan(
                should_use_tools=True,
                tools=["list_directory"],
                can_answer_without_tools=False,
                rationale="User wants directory structure",
            )

        # Already have sufficient context
        if has_code_context and complexity in (Complexity.SIMPLE, Complexity.MEDIUM):
            return ToolPlan(
                should_use_tools=False,
                can_answer_without_tools=True,
                rationale="Sufficient context already retrieved",
            )

        # Get intent-based tool hints
        tools = list(_INTENT_TOOL_HINTS.get(intent, []))

        # For coding intents without context, add search
        if intent == Intent.CODING and not has_code_context and has_repo:
            tools = ["search_code"]

        if not tools:
            return ToolPlan(
                should_use_tools=False,
                can_answer_without_tools=True,
                rationale="No tools required for this intent",
            )

        # Build parallel groups
        parallel_groups: list[list[str]] = []
        sequential: list[str] = []
        parallel_batch: list[str] = []

        for tool in tools:
            if tool in _PARALLEL_SAFE:
                parallel_batch.append(tool)
            else:
                if parallel_batch:
                    parallel_groups.append(parallel_batch)
                    parallel_batch = []
                sequential.append(tool)

        if parallel_batch:
            parallel_groups.append(parallel_batch)

        return ToolPlan(
            should_use_tools=True,
            tools=tools,
            parallel_groups=parallel_groups,
            can_answer_without_tools=False,
            rationale=f"Intent '{intent.value}' benefits from: {', '.join(tools)}",
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_planner: IntelligenceToolPlanner | None = None


def get_intelligence_tool_planner() -> IntelligenceToolPlanner:
    global _planner
    if _planner is None:
        _planner = IntelligenceToolPlanner()
    return _planner
