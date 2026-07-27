"""The Execution aggregate — a single unit of coordinated work.

An ``Execution`` binds together a request, a kernel :class:`ExecutionContext`, a
state machine, a runtime budget, and a place in the execution *hierarchy*
(parent/children). It supports snapshots (for checkpoints) and hierarchical
cancellation propagation. It is a runtime aggregate (mutable, lock-guarded) —
NOT a value object — but it holds the frozen kernel context unchanged (OL8: the
kernel is not modified; hierarchy is layered on top).
"""

from __future__ import annotations

import threading
import time

from ..contracts import ExecutionContext
from .budget import RuntimeBudget
from .contracts import (
    ExecutionPolicy,
    ExecutionRequest,
    ExecutionSnapshot,
    ExecutionState,
    QueueKind,
)
from .state_machine import ExecutionStateMachine


class Execution:
    __slots__ = (
        "id",
        "request",
        "context",
        "budget",
        "policy",
        "sm",
        "parent",
        "children",
        "attempts",
        "kind",
        "priority",
        "due",
        "enqueue_seq",
        "queued_at_logical",
        "started_at_logical",
        "finished_at_logical",
        "queued_at_wall",
        "started_at_wall",
        "finished_at_wall",
        "value",
        "error",
        "_lock",
    )

    def __init__(
        self,
        execution_id: str,
        request: ExecutionRequest,
        context: ExecutionContext,
        budget: RuntimeBudget,
        policy: ExecutionPolicy,
        parent: "Execution | None" = None,
    ) -> None:
        self.id = execution_id
        self.request = request
        self.context = context
        self.budget = budget
        self.policy = policy
        self.sm = ExecutionStateMachine()
        self.parent = parent
        self.children: list["Execution"] = []
        self.attempts = 0
        self.kind: QueueKind = request.kind
        self.priority = policy.priority if request.priority is None else request.priority
        self.due = time.monotonic() + request.delay_seconds
        self.enqueue_seq = 0
        self.queued_at_logical = 0
        self.started_at_logical = 0
        self.finished_at_logical = 0
        self.queued_at_wall = 0.0
        self.started_at_wall = 0.0
        self.finished_at_wall = 0.0
        self.value = None
        self.error: str | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> ExecutionState:
        return self.sm.state

    @property
    def correlation_id(self) -> str:
        return self.context.correlation_id

    def add_child(self, child: "Execution") -> None:
        with self._lock:
            self.children.append(child)

    def snapshot(self, ledger_head: int) -> ExecutionSnapshot:
        """Immutable record of where this execution stands (RL8)."""
        return ExecutionSnapshot(
            execution_id=self.id,
            engine=self.request.engine,
            operation=self.request.operation,
            state=self.state,
            attempts=self.attempts,
            parent_id=self.parent.id if self.parent else None,
            correlation_id=self.correlation_id,
            ledger_head=ledger_head,
        )

    def cancel_subtree(self, reason: str | None = None) -> list["Execution"]:
        """Cooperatively cancel this execution and (if the policy permits) all
        descendants. Returns the list of executions whose tokens were cancelled.
        Cancellation is directional: a child cancel never cancels its parent.
        """
        cancelled: list["Execution"] = [self]
        self.context.cancellation.cancel(reason)
        if self.policy.cancel_propagates:
            with self._lock:
                children = list(self.children)
            for child in children:
                cancelled.extend(child.cancel_subtree(reason))
        return cancelled
