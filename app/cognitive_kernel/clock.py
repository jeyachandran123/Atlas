"""Logical clock — the authoritative time of the mind (RL4).

Logical time is a monotonic total order over cognitive operations. It, not the
wall clock, defines *before/after*, causality, replay order, and checkpoint
positions (Phase 2 Ch8). Wall-clock timestamps on events are advisory only.
"""

from __future__ import annotations

import threading

from .contracts import LogicalClock


class MonotonicLogicalClock(LogicalClock):
    """A thread-safe, strictly-increasing counter. Deterministic under replay."""

    __slots__ = ("_value", "_lock")

    def __init__(self, start: int = 0) -> None:
        self._value = start
        self._lock = threading.Lock()

    def tick(self) -> int:
        with self._lock:
            self._value += 1
            return self._value

    def current(self) -> int:
        with self._lock:
            return self._value
