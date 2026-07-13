"""
Prompt Understanding.

Analyses what the user actually wants before any prompt is written.
Answers:
  - What is the real objective? (explicit vs implicit)
  - What information is missing?
  - What assumptions is the user making?
  - Is this a complete question or a fragment?
  - What does the user already know (from conversation)?

No LLM call. Pure signal analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PromptUnderstanding:
    """Result of analysing the user's raw message."""
    real_objective: str          # what the user actually wants
    is_complete: bool            # is the question fully formed?
    missing_info: list[str]      # what context is absent
    user_assumptions: list[str]  # what the user is assuming
    prior_knowledge: list[str]   # what we already know about this user/topic
    is_implicit: bool            # is the goal implied rather than stated?
    topic: str                   # one-word topic label
    audience_level: str          # "beginner" | "intermediate" | "expert" | "unknown"


# ── Signals ───────────────────────────────────────────────────────────────────

_IMPLICIT_SIGNALS = [
    "how", "why", "when", "what", "where", "who",
    "can you", "could you", "tell me", "explain",
    "i want to know", "i'm curious",
]

_BEGINNER_SIGNALS = [
    "beginner", "new to", "just started", "learning", "never used",
    "don't know", "don't understand", "what is", "what are", "basics",
    "simple", "easy", "for dummies", "eli5", "explain like",
]

_EXPERT_SIGNALS = [
    "production", "enterprise", "advanced", "deep dive", "internals",
    "under the hood", "performance", "optimization", "architecture",
    "senior", "expert", "professional",
]

_INCOMPLETE_SIGNALS = [
    # very short messages that are clearly fragments
]


def _detect_audience(message: str, session_messages: list[dict]) -> str:
    lower = message.lower()
    history = " ".join(m.get("content", "").lower() for m in session_messages[-6:])
    combined = lower + " " + history

    if any(s in combined for s in _EXPERT_SIGNALS):
        return "expert"
    if any(s in combined for s in _BEGINNER_SIGNALS):
        return "beginner"
    # Medium-length questions with no signals → intermediate
    if len(message.split()) > 8:
        return "intermediate"
    return "unknown"


def _extract_prior_knowledge(session_messages: list[dict]) -> list[str]:
    """Extract what we already know about this user from conversation history."""
    if not session_messages:
        return []

    known: list[str] = []
    tech_map = {
        "python": "uses Python",
        "typescript": "uses TypeScript",
        "javascript": "uses JavaScript",
        "react": "uses React",
        "fastapi": "uses FastAPI",
        "django": "uses Django",
        "postgresql": "uses PostgreSQL",
        "docker": "uses Docker",
        "kubernetes": "uses Kubernetes",
        "aws": "uses AWS",
    }
    all_content = " ".join(m.get("content", "").lower() for m in session_messages[-8:])
    for kw, label in tech_map.items():
        if kw in all_content:
            known.append(label)

    return known[:4]


def _detect_missing_info(message: str, intent: str) -> list[str]:
    """Identify what context is absent from the user's question."""
    lower = message.lower()
    missing: list[str] = []

    if intent == "coding":
        if not any(lang in lower for lang in ["python", "typescript", "javascript", "java", "go", "rust", "c#"]):
            missing.append("programming language not specified")
        if not any(fw in lower for fw in ["react", "fastapi", "django", "express", "nextjs", "flask"]):
            pass  # framework is optional
    if intent in ("debugging", "fix"):
        if "error" not in lower and "exception" not in lower and "traceback" not in lower:
            missing.append("error message or stack trace not provided")
    if intent == "comparison" and lower.count(" vs ") == 0 and "compare" not in lower:
        missing.append("items to compare not clearly stated")

    return missing


def _infer_real_objective(message: str, intent: str, session_messages: list[dict]) -> str:
    """
    Infer the real objective from the raw message.
    For short/vague messages, expand using conversation context.
    """
    stripped = message.strip()

    # If the message is already detailed enough, use it directly
    if len(stripped.split()) >= 12:
        return stripped

    # For short messages, check if conversation gives us more context
    if session_messages:
        last_user = next(
            (m["content"] for m in reversed(session_messages) if m.get("role") == "user"),
            "",
        )
        last_assistant = next(
            (m["content"] for m in reversed(session_messages) if m.get("role") == "assistant"),
            "",
        )
        # If this looks like a follow-up, attach prior topic
        if last_user and len(stripped.split()) < 8:
            topic_hint = last_user[:60].strip()
            return f"{stripped} (in context of: {topic_hint})"

    return stripped


def _detect_topic(message: str) -> str:
    """Extract a short topic label from the message."""
    lower = message.lower()

    topic_map = {
        "evolution": "evolution", "human": "human biology", "computer": "computing",
        "python": "Python", "javascript": "JavaScript", "typescript": "TypeScript",
        "react": "React", "fastapi": "FastAPI", "docker": "Docker",
        "kubernetes": "Kubernetes", "aws": "AWS", "database": "databases",
        "sql": "SQL", "api": "API design", "machine learning": "ML",
        "neural": "neural networks", "git": "Git", "linux": "Linux",
        "security": "security", "auth": "authentication",
    }
    for kw, label in topic_map.items():
        if kw in lower:
            return label

    # Fall back to first meaningful noun phrase (first 3 words)
    words = [w for w in message.split() if len(w) > 3]
    return words[0].capitalize() if words else "general"


class PromptUnderstandingAnalyzer:
    """
    Analyses the user's raw message to understand the real objective.
    Called first in the Prompt Intelligence Engine pipeline.
    """

    def analyse(
        self,
        message: str,
        intent: str,
        session_messages: list[dict],
    ) -> PromptUnderstanding:
        lower = message.lower()
        word_count = len(message.split())

        real_objective = _infer_real_objective(message, intent, session_messages)
        is_complete = word_count >= 6
        is_implicit = any(s in lower for s in _IMPLICIT_SIGNALS) and word_count < 10
        missing_info = _detect_missing_info(message, intent)
        user_assumptions = []  # populated by conversation context resolver
        prior_knowledge = _extract_prior_knowledge(session_messages)
        topic = _detect_topic(message)
        audience_level = _detect_audience(message, session_messages)

        return PromptUnderstanding(
            real_objective=real_objective,
            is_complete=is_complete,
            missing_info=missing_info,
            user_assumptions=user_assumptions,
            prior_knowledge=prior_knowledge,
            is_implicit=is_implicit,
            topic=topic,
            audience_level=audience_level,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_analyser: PromptUnderstandingAnalyzer | None = None


def get_understanding_analyser() -> PromptUnderstandingAnalyzer:
    global _analyser
    if _analyser is None:
        _analyser = PromptUnderstandingAnalyzer()
    return _analyser
