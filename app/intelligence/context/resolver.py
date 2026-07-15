"""
Conversation Context Resolution Engine.

Decides WHICH memory should be visible to the LLM.
This is NOT a memory store — it is a context filter.

Responsibilities:
1. Topic detection and tracking
2. Topic similarity comparison
3. Context window selection (only relevant messages)
4. Context reset detection (greetings, acknowledgments)
5. Goal continuity (preserve or close goals)
6. Context expiration (old topics fade)
7. Structured conversation state
8. Smart follow-up detection
9. Topic isolation (no cross-contamination)

The LLM never decides which history to use.
Atlas decides that here, before prompt composition.
"""

from __future__ import annotations

from typing import Optional

from loguru import logger

from app.intelligence.context.state import (
    ContextResolution,
    ConversationState,
    TopicRelation,
)
from app.intelligence.context.topic import (
    classify_topic_relation,
    extract_topic_keywords,
    is_followup_message,
    is_reset_message,
)


class ContextResolutionEngine:
    """
    Resolves which conversation history is relevant for the current turn.

    Called AFTER memory is loaded, BEFORE prompt composition.
    Filters session_messages to only include topically relevant turns.
    """

    def __init__(self, topic_expiry_seconds: float = 300.0):
        self._topic_expiry = topic_expiry_seconds
        # Per-conversation state cache (conversation_id → state)
        self._states: dict[str, ConversationState] = {}

    def get_state(self, conversation_id: str) -> ConversationState:
        if conversation_id not in self._states:
            self._states[conversation_id] = ConversationState()
        return self._states[conversation_id]

    def resolve(
        self,
        message: str,
        session_messages: list[dict],
        conversation_id: str,
        intent: str = "",
    ) -> ContextResolution:
        """
        Main entry point. Determines which messages to include in context.

        Args:
            message: Current user message
            session_messages: All loaded session messages (unfiltered)
            conversation_id: Conversation identifier
            intent: Detected intent (optional, for goal tracking)

        Returns:
            ContextResolution with filtered message indices and updated state
        """
        state = self.get_state(conversation_id)

        # ── 1. Context Reset Detection ────────────────────────────────────────
        if is_reset_message(message):
            return self._handle_reset(state, conversation_id)

        # ── 2. Topic Expiration ───────────────────────────────────────────────
        if state.current_topic and state.is_expired(self._topic_expiry):
            logger.debug(
                f"Topic expired for conversation {conversation_id}: '{state.current_topic}'"
            )
            state.shift_topic("", "", 0.0)

        # ── 3. Topic Classification ───────────────────────────────────────────
        current_keywords = extract_topic_keywords(state.current_topic) if state.current_topic else []
        relation, confidence = classify_topic_relation(
            message, current_keywords, session_messages
        )

        # ── 4. Update State Based on Classification ───────────────────────────
        new_keywords = extract_topic_keywords(message)
        topic_summary = " ".join(new_keywords[:8]) if new_keywords else message[:50]

        if relation == TopicRelation.NEW_TOPIC:
            state.shift_topic(
                new_topic=topic_summary,
                new_goal=self._infer_goal(message, intent),
                confidence=confidence,
            )
        elif relation == TopicRelation.CONTINUATION:
            state.continue_topic(confidence)
            # Enrich topic with new keywords
            if new_keywords:
                combined = state.current_topic + " " + " ".join(new_keywords[:4])
                state.current_topic = combined[:200]
        elif relation == TopicRelation.RELATED_FOLLOWUP:
            state.continue_topic(confidence)
        elif relation == TopicRelation.SUBTOPIC:
            state.continue_topic(confidence)
            state.current_topic = topic_summary

        state.current_intent = intent
        state.topic_confidence = confidence

        # ── 5. Context Window Selection ───────────────────────────────────────
        relevant_indices = self._select_relevant_messages(
            message, session_messages, relation, state
        )

        # ── 6. Determine context window size ──────────────────────────────────
        if relation == TopicRelation.NEW_TOPIC:
            window_size = 0  # No history for new topics
        elif relation == TopicRelation.SUBTOPIC:
            window_size = 2  # Minimal context
        elif relation == TopicRelation.RELATED_FOLLOWUP:
            window_size = 4
        else:
            window_size = 6  # Full continuation

        return ContextResolution(
            relation=relation,
            relevant_message_indices=relevant_indices,
            should_include_history=relation != TopicRelation.NEW_TOPIC,
            context_window_size=window_size,
            topic_changed=relation == TopicRelation.NEW_TOPIC,
            new_state=state,
        )

    def filter_messages(
        self,
        session_messages: list[dict],
        resolution: ContextResolution,
    ) -> list[dict]:
        """
        Apply the resolution to filter session messages.
        Returns only the messages that should be visible to the LLM.
        """
        if not resolution.should_include_history:
            return []

        if not resolution.relevant_message_indices:
            # Fallback: use last N messages based on window size
            return session_messages[-resolution.context_window_size:]

        # Return messages at the resolved indices
        filtered = []
        for idx in resolution.relevant_message_indices:
            if 0 <= idx < len(session_messages):
                filtered.append(session_messages[idx])

        # Cap at window size
        return filtered[-resolution.context_window_size:]

    # ── Private Methods ───────────────────────────────────────────────────────

    def _handle_reset(
        self, state: ConversationState, conversation_id: str
    ) -> ContextResolution:
        """
        Handle reset messages (greetings, acknowledgments).
        Marks goal as done but preserves topic state so the NEXT message
        can still be classified as a continuation if it references prior context.
        """
        state.goal_completed = True
        # Preserve current_topic so the next message can still match it.
        # Only return empty context for this greeting turn itself.
        return ContextResolution(
            relation=TopicRelation.NEW_TOPIC,
            relevant_message_indices=[],
            should_include_history=False,
            context_window_size=0,
            topic_changed=False,
            new_state=state,
        )

    def _select_relevant_messages(
        self,
        message: str,
        session_messages: list[dict],
        relation: TopicRelation,
        state: ConversationState,
    ) -> list[int]:
        """
        Select which message indices are relevant to the current topic.
        Uses keyword overlap to score each message's relevance.
        """
        if not session_messages:
            return []

        if relation == TopicRelation.NEW_TOPIC:
            return []

        # For continuations and follow-ups, score each message by topic relevance
        topic_keywords = extract_topic_keywords(state.current_topic) if state.current_topic else []
        message_keywords = extract_topic_keywords(message)
        reference_keywords = set(topic_keywords + message_keywords)

        if not reference_keywords:
            # No keywords to match — return recent messages
            return list(range(max(0, len(session_messages) - 6), len(session_messages)))

        scored: list[tuple[int, float]] = []
        for idx, msg in enumerate(session_messages):
            content = msg.get("content", "")
            msg_keywords = set(extract_topic_keywords(content))
            if not msg_keywords:
                # Keep messages with no keywords if they're recent (likely structural)
                recency_bonus = 0.3 if idx >= len(session_messages) - 2 else 0.0
                scored.append((idx, recency_bonus))
                continue
            overlap = len(msg_keywords & reference_keywords)
            score = overlap / max(len(reference_keywords), 1)
            # Recency bonus: more recent messages get a boost
            position_ratio = idx / max(len(session_messages) - 1, 1)
            score += position_ratio * 0.2
            scored.append((idx, score))

        # Filter to messages with meaningful relevance
        threshold = 0.1
        relevant = [idx for idx, score in scored if score >= threshold]

        # Always include the most recent pair (last user + assistant) for coherence
        if session_messages:
            last_idx = len(session_messages) - 1
            if last_idx not in relevant:
                relevant.append(last_idx)
            if last_idx - 1 >= 0 and (last_idx - 1) not in relevant:
                relevant.append(last_idx - 1)

        return sorted(relevant)

    def _infer_goal(self, message: str, intent: str) -> str:
        """Infer the user's goal from the message and intent."""
        if intent:
            return f"{intent}: {message[:60]}"
        return message[:80]


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: ContextResolutionEngine | None = None


def get_context_resolution_engine() -> ContextResolutionEngine:
    global _engine
    if _engine is None:
        _engine = ContextResolutionEngine()
    return _engine
