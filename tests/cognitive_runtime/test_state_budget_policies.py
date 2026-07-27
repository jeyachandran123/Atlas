"""Unit tests: state machine, budgets, policies, deterministic queue."""

from __future__ import annotations

import pytest

from app.cognitive_kernel.contracts import (
    EventPriority,
    ExecutionContext,
    SecurityContext,
    TraceInfo,
)
from app.cognitive_kernel.runtime.budget import BudgetManager, RuntimeBudget
from app.cognitive_kernel.runtime.contracts import (
    BudgetSpec,
    ExecutionPolicy,
    ExecutionRequest,
    ExecutionState as S,
    QueueKind,
)
from app.cognitive_kernel.runtime.errors import (
    IllegalExecutionTransition,
    PolicyViolation,
)
from app.cognitive_kernel.runtime.execution import Execution
from app.cognitive_kernel.runtime.policies import PolicyRegistry
from app.cognitive_kernel.runtime.queue import ExecutionQueue
from app.cognitive_kernel.runtime.state_machine import ExecutionStateMachine


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        correlation_id="c", identity_id="i",
        security=SecurityContext("p", "o"), trace=TraceInfo("t", "s"),
    )


def _exec(priority: EventPriority, kind: QueueKind = QueueKind.PRIORITY) -> Execution:
    req = ExecutionRequest(engine="e", priority=priority, kind=kind)
    return Execution("x", req, _ctx(), RuntimeBudget(BudgetSpec()), ExecutionPolicy(priority=priority))


# --- state machine --------------------------------------------------------- #


def test_state_machine_happy_path() -> None:
    m = ExecutionStateMachine()
    for target in (S.QUEUED, S.SCHEDULED, S.EXECUTING, S.COMPLETED):
        m.transition(target)
    assert m.state is S.COMPLETED and len(m.history) == 4


def test_state_machine_rejects_illegal() -> None:
    m = ExecutionStateMachine()
    m.transition(S.QUEUED)
    m.transition(S.SCHEDULED)
    m.transition(S.EXECUTING)
    m.transition(S.COMPLETED)
    with pytest.raises(IllegalExecutionTransition):
        m.transition(S.EXECUTING)  # terminal


def test_state_machine_suspend_resume() -> None:
    m = ExecutionStateMachine()
    m.transition(S.QUEUED)
    m.transition(S.SUSPENDED)  # parking a queued execution
    m.transition(S.SCHEDULED)
    assert m.state is S.SCHEDULED


# --- budgets --------------------------------------------------------------- #


def test_budget_step_dimension() -> None:
    b = RuntimeBudget(BudgetSpec(steps=3))
    assert not b.exceeded()
    b.consume("steps", 3)
    assert b.exceeded() and b.remaining("steps") == 0
    assert 0.0 < b.utilization() <= 1.0


def test_budget_time_dimension() -> None:
    b = RuntimeBudget(BudgetSpec(time_seconds=0.0))  # already past
    assert b.time_exceeded() and b.exceeded()


def test_budget_unbounded_axis() -> None:
    b = RuntimeBudget(BudgetSpec())
    b.consume("tokens", 10_000)
    assert not b.exceeded() and b.remaining("tokens") is None


def test_budget_manager_applies_defaults() -> None:
    mgr = BudgetManager(BudgetSpec(steps=5, tokens=100))
    b = mgr.create(BudgetSpec(steps=2))  # overrides steps, inherits tokens
    b.consume("steps", 2)
    assert b.exceeded() and b.remaining("tokens") == 100


# --- policies -------------------------------------------------------------- #


def test_policy_registry_defaults_and_custom() -> None:
    reg = PolicyRegistry()
    assert reg.get("default").name == "default"
    assert reg.get("critical").max_attempts == 3
    assert reg.get("critical").priority is EventPriority.HIGH
    with pytest.raises(PolicyViolation):
        reg.get("nonexistent")
    reg.register(ExecutionPolicy(name="mine", max_attempts=7))
    assert reg.get("mine").max_attempts == 7


# --- deterministic queue --------------------------------------------------- #


def test_queue_orders_by_priority_then_fifo() -> None:
    q = ExecutionQueue()
    low = _exec(EventPriority.LOW)
    hi = _exec(EventPriority.HIGH)
    norm1 = _exec(EventPriority.NORMAL)
    norm2 = _exec(EventPriority.NORMAL)
    for ex, name in ((low, "low"), (hi, "hi"), (norm1, "n1"), (norm2, "n2")):
        ex.id = name
        q.enqueue(ex)
    # HIGH first, then the two NORMALs in FIFO order, then LOW.
    assert q.peek_order() == ["hi", "n1", "n2", "low"]
    assert q.pop_ready().id == "hi"


def test_queue_background_is_demoted() -> None:
    q = ExecutionQueue()
    bg = _exec(EventPriority.INTERRUPT, kind=QueueKind.BACKGROUND)
    bg.id = "bg"
    normal = _exec(EventPriority.NORMAL)
    normal.id = "n"
    q.enqueue(bg)
    q.enqueue(normal)
    # Background sorts last even though its nominal priority is INTERRUPT.
    assert q.peek_order() == ["n", "bg"]


def test_queue_deferred_not_ready() -> None:
    q = ExecutionQueue()
    ex = _exec(EventPriority.NORMAL, kind=QueueKind.DEFERRED)
    ex.id = "d"
    ex.due = 10**9  # far future
    q.enqueue(ex)
    assert q.pop_ready() is None and q.depth() == 1
