"""
Goal Analyzer.

Transforms user messages into clear, structured goals.
Users rarely state their actual goal — this module infers it.

"My authentication is broken."
→ Goal: Find auth implementation, locate defect, fix it, validate, explain.

No LLM call. Pure rule-based inference from intent + message signals.
"""

from __future__ import annotations

from app.intelligence.reasoning.interfaces import AbstractGoalAnalyzer
from app.intelligence.reasoning.models import (
    ActiveGoalContext,
    GoalType,
    InferredGoal,
)

# ── Goal type inference rules ─────────────────────────────────────────────────
# Maps (intent_value, message_signals) → GoalType + sub_objectives template

_DEBUGGING_SIGNALS = ["broken", "not working", "error", "crash", "failing", "bug", "exception"]
_BUILD_SIGNALS     = ["create", "build", "implement", "write", "add", "generate", "make"]
_IMPROVE_SIGNALS   = ["improve", "refactor", "optimize", "clean", "better", "enhance", "upgrade"]
_VALIDATE_SIGNALS  = ["test", "verify", "check", "validate", "confirm", "ensure"]
_DECIDE_SIGNALS    = ["should i", "recommend", "which", "best", "choose", "pick"]

# Intent → GoalType mapping (primary)
_INTENT_GOAL_MAP: dict[str, GoalType] = {
    "coding":              GoalType.BUILD,
    "debugging":           GoalType.FIND_AND_FIX,
    "architecture":        GoalType.PLAN,
    "repository_question": GoalType.UNDERSTAND,
    "documentation":       GoalType.EXPLAIN,
    "learning":            GoalType.UNDERSTAND,
    "deep_teaching":       GoalType.EXPLAIN,
    "recommendation":      GoalType.DECIDE,
    "comparison":          GoalType.COMPARE,
    "research":            GoalType.RESEARCH,
    "brainstorming":       GoalType.PLAN,
    "planning":            GoalType.PLAN,
    "refactoring":         GoalType.IMPROVE,
    "testing":             GoalType.VALIDATE,
    "git_operations":      GoalType.BUILD,
    "tool_execution":      GoalType.BUILD,
    "general_chat":        GoalType.UNDERSTAND,
    "unknown":             GoalType.UNKNOWN,
    "document_analysis":   GoalType.RESEARCH,
}

# GoalType → sub_objective templates
_GOAL_TEMPLATES: dict[GoalType, list[str]] = {
    GoalType.FIND_AND_FIX: [
        "Locate the relevant implementation",
        "Identify the root cause of the problem",
        "Design and apply the fix",
        "Validate the fix is correct",
        "Explain what was wrong and why the fix works",
    ],
    GoalType.BUILD: [
        "Understand the requirements",
        "Design the implementation approach",
        "Write the complete implementation",
        "Handle edge cases and errors",
        "Explain the design decisions",
    ],
    GoalType.IMPROVE: [
        "Analyze the current implementation",
        "Identify specific improvement opportunities",
        "Apply improvements without breaking existing behaviour",
        "Explain what changed and why",
    ],
    GoalType.UNDERSTAND: [
        "Identify what the user needs to understand",
        "Build a clear mental model",
        "Provide concrete examples",
        "Connect to what the user already knows",
    ],
    GoalType.EXPLAIN: [
        "Identify the target audience level",
        "Structure the explanation progressively",
        "Use examples and analogies",
        "Summarize key takeaways",
    ],
    GoalType.VALIDATE: [
        "Understand what needs to be validated",
        "Design appropriate test cases",
        "Implement the tests",
        "Report results and coverage",
    ],
    GoalType.RESEARCH: [
        "Identify the scope of the research",
        "Survey available options or approaches",
        "Evaluate each option against the context",
        "Synthesize findings into actionable insights",
    ],
    GoalType.DECIDE: [
        "Understand the decision context",
        "Identify the relevant options",
        "Evaluate trade-offs for this specific context",
        "Make a clear recommendation with reasoning",
    ],
    GoalType.COMPARE: [
        "Identify what is being compared",
        "Define the comparison dimensions",
        "Evaluate each option on each dimension",
        "Recommend the best fit for the user's context",
    ],
    GoalType.PLAN: [
        "Understand the desired outcome",
        "Break the work into phases",
        "Identify dependencies and risks",
        "Produce an actionable plan",
    ],
    GoalType.UNKNOWN: [
        "Clarify the user's intent",
        "Identify the most likely goal",
        "Respond to the most probable interpretation",
    ],
}

# GoalType → success criteria templates
_SUCCESS_CRITERIA: dict[GoalType, list[str]] = {
    GoalType.FIND_AND_FIX:  ["Problem is identified", "Fix is complete and correct", "Explanation is clear"],
    GoalType.BUILD:         ["Implementation is complete", "Code is correct and handles errors", "Design is explained"],
    GoalType.IMPROVE:       ["Improvements are applied", "Existing behaviour is preserved", "Changes are explained"],
    GoalType.UNDERSTAND:    ["Concept is clear", "Examples are provided", "User can apply the knowledge"],
    GoalType.EXPLAIN:       ["Explanation is complete", "Examples are used", "Key points are summarized"],
    GoalType.VALIDATE:      ["Tests are written", "Coverage is adequate", "Results are reported"],
    GoalType.RESEARCH:      ["Options are surveyed", "Trade-offs are clear", "Recommendation is actionable"],
    GoalType.DECIDE:        ["Recommendation is clear", "Reasoning is explained", "Context is considered"],
    GoalType.COMPARE:       ["Comparison is systematic", "Differences are clear", "Best fit is identified"],
    GoalType.PLAN:          ["Plan is actionable", "Dependencies are identified", "Risks are noted"],
    GoalType.UNKNOWN:       ["Intent is clarified", "Response is useful"],
}


def _infer_goal_type(intent: str, message: str) -> GoalType:
    """Infer goal type from intent + message signals."""
    lower = message.lower()

    # Message signals override intent for ambiguous cases
    if any(s in lower for s in _DEBUGGING_SIGNALS):
        return GoalType.FIND_AND_FIX
    if any(s in lower for s in _IMPROVE_SIGNALS):
        return GoalType.IMPROVE
    if any(s in lower for s in _BUILD_SIGNALS):
        return GoalType.BUILD
    if any(s in lower for s in _VALIDATE_SIGNALS) and "test" in lower:
        return GoalType.VALIDATE
    if any(s in lower for s in _DECIDE_SIGNALS):
        return GoalType.DECIDE

    return _INTENT_GOAL_MAP.get(intent, GoalType.UNKNOWN)


def _build_primary_objective(goal_type: GoalType, message: str) -> str:
    """Build a single-sentence primary objective."""
    templates = {
        GoalType.FIND_AND_FIX:  f"Find and fix the problem described: {message[:80]}",
        GoalType.BUILD:         f"Build the requested implementation: {message[:80]}",
        GoalType.IMPROVE:       f"Improve the existing implementation: {message[:80]}",
        GoalType.UNDERSTAND:    f"Explain clearly: {message[:80]}",
        GoalType.EXPLAIN:       f"Provide a complete explanation of: {message[:80]}",
        GoalType.VALIDATE:      f"Write tests to validate: {message[:80]}",
        GoalType.RESEARCH:      f"Research and synthesize: {message[:80]}",
        GoalType.DECIDE:        f"Make a recommendation for: {message[:80]}",
        GoalType.COMPARE:       f"Compare and evaluate: {message[:80]}",
        GoalType.PLAN:          f"Create an actionable plan for: {message[:80]}",
        GoalType.UNKNOWN:       f"Respond helpfully to: {message[:80]}",
    }
    return templates.get(goal_type, f"Address: {message[:80]}")


class GoalAnalyzer(AbstractGoalAnalyzer):
    """
    Infers the actual goal from a user message.
    Pure heuristic — no LLM call required.
    """

    def analyze(
        self,
        message: str,
        context: "IntelligenceContext",
        active_goal: ActiveGoalContext,
    ) -> InferredGoal:
        intent = context.intent_analysis.primary.intent.value
        intent_confidence = context.intent_analysis.primary.confidence
        lower = message.lower()

        goal_type = _infer_goal_type(intent, message)
        primary_objective = _build_primary_objective(goal_type, message)
        sub_objectives = list(_GOAL_TEMPLATES.get(goal_type, []))
        success_criteria = list(_SUCCESS_CRITERIA.get(goal_type, []))

        requires_repo = bool(context.repo_id) or any(
            s in lower for s in ["in this repo", "in my code", "in the codebase", "this project"]
        )
        requires_tools = goal_type in (
            GoalType.FIND_AND_FIX, GoalType.BUILD, GoalType.IMPROVE, GoalType.VALIDATE
        )

        # If continuing a prior goal, inherit its context
        if active_goal.goal_continuity and active_goal.current_goal:
            prior = active_goal.current_goal
            # Merge sub-objectives: keep prior ones not yet addressed
            sub_objectives = list(dict.fromkeys(prior.sub_objectives + sub_objectives))[:6]

        return InferredGoal(
            goal_type=goal_type,
            primary_objective=primary_objective,
            sub_objectives=sub_objectives,
            success_criteria=success_criteria,
            requires_repo=requires_repo,
            requires_tools=requires_tools,
            confidence=min(intent_confidence + 0.1, 1.0),
            raw_message=message,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_analyzer: GoalAnalyzer | None = None


def get_goal_analyzer() -> GoalAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = GoalAnalyzer()
    return _analyzer
