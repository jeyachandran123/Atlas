"""
Goal Memory.

Stores goals across conversation turns so Atlas can answer
relative to long-running objectives rather than isolated messages.

"I'm building Atlas."
→ Later: "Should I use DeepSeek?"
→ Goal context: Building Atlas → answer relative to that goal.

In-process store (per-process, per-conversation).
Designed so a persistent backend (Redis/DB) can be swapped in
by replacing this implementation without changing the interface.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone

from app.intelligence.reasoning.interfaces import AbstractGoalMemory
from app.intelligence.reasoning.models import (
    ActiveGoalContext,
    GoalMemoryEntry,
    GoalType,
    InferredGoal,
)

# Signals that indicate the user is starting a new, unrelated goal
_TOPIC_CHANGE_SIGNALS = [
    "new topic", "different question", "forget that", "let's talk about",
    "change subject", "actually", "never mind",
]

# GoalTypes that are strong enough to persist as active goals
_PERSISTENT_GOAL_TYPES = {
    GoalType.BUILD, GoalType.PLAN, GoalType.IMPROVE,
    GoalType.FIND_AND_FIX, GoalType.RESEARCH,
}


class GoalMemory(AbstractGoalMemory):
    """
    In-process goal memory store.
    Keyed by (user_id, conversation_id).
    Thread-safe for single-process use (asyncio event loop).
    """

    def __init__(self) -> None:
        # {(user_id, conversation_id): [GoalMemoryEntry, ...]}
        self._store: dict[tuple[str, str], list[GoalMemoryEntry]] = defaultdict(list)

    def get_active_context(
        self,
        user_id: str,
        conversation_id: str,
        current_goal: InferredGoal,
    ) -> ActiveGoalContext:
        key = (user_id, conversation_id)
        entries = self._store[key]

        if not entries:
            return ActiveGoalContext(
                current_goal=current_goal,
                prior_goals=[],
                goal_continuity=False,
            )

        # Find the most recent active goal
        active_entries = [e for e in entries if e.is_active]
        if not active_entries:
            return ActiveGoalContext(
                current_goal=current_goal,
                prior_goals=list(entries[-3:]),
                goal_continuity=False,
            )

        last_active = active_entries[-1]

        # Detect topic change
        raw = current_goal.raw_message.lower()
        topic_changed = any(sig in raw for sig in _TOPIC_CHANGE_SIGNALS)

        # Detect goal continuity: same goal type or message references prior goal
        same_type = last_active.goal.goal_type == current_goal.goal_type
        goal_continuity = same_type and not topic_changed

        # If topic changed, deactivate prior goals
        if topic_changed:
            for entry in active_entries:
                entry.is_active = False

        return ActiveGoalContext(
            current_goal=current_goal,
            prior_goals=list(entries[-5:]),
            goal_continuity=goal_continuity,
            continuity_reason=(
                f"Continuing '{last_active.goal.goal_type.value}' goal"
                if goal_continuity else ""
            ),
        )

    def store(
        self,
        user_id: str,
        conversation_id: str,
        goal: InferredGoal,
        turn_index: int,
    ) -> None:
        # Only persist goals that are meaningful enough to remember
        if goal.goal_type not in _PERSISTENT_GOAL_TYPES:
            return

        key = (user_id, conversation_id)
        entry = GoalMemoryEntry(
            goal_id=str(uuid.uuid4())[:8],
            conversation_id=conversation_id,
            user_id=user_id,
            goal=goal,
            turn_index=turn_index,
            is_active=True,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._store[key].append(entry)

        # Keep only last 10 goals per conversation
        if len(self._store[key]) > 10:
            self._store[key] = self._store[key][-10:]

    def clear(self, user_id: str, conversation_id: str) -> None:
        self._store.pop((user_id, conversation_id), None)


# ── Singleton ─────────────────────────────────────────────────────────────────

_memory: GoalMemory | None = None


def get_goal_memory() -> GoalMemory:
    global _memory
    if _memory is None:
        _memory = GoalMemory()
    return _memory
