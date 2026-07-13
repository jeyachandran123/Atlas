"""
Intelligent Prompt Expander.

Transforms incomplete or vague user messages into complete internal objectives.
This is NOT a template filler. It reasons about what the user actually needs.

Rules:
  - Never change the user's meaning
  - Only add what is implied but unstated
  - The expansion is an internal instruction, not shown to the user
  - Different intents produce different expansion strategies
  - Short questions get expanded; detailed questions pass through with light enrichment

Examples:
  "How humans evolved?"
  → "Provide a comprehensive educational explanation of human evolution.
     Start from early primates, cover major hominin species chronologically,
     explain key evolutionary pressures (bipedalism, brain size, tool use),
     discuss migration out of Africa, and connect to modern humans.
     Assume no prior biology knowledge. Use concrete examples and timelines."

  "When were computers invented?"
  → "Explain the history of computing from mechanical calculators through
     modern computers. Cover key milestones: Babbage, Turing, ENIAC, transistors,
     microprocessors, personal computers. Explain the significance of each step."

  "Fix my login bug"
  → "Diagnose and fix the login bug. Identify the root cause, explain why it
     occurs, provide the complete fix, and add prevention measures."
"""

from __future__ import annotations

from dataclasses import dataclass

from app.intelligence.models import ConversationTurn


@dataclass
class ExpandedPrompt:
    """The expanded internal objective for the LLM."""
    original: str
    expanded: str
    expansion_applied: bool
    expansion_type: str   # "educational" | "technical" | "diagnostic" | "comparative" | "none"


# ── Domain-aware expansion templates ─────────────────────────────────────────
# These are OBJECTIVE BUILDERS, not response templates.
# They tell the LLM what to cover, not how to write.

_EDUCATIONAL_EXPANSION = (
    "Provide a comprehensive educational explanation of: {topic}. "
    "Cover the subject progressively from foundational concepts to key developments. "
    "Use concrete examples and real-world context. "
    "Assume the reader has {audience_level} knowledge of this subject."
)

_HISTORY_EXPANSION = (
    "Explain the history and development of: {topic}. "
    "Cover key milestones chronologically, explain the significance of each, "
    "and connect them to show how each development led to the next. "
    "Include the people, discoveries, or events that drove each change."
)

_TECHNICAL_EXPANSION = (
    "Explain {topic} technically. "
    "Cover: what it is, how it works internally, when to use it, "
    "common patterns and pitfalls, and practical examples."
)

_DIAGNOSTIC_EXPANSION = (
    "Diagnose and resolve: {topic}. "
    "Identify the root cause, explain why it occurs, "
    "provide the complete fix with code, and add prevention measures."
)

_COMPARATIVE_EXPANSION = (
    "Compare {topic} systematically. "
    "Evaluate each option on: use case fit, performance, complexity, ecosystem, and maturity. "
    "Give a clear recommendation based on the context."
)

_CODING_EXPANSION = (
    "Implement {topic}. "
    "Provide complete, working code with error handling. "
    "Explain the design decisions and any important trade-offs."
)

# ── Topic classifiers ─────────────────────────────────────────────────────────

_HISTORY_TOPICS = [
    "history", "invented", "created", "origin", "evolution", "developed",
    "when did", "when was", "how did", "timeline", "ancient", "first",
    "discovery", "discovered",
]

_SCIENCE_TOPICS = [
    "evolution", "biology", "physics", "chemistry", "astronomy", "genetics",
    "quantum", "relativity", "atom", "cell", "dna", "species", "organism",
    "human", "animal", "planet", "universe", "brain", "consciousness",
]

_TECH_TOPICS = [
    "algorithm", "data structure", "database", "network", "protocol",
    "compiler", "operating system", "memory", "cpu", "cache", "thread",
    "async", "concurrency", "distributed",
]


def _classify_expansion_type(message: str, intent: str) -> str:
    lower = message.lower()

    if intent in ("debugging", "fix"):
        return "diagnostic"
    if intent == "comparison":
        return "comparative"
    if intent in ("coding", "refactoring", "testing"):
        return "coding"
    if any(s in lower for s in _HISTORY_TOPICS):
        return "history"
    if any(s in lower for s in _SCIENCE_TOPICS):
        return "educational"
    if any(s in lower for s in _TECH_TOPICS):
        return "technical"
    if intent in ("learning", "deep_teaching"):
        return "educational"

    return "none"


def _needs_expansion(message: str) -> bool:
    """Determine if the message is incomplete enough to warrant expansion."""
    word_count = len(message.split())
    # Short questions almost always need expansion
    if word_count <= 10:
        return True
    # Medium questions with vague verbs need expansion
    vague_starters = ["explain", "tell me about", "what is", "how does", "describe", "teach me"]
    lower = message.lower()
    if any(lower.startswith(s) for s in vague_starters) and word_count <= 15:
        return True
    return False


def _build_expansion(
    message: str,
    expansion_type: str,
    topic: str,
    audience_level: str,
) -> str:
    audience_map = {
        "beginner": "no prior",
        "intermediate": "some",
        "expert": "deep",
        "unknown": "general",
    }
    audience_str = audience_map.get(audience_level, "general")

    templates = {
        "educational": _EDUCATIONAL_EXPANSION.format(topic=topic, audience_level=audience_str),
        "history":     _HISTORY_EXPANSION.format(topic=topic),
        "technical":   _TECHNICAL_EXPANSION.format(topic=topic),
        "diagnostic":  _DIAGNOSTIC_EXPANSION.format(topic=message[:80]),
        "comparative": _COMPARATIVE_EXPANSION.format(topic=topic),
        "coding":      _CODING_EXPANSION.format(topic=message[:80]),
    }
    return templates.get(expansion_type, message)


class PromptExpander:
    """
    Expands incomplete user prompts into complete internal objectives.
    The expansion is used internally — the user never sees it.
    """

    def expand(
        self,
        message: str,
        intent: str,
        topic: str,
        audience_level: str,
        turn_type: ConversationTurn,
    ) -> ExpandedPrompt:
        # Follow-ups and corrections should not be re-expanded
        # — they reference prior context and need to stay focused
        if turn_type in (ConversationTurn.CORRECTION, ConversationTurn.CLARIFICATION):
            return ExpandedPrompt(
                original=message,
                expanded=message,
                expansion_applied=False,
                expansion_type="none",
            )

        expansion_type = _classify_expansion_type(message, intent)

        if expansion_type == "none" or not _needs_expansion(message):
            return ExpandedPrompt(
                original=message,
                expanded=message,
                expansion_applied=False,
                expansion_type="none",
            )

        expanded = _build_expansion(message, expansion_type, topic, audience_level)

        return ExpandedPrompt(
            original=message,
            expanded=expanded,
            expansion_applied=True,
            expansion_type=expansion_type,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_expander: PromptExpander | None = None


def get_prompt_expander() -> PromptExpander:
    global _expander
    if _expander is None:
        _expander = PromptExpander()
    return _expander
