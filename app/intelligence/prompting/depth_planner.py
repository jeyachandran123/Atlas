"""
Response Depth Planner.

Determines the appropriate response depth dynamically.
Never hardcodes lengths. Estimates from multiple signals.

Signals considered:
  - Intent (learning vs quick question)
  - Complexity level
  - User wording (explicit depth requests)
  - Conversation history (has this been partially answered?)
  - Educational value of the topic
  - Whether repo context is available

Output: a DepthPlan that tells the composer exactly what depth to target.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.intelligence.models import Complexity, ConversationTurn


@dataclass
class DepthPlan:
    """Describes how deep and long the response should be."""
    depth_label: str          # "brief" | "moderate" | "detailed" | "comprehensive"
    target_length: str        # "1-2 paragraphs" | "3-5 paragraphs" | "full article" | etc.
    use_sections: bool        # whether to use ## headers
    use_examples: bool
    use_code: bool
    depth_instruction: str    # the actual instruction injected into the prompt


# ── Explicit depth signals in user message ────────────────────────────────────

_BRIEF_SIGNALS = [
    "briefly", "quick", "short", "tldr", "in one sentence", "just tell me",
    "simple answer", "quick answer", "in a nutshell", "summary",
]

_DETAILED_SIGNALS = [
    "detailed", "in detail", "thoroughly", "comprehensive", "complete",
    "full explanation", "everything about", "all about", "deep dive",
    "in depth", "explain fully",
]

_TUTORIAL_SIGNALS = [
    "teach me", "tutorial", "from scratch", "step by step", "guide me",
    "walk me through", "beginner to advanced", "learn", "how to learn",
    "full course", "complete guide",
]

# ── Intent → base depth ───────────────────────────────────────────────────────

_INTENT_DEPTH: dict[str, str] = {
    "general_chat":        "brief",
    "learning":            "detailed",
    "deep_teaching":       "comprehensive",
    "coding":              "moderate",
    "debugging":           "moderate",
    "architecture":        "detailed",
    "recommendation":      "moderate",
    "comparison":          "detailed",
    "research":            "detailed",
    "brainstorming":       "moderate",
    "planning":            "detailed",
    "refactoring":         "moderate",
    "testing":             "moderate",
    "documentation":       "moderate",
    "repository_question": "brief",
    "git_operations":      "brief",
    "tool_execution":      "brief",
    "unknown":             "moderate",
}

# ── Depth profiles ────────────────────────────────────────────────────────────

_DEPTH_PROFILES: dict[str, dict] = {
    "brief": {
        "target_length": "1-3 paragraphs",
        "use_sections": False,
        "use_examples": False,
        "use_code": False,
        "instruction": (
            "Be concise and direct. Answer the question clearly in 1-3 paragraphs. "
            "No headers. No padding."
        ),
    },
    "moderate": {
        "target_length": "3-6 paragraphs or equivalent code",
        "use_sections": False,
        "use_examples": True,
        "use_code": True,
        "instruction": (
            "Provide a clear, complete answer. Include examples where they add clarity. "
            "Use headers only if the response has genuinely distinct sections."
        ),
    },
    "detailed": {
        "target_length": "structured multi-section response",
        "use_sections": True,
        "use_examples": True,
        "use_code": True,
        "instruction": (
            "Provide a thorough, well-structured response. "
            "Use sections to organise the content. Include examples and practical context. "
            "Cover the topic completely without padding."
        ),
    },
    "comprehensive": {
        "target_length": "full educational article",
        "use_sections": True,
        "use_examples": True,
        "use_code": True,
        "instruction": (
            "Provide a comprehensive, educational response. "
            "Structure it progressively: foundations first, then depth. "
            "Use sections, examples, and concrete illustrations. "
            "Cover every important aspect. Do not stop early."
        ),
    },
}


def _resolve_depth(
    message: str,
    intent: str,
    complexity: Complexity,
    turn_type: ConversationTurn,
    has_prior_answer: bool,
) -> str:
    lower = message.lower()

    # Explicit user signals override everything
    if any(s in lower for s in _BRIEF_SIGNALS):
        return "brief"
    if any(s in lower for s in _TUTORIAL_SIGNALS):
        return "comprehensive"
    if any(s in lower for s in _DETAILED_SIGNALS):
        return "detailed"

    # Follow-ups and corrections should be brief — don't repeat everything
    if turn_type in (ConversationTurn.FOLLOW_UP, ConversationTurn.CORRECTION, ConversationTurn.CLARIFICATION):
        return "brief"

    # Complexity upgrade
    complexity_map = {
        Complexity.SIMPLE:       "brief",
        Complexity.MEDIUM:       "moderate",
        Complexity.COMPLEX:      "detailed",
        Complexity.VERY_COMPLEX: "comprehensive",
    }
    complexity_depth = complexity_map.get(complexity, "moderate")

    # Intent base
    intent_depth = _INTENT_DEPTH.get(intent, "moderate")

    # Take the deeper of the two
    depth_order = ["brief", "moderate", "detailed", "comprehensive"]
    intent_idx = depth_order.index(intent_depth)
    complexity_idx = depth_order.index(complexity_depth)
    return depth_order[max(intent_idx, complexity_idx)]


class ResponseDepthPlanner:
    """
    Determines the appropriate response depth for each request.
    """

    def plan(
        self,
        message: str,
        intent: str,
        complexity: Complexity,
        turn_type: ConversationTurn,
        has_prior_answer: bool = False,
        use_code: bool = False,
    ) -> DepthPlan:
        depth_label = _resolve_depth(message, intent, complexity, turn_type, has_prior_answer)
        profile = _DEPTH_PROFILES[depth_label]

        # Code intent always enables code blocks
        should_use_code = use_code or profile["use_code"] or intent in (
            "coding", "debugging", "refactoring", "testing"
        )

        return DepthPlan(
            depth_label=depth_label,
            target_length=profile["target_length"],
            use_sections=profile["use_sections"],
            use_examples=profile["use_examples"],
            use_code=should_use_code,
            depth_instruction=profile["instruction"],
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_planner: ResponseDepthPlanner | None = None


def get_depth_planner() -> ResponseDepthPlanner:
    global _planner
    if _planner is None:
        _planner = ResponseDepthPlanner()
    return _planner
