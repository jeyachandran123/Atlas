"""Kernel lifecycle state machine.

Every transition is validated (illegal transitions raise). This mirrors an OS
bringing subsystems up and down in a controlled, observable manner. The machine
performs no cognition; it only guards the legality and ordering of kernel state
changes (Phase 2 Runtime lifecycle).
"""

from __future__ import annotations

import threading

from .contracts import KernelState
from .errors import LifecycleError

# Allowed transitions. Any transition not listed here is illegal.
_TRANSITIONS: dict[KernelState, frozenset[KernelState]] = {
    KernelState.CREATED: frozenset({KernelState.INITIALIZING, KernelState.FAILED}),
    KernelState.INITIALIZING: frozenset({KernelState.STARTING, KernelState.FAILED, KernelState.STOPPING}),
    KernelState.STARTING: frozenset({KernelState.RUNNING, KernelState.FAILED, KernelState.STOPPING}),
    KernelState.RUNNING: frozenset({KernelState.DEGRADED, KernelState.STOPPING, KernelState.FAILED}),
    KernelState.DEGRADED: frozenset({KernelState.RECOVERING, KernelState.RUNNING, KernelState.STOPPING, KernelState.FAILED}),
    KernelState.RECOVERING: frozenset({KernelState.RUNNING, KernelState.DEGRADED, KernelState.STOPPING, KernelState.FAILED}),
    KernelState.STOPPING: frozenset({KernelState.STOPPED, KernelState.FAILED}),
    KernelState.STOPPED: frozenset({KernelState.INITIALIZING}),  # cold restart
    KernelState.FAILED: frozenset({KernelState.RECOVERING, KernelState.STOPPING, KernelState.STOPPED}),
}


class LifecycleMachine:
    def __init__(self) -> None:
        self._state = KernelState.CREATED
        self._history: list[tuple[KernelState, KernelState]] = []
        self._lock = threading.Lock()

    @property
    def state(self) -> KernelState:
        with self._lock:
            return self._state

    @property
    def history(self) -> tuple[tuple[KernelState, KernelState], ...]:
        with self._lock:
            return tuple(self._history)

    def can_transition(self, target: KernelState) -> bool:
        with self._lock:
            return target in _TRANSITIONS.get(self._state, frozenset())

    def transition(self, target: KernelState) -> None:
        with self._lock:
            allowed = _TRANSITIONS.get(self._state, frozenset())
            if target not in allowed:
                raise LifecycleError(
                    f"Illegal transition {self._state.value} -> {target.value}"
                )
            self._history.append((self._state, target))
            self._state = target
