"""
Conversation Analyzer.

Understands the conversational context before the LLM is called:
- Is this a new topic or continuation?
- Is the user correcting Atlas?
- What is the user's underlying goal?
- What assumptions exist from prior turns?
"""

from __future__ import annotations

from app.intelligence.interfaces import AbstractConversationAnalyzer
from app.intelligence.models import ConversationAnalysis, ConversationTurn, IntentAnalysis

_CORRECTION_SIGNALS = [
    "no, i meant", "that's not what i", "you misunderstood", "actually i want",
    "not that", "wrong", "incorrect", "that's wrong", "no no", "i said",
]

_FOLLOW_UP_SIGNALS = [
    "what about", "and also", "additionally", "furthermore", "can you also",
    "now show me", "next", "continue", "go on", "what else", "more about",
    "expand on", "tell me more",
]

_CLARIFICATION_SIGNALS = [
    "what do you mean", "can you clarify", "i don't understand", "confused",
    "elaborate", "explain that", "what exactly", "be more specific",
]


class ConversationAnalyzer(AbstractConversationAnalyzer):
    """
    Analyzes conversation history to understand turn type and user goal.
    Pure heuristic — no LLM call required.
    """

    def analyze(
        self,
        message: str,
        session_messages: list[dict],
        intent_analysis: IntentAnalysis,
    ) -> ConversationAnalysis:
        lower = message.lower()
        has_history = bool(session_messages)

        # Determine turn type
        turn_type = self._classify_turn(lower, has_history)

        # Extract prior context summary (last assistant message)
        prior_summary = ""
        referenced_prior = False
        if has_history:
            last_assistant = next(
                (m["content"] for m in reversed(session_messages) if m.get("role") == "assistant"),
                "",
            )
            if last_assistant:
                prior_summary = last_assistant[:200].strip()
                referenced_prior = turn_type in (
                    ConversationTurn.CONTINUATION,
                    ConversationTurn.FOLLOW_UP,
                    ConversationTurn.CORRECTION,
                )

        # Extract assumptions from history
        assumptions = self._extract_assumptions(session_messages)

        # Infer user goal
        user_goal = self._infer_goal(message, intent_analysis, session_messages)

        # Topic summary
        topic_summary = self._summarize_topic(message, session_messages)

        return ConversationAnalysis(
            turn_type=turn_type,
            topic_summary=topic_summary,
            user_goal=user_goal,
            is_continuation=turn_type != ConversationTurn.NEW_TOPIC,
            referenced_prior_turn=referenced_prior,
            prior_context_summary=prior_summary,
            assumptions=assumptions,
        )

    def _classify_turn(self, lower: str, has_history: bool) -> ConversationTurn:
        if not has_history:
            return ConversationTurn.NEW_TOPIC

        for sig in _CORRECTION_SIGNALS:
            if sig in lower:
                return ConversationTurn.CORRECTION

        for sig in _CLARIFICATION_SIGNALS:
            if sig in lower:
                return ConversationTurn.CLARIFICATION

        for sig in _FOLLOW_UP_SIGNALS:
            if sig in lower:
                return ConversationTurn.FOLLOW_UP

        # Short messages with no new topic signals are likely continuations
        word_count = len(lower.split())
        if word_count < 15:
            return ConversationTurn.CONTINUATION

        return ConversationTurn.NEW_TOPIC

    def _extract_assumptions(self, session_messages: list[dict]) -> list[str]:
        """Extract implicit assumptions from conversation history."""
        assumptions: list[str] = []
        if not session_messages:
            return assumptions

        # Look for technology mentions in prior messages
        tech_signals = {
            "python": "User is working with Python",
            "typescript": "User is working with TypeScript",
            "react": "User is using React",
            "fastapi": "User is using FastAPI",
            "postgresql": "User is using PostgreSQL",
            "docker": "User is using Docker",
        }
        all_content = " ".join(
            m.get("content", "").lower() for m in session_messages[-6:]
        )
        for kw, assumption in tech_signals.items():
            if kw in all_content:
                assumptions.append(assumption)

        return assumptions[:5]  # cap at 5

    def _infer_goal(
        self,
        message: str,
        intent_analysis: IntentAnalysis,
        session_messages: list[dict],
    ) -> str:
        intent_name = intent_analysis.primary.intent.value.replace("_", " ")
        if not session_messages:
            return f"User wants to {intent_name}: {message[:80]}"
        return f"User is {intent_name} (ongoing conversation with {len(session_messages)} turns)"

    def _summarize_topic(self, message: str, session_messages: list[dict]) -> str:
        if not session_messages:
            return message[:100]
        first_user = next(
            (m["content"] for m in session_messages if m.get("role") == "user"),
            message,
        )
        return first_user[:100]


# ── Singleton ─────────────────────────────────────────────────────────────────

_analyzer: ConversationAnalyzer | None = None


def get_conversation_analyzer() -> ConversationAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = ConversationAnalyzer()
    return _analyzer
