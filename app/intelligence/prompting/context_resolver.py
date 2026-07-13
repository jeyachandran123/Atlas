"""
Conversation Context Resolver.

Decides WHICH parts of conversation history are actually useful for this request.
Does NOT blindly inject all history.

Rules:
  - New topic  → no history injected
  - Greeting   → no history injected
  - Follow-up  → inject only the immediately relevant prior exchange
  - Correction → inject only the message being corrected
  - Continuation → inject last 2-3 relevant turns
  - Clarification → inject the specific thing being clarified

The output is a filtered, relevance-ranked list of messages — not the raw history.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.intelligence.models import ConversationTurn


@dataclass
class ResolvedContext:
    """The conversation context that should actually be injected into the prompt."""
    messages: list[dict]           # filtered, relevant messages only
    context_summary: str           # one-sentence summary of active context
    inject_history: bool           # whether any history should be injected at all
    active_topic: str              # what topic is currently active
    continuity_note: str           # instruction for the LLM about continuity


_GREETING_SIGNALS = {
    "hi", "hello", "hey", "good morning", "good evening", "good afternoon",
    "howdy", "sup", "what's up", "greetings",
}

_TOPIC_SHIFT_SIGNALS = [
    "new question", "different topic", "change subject", "forget that",
    "let's talk about", "switching to", "moving on",
    "by the way", "actually", "never mind",
]


def _is_greeting(message: str) -> bool:
    stripped = message.strip().lower().rstrip("?!.,")
    if stripped in _GREETING_SIGNALS:
        return True
    if len(stripped.split()) <= 3 and any(g in stripped for g in _GREETING_SIGNALS):
        return True
    return False


def _is_topic_shift(message: str) -> bool:
    lower = message.lower()
    return any(sig in lower for sig in _TOPIC_SHIFT_SIGNALS)


def _topic_overlap(message: str, history_content: str) -> float:
    """
    Simple lexical overlap score between current message and history.
    Returns 0.0–1.0. Higher = more relevant history.
    """
    msg_words = set(w.lower() for w in message.split() if len(w) > 3)
    hist_words = set(w.lower() for w in history_content.split() if len(w) > 3)
    if not msg_words:
        return 0.0
    overlap = msg_words & hist_words
    return len(overlap) / len(msg_words)


def _extract_relevant_messages(
    message: str,
    session_messages: list[dict],
    turn_type: ConversationTurn,
    max_turns: int,
) -> list[dict]:
    """Select only the messages that are relevant to the current request."""
    if not session_messages:
        return []

    if turn_type == ConversationTurn.NEW_TOPIC:
        return []

    if turn_type == ConversationTurn.CORRECTION:
        # Only the last exchange (what's being corrected)
        last_pair = session_messages[-2:] if len(session_messages) >= 2 else session_messages[-1:]
        return last_pair

    if turn_type == ConversationTurn.CLARIFICATION:
        # The specific thing being clarified — last assistant message
        last_assistant = [m for m in session_messages if m.get("role") == "assistant"]
        return last_assistant[-1:] if last_assistant else []

    if turn_type == ConversationTurn.FOLLOW_UP:
        # Last 2 turns (4 messages) — the active thread
        return session_messages[-4:]

    # CONTINUATION — filter by topic overlap
    recent = session_messages[-(max_turns * 2):]
    history_text = " ".join(m.get("content", "") for m in recent)
    overlap = _topic_overlap(message, history_text)

    if overlap < 0.1:
        # Very low overlap — topic has drifted, don't inject
        return []

    return recent


def _build_continuity_note(turn_type: ConversationTurn, active_topic: str) -> str:
    notes = {
        ConversationTurn.NEW_TOPIC:      "",
        ConversationTurn.CONTINUATION:   f"Continue the ongoing discussion about {active_topic}. Do not reintroduce concepts already established.",
        ConversationTurn.FOLLOW_UP:      f"This is a follow-up to the previous response about {active_topic}. Build on what was already explained.",
        ConversationTurn.CORRECTION:     "The user is correcting a previous response. Address the correction directly without repeating what was already said.",
        ConversationTurn.CLARIFICATION:  "The user wants clarification on a specific point. Be precise and targeted.",
    }
    return notes.get(turn_type, "")


class ConversationContextResolver:
    """
    Resolves which conversation history is relevant for the current request.
    Replaces the mechanical history injection in the old system.
    """

    def resolve(
        self,
        message: str,
        session_messages: list[dict],
        turn_type: ConversationTurn,
        active_topic: str = "",
    ) -> ResolvedContext:
        # Greetings never get history
        if _is_greeting(message):
            return ResolvedContext(
                messages=[],
                context_summary="",
                inject_history=False,
                active_topic="",
                continuity_note="",
            )

        # Explicit topic shifts get no history
        if _is_topic_shift(message):
            return ResolvedContext(
                messages=[],
                context_summary="",
                inject_history=False,
                active_topic="",
                continuity_note="",
            )

        # No history available
        if not session_messages:
            return ResolvedContext(
                messages=[],
                context_summary="",
                inject_history=False,
                active_topic=active_topic,
                continuity_note="",
            )

        relevant = _extract_relevant_messages(message, session_messages, turn_type, max_turns=3)

        if not relevant:
            return ResolvedContext(
                messages=[],
                context_summary="",
                inject_history=False,
                active_topic=active_topic,
                continuity_note="",
            )

        # Build a one-sentence summary of the active context
        first_user_msg = next((m["content"] for m in relevant if m.get("role") == "user"), "")
        context_summary = first_user_msg[:100].strip() if first_user_msg else ""

        continuity_note = _build_continuity_note(turn_type, active_topic)

        return ResolvedContext(
            messages=relevant,
            context_summary=context_summary,
            inject_history=True,
            active_topic=active_topic,
            continuity_note=continuity_note,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_resolver: ConversationContextResolver | None = None


def get_context_resolver() -> ConversationContextResolver:
    global _resolver
    if _resolver is None:
        _resolver = ConversationContextResolver()
    return _resolver
