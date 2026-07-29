"""The Simulation Manager (Phase 6 Ch8) — isolated branch lifecycle (PrL8/PrL13).

Creates and governs the tree of **isolated, in-memory, reference-only** simulation
branches. Isolation is guaranteed *by construction*: a branch holds only references
to canonical handles and drivers, and this manager has **no write path to
Cognitive State whatsoever** — a simulation therefore cannot mutate reality (PrL8).
Branches are bounded (a simulation budget, PrL13) and destroyed after completion
unless explicitly archived for audit (item 36); archived branches are tagged
hypothetical and never become belief (PrL9).
"""

from __future__ import annotations

import dataclasses
import threading
import uuid
from typing import Any, Sequence

from .contracts import BranchState, Driver, PredictionConfig, PredictionRequest, SimulationBranch
from .errors import BranchNotFoundError, SimulationBudgetExceeded


class SimulationManager:
    def __init__(self, config: PredictionConfig, clock: Any) -> None:
        self._config = config
        self._clock = clock
        self._lock = threading.RLock()
        self._open: dict[str, SimulationBranch] = {}
        self._archived: dict[str, SimulationBranch] = {}
        self._created = 0
        self._destroyed = 0
        self._archived_count = 0

    def create(self, request: PredictionRequest, references: Sequence[str], drivers: Sequence[Driver]) -> SimulationBranch:
        with self._lock:
            if len(self._open) >= self._config.max_open_branches:
                raise SimulationBudgetExceeded(
                    f"open branches {len(self._open)} >= budget {self._config.max_open_branches} (PrL13)"
                )
            bid = "sim-" + uuid.uuid4().hex
            branch = SimulationBranch(
                branch_id=bid, request_id=request.request_id, kind=request.kind,
                base_context=request.source or "present", created_seq=self._clock.current(),
                references=tuple(references), drivers=tuple(drivers),
                state=BranchState.OPEN, hypothetical=True,
            )
            self._open[bid] = branch
            self._created += 1
            return branch

    def mark_evaluated(self, branch_id: str) -> SimulationBranch:
        with self._lock:
            branch = self._open.get(branch_id)
            if branch is None:
                raise BranchNotFoundError(branch_id)
            evaluated = dataclasses.replace(branch, state=BranchState.EVALUATED)
            self._open[branch_id] = evaluated
            return evaluated

    def destroy(self, branch_id: str) -> bool:
        """Cleanup — the default terminal state (item 36); nothing leaks (PrL9)."""
        with self._lock:
            if self._open.pop(branch_id, None) is None:
                return False
            self._destroyed += 1
            return True

    def archive(self, branch_id: str) -> SimulationBranch:
        """Retain a branch for audit, tagged hypothetical (PrL15) — never as belief (PrL9)."""
        with self._lock:
            branch = self._open.pop(branch_id, None)
            if branch is None:
                raise BranchNotFoundError(branch_id)
            archived = dataclasses.replace(branch, state=BranchState.ARCHIVED)
            self._archived[branch_id] = archived
            self._archived_count += 1
            return archived

    def is_open(self, branch_id: str) -> bool:
        with self._lock:
            return branch_id in self._open

    def open_count(self) -> int:
        with self._lock:
            return len(self._open)

    def cleanup_all(self) -> int:
        """Destroy every open branch (item 36) — used on stop/recovery."""
        with self._lock:
            n = len(self._open)
            self._open.clear()
            self._destroyed += n
            return n

    def counts(self) -> tuple[int, int, int, int]:
        with self._lock:
            return self._created, self._destroyed, self._archived_count, len(self._open)
