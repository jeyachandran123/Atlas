"""Execution state machine — validated transitions (RL3).

Every execution transition is legal-checked and (by the pipeline) recorded to
the ledger, so no execution is ever left in a partial/ambiguous state.
"""

from __future__ import annotations

import threading

from .contracts import ExecutionState as S
from .errors import IllegalExecutionTransition

_TRANSITIONS: dict[S, frozenset[S]] = {
    S.CREATED: frozenset({S.QUEUED, S.CANCELLED}),
    S.QUEUED: frozenset({S.SCHEDULED, S.SUSPENDED, S.CANCELLED}),
    S.SCHEDULED: frozenset({S.EXECUTING, S.CANCELLED, S.SUSPENDED}),
    S.EXECUTING: frozenset(
        {S.WAITING, S.SUSPENDED, S.COMPLETED, S.FAILED, S.TIMED_OUT, S.CANCELLED}
    ),
    S.WAITING: frozenset({S.EXECUTING, S.CANCELLED, S.SUSPENDED}),
    S.SUSPENDED: frozenset({S.SCHEDULED, S.EXECUTING, S.CANCELLED}),
    S.TIMED_OUT: frozenset({S.SCHEDULED, S.FAILED, S.RECOVERED}),
    S.FAILED: frozenset({S.SCHEDULED, S.RECOVERED}),
    S.RECOVERED: frozenset({S.SCHEDULED, S.COMPLETED}),
    # Terminal states.
    S.COMPLETED: frozenset(),
    S.CANCELLED: frozenset(),
}


class ExecutionStateMachine:
    """One per execution. Thread-safe; records its own transition history."""

    def __init__(self) -> None:
        self._state = S.CREATED
        self._history: list[tuple[S, S]] = []
        self._lock = threading.Lock()

    @property
    def state(self) -> S:
        with self._lock:
            return self._state

    @property
    def history(self) -> tuple[tuple[S, S], ...]:
        with self._lock:
            return tuple(self._history)

    def can(self, target: S) -> bool:
        with self._lock:
            return target in _TRANSITIONS.get(self._state, frozenset())

    def transition(self, target: S) -> None:
        with self._lock:
            allowed = _TRANSITIONS.get(self._state, frozenset())
            if target not in allowed:
                raise IllegalExecutionTransition(
                    f"Illegal execution transition {self._state.value} -> {target.value}"
                )
            self._history.append((self._state, target))
            self._state = target
