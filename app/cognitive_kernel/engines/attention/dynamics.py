"""Attention dynamics — novelty (from history), fatigue, and inhibition-of-return.

These are ephemeral (reconstructable) dynamics; the durable attention record lives
in Cognitive State R3. Fatigue implements the vigilance decrement (AL14);
inhibition-of-return promotes novelty by penalising a just-defocused target for
one cycle (Phase 3, Ch0 item 17).
"""

from __future__ import annotations

import threading
from collections import deque

from .contracts import AttentionConfig


class FocusHistory:
    """Bounded trajectory of recently-focused targets (AL26 attention history)."""

    def __init__(self, window: int) -> None:
        self._window = window
        self._recent: deque[str] = deque(maxlen=window)
        self._lock = threading.Lock()

    def record(self, targets: list[str]) -> None:
        with self._lock:
            for t in targets:
                self._recent.append(t)

    def novelty(self, target: str) -> float:
        with self._lock:
            if not self._window:
                return 1.0
            seen = sum(1 for t in self._recent if t == target)
            return max(0.0, 1.0 - seen / self._window)

    def recent(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._recent)

    def clear(self) -> None:
        with self._lock:
            self._recent.clear()


class FatigueModel:
    """Sustained effortful attention fatigues; idle attention recovers (AL14)."""

    def __init__(self) -> None:
        self._fatigue = 0.0
        self._lock = threading.Lock()

    @property
    def value(self) -> float:
        with self._lock:
            return self._fatigue

    def effort(self, coalition_size: int, config: AttentionConfig) -> None:
        with self._lock:
            load = coalition_size / max(1, config.coalition_capacity)
            self._fatigue = min(1.0, self._fatigue + config.fatigue_per_cycle * load)

    def recover(self, config: AttentionConfig) -> None:
        with self._lock:
            self._fatigue = max(0.0, self._fatigue - config.fatigue_recovery)
