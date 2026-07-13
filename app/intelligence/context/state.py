"""
Conversation Context State.

Structured state that replaces reliance on raw message history.
Maintained per-conversation, updated on every turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time


class TopicRelation(str, Enum):
    CONTINUATION = "continuation"
    RELATED_FOLLOWUP = "related_followup"
    SUBTOPIC = "subtopic"
    NEW_TOPIC = "new_topic"


@dataclass
class ConversationState:
    """Structured state for context resolution decisions."""

    current_topic: str = ""
    previous_topic: str = ""
    current_goal: str = ""
    active_persona: str = ""
    active_strategy: str = ""
    current_intent: str = ""
    topic_confidence: float = 0.0
    topic_started_at: float = field(default_factory=time)
    last_activity_at: float = field(default_factory=time)
    topic_turn_count: int = 0
    goal_completed: bool = False

    def shift_topic(self, new_topic: str, new_goal: str, confidence: float) -> None:
        """Transition to a new topic, archiving the previous one."""
        self.previous_topic = self.current_topic
        self.current_topic = new_topic
        self.current_goal = new_goal
        self.topic_confidence = confidence
        self.topic_started_at = time()
        self.last_activity_at = time()
        self.topic_turn_count = 1
        self.goal_completed = False

    def continue_topic(self, confidence: float) -> None:
        """Mark the current topic as continuing."""
        self.topic_confidence = confidence
        self.last_activity_at = time()
        self.topic_turn_count += 1

    def is_expired(self, max_idle_seconds: float = 300.0) -> bool:
        """Topic expires after sustained inactivity."""
        return (time() - self.last_activity_at) > max_idle_seconds


@dataclass
class ContextResolution:
    """Output of the context resolution engine for a single turn."""

    relation: TopicRelation
    relevant_message_indices: list[int] = field(default_factory=list)
    should_include_history: bool = True
    context_window_size: int = 6
    topic_changed: bool = False
    new_state: ConversationState = field(default_factory=ConversationState)
