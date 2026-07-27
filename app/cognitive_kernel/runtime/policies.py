"""Execution policies — configurable, loaded by the runtime, obeyed by engines.

Policies govern priority, retry, timeout, isolation, recovery, and cancellation
propagation. They are immutable value objects held in a registry; the runtime
resolves a request's named policy and enforces it. New policies extend the
registry without code changes to the pipeline.
"""

from __future__ import annotations

import threading

from ..contracts import EventPriority
from .contracts import ExecutionPolicy, RecoveryStrategy
from .errors import PolicyViolation

_DEFAULTS: tuple[ExecutionPolicy, ...] = (
    ExecutionPolicy(name="default"),
    ExecutionPolicy(
        name="critical",
        priority=EventPriority.HIGH,
        max_attempts=3,
        retry_backoff_seconds=0.0,
        recovery=RecoveryStrategy.RETRY,
    ),
    ExecutionPolicy(
        name="interrupt",
        priority=EventPriority.INTERRUPT,
        max_attempts=1,
    ),
    ExecutionPolicy(
        name="background",
        priority=EventPriority.BACKGROUND,
        max_attempts=1,
    ),
    ExecutionPolicy(
        name="resumable",
        max_attempts=2,
        recovery=RecoveryStrategy.CHECKPOINT,
    ),
)


class PolicyRegistry:
    def __init__(self) -> None:
        self._policies: dict[str, ExecutionPolicy] = {p.name: p for p in _DEFAULTS}
        self._lock = threading.Lock()

    def register(self, policy: ExecutionPolicy) -> None:
        with self._lock:
            self._policies[policy.name] = policy

    def get(self, name: str) -> ExecutionPolicy:
        with self._lock:
            if name not in self._policies:
                raise PolicyViolation(f"Unknown execution policy: {name!r}")
            return self._policies[name]

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._policies.keys())
