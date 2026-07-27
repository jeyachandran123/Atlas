"""Cancellation, timeout, retry, suspend/resume+checkpoint, recovery, budgets."""

from __future__ import annotations

import time

from app.cognitive_kernel.runtime import ExecutionRequest, ExecutionState
from app.cognitive_kernel.runtime.contracts import BudgetSpec

from ._rt import make_runtime


def test_cancel_queued_execution() -> None:
    kernel, rt = make_runtime()
    try:
        ran: list[int] = []
        h = rt.submit(ExecutionRequest(engine="calc", task=lambda ctx: ran.append(1)))
        assert rt.cancel(h.id) is True
        assert rt.drain() == 0  # cancelled work is not dispatched
        assert h.state is ExecutionState.CANCELLED and ran == []
        assert rt.metrics().cancelled == 1 and rt.metrics().completed == 0
    finally:
        rt.stop()


def test_nested_cancellation_propagates_to_children() -> None:
    kernel, rt = make_runtime()
    try:
        parent = rt.submit(ExecutionRequest(engine="p", task=lambda ctx: 1))
        child = rt.submit(ExecutionRequest(engine="c", task=lambda ctx: 1, parent_id=parent.id))
        assert rt.cancel(parent.id) is True
        assert parent.state is ExecutionState.CANCELLED
        assert child.state is ExecutionState.CANCELLED  # directional propagation
    finally:
        rt.stop()


def test_child_cancel_does_not_cancel_parent() -> None:
    kernel, rt = make_runtime()
    try:
        parent = rt.submit(ExecutionRequest(engine="p", task=lambda ctx: 1))
        child = rt.submit(ExecutionRequest(engine="c", task=lambda ctx: 1, parent_id=parent.id))
        assert rt.cancel(child.id) is True
        assert child.state is ExecutionState.CANCELLED
        assert parent.state is ExecutionState.QUEUED  # parent unaffected
    finally:
        rt.stop()


def test_timeout_marks_timed_out() -> None:
    kernel, rt = make_runtime()
    try:
        def slow(ctx):
            time.sleep(0.4)
            return "never"

        h = rt.submit(ExecutionRequest(engine="slow", task=slow, budget=BudgetSpec(time_seconds=0.05)))
        rt.drain()
        assert h.result().state is ExecutionState.TIMED_OUT
        assert rt.metrics().timed_out == 1
    finally:
        rt.stop()


def test_retry_succeeds_after_transient_failure() -> None:
    kernel, rt = make_runtime()
    try:
        attempts = {"n": 0}

        def flaky(ctx):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise ValueError("transient")
            return "ok"

        h = rt.submit(ExecutionRequest(engine="flaky", task=flaky, policy="critical"))
        rt.drain()
        assert h.result().state is ExecutionState.FAILED
        assert rt.retry(h.id) is True
        rt.drain()
        final = h.result()
        assert final.state is ExecutionState.COMPLETED and final.value == "ok" and final.attempts == 2
        assert rt.metrics().retries == 1
    finally:
        rt.stop()


def test_retry_exhausted_returns_false() -> None:
    kernel, rt = make_runtime()
    try:
        def always_fail(ctx):
            raise RuntimeError("boom")

        h = rt.submit(ExecutionRequest(engine="x", task=always_fail))  # default: max_attempts=1
        rt.drain()
        assert h.result().state is ExecutionState.FAILED
        assert rt.retry(h.id) is False  # no attempts left
    finally:
        rt.stop()


def test_suspend_checkpoints_then_resume_completes() -> None:
    kernel, rt = make_runtime()
    try:
        h = rt.submit(ExecutionRequest(engine="calc", task=lambda ctx: 99))
        assert rt.suspend(h.id) is True
        assert h.state is ExecutionState.SUSPENDED
        # The runtime knows where execution stopped — a checkpoint was written.
        snap = rt._recovery.restore(h.id)  # noqa: SLF001 - recovery introspection
        assert snap is not None and snap.state is ExecutionState.SUSPENDED
        assert rt.resume_execution(h.id) is True
        rt.drain()
        assert h.result().state is ExecutionState.COMPLETED and h.result().value == 99
    finally:
        rt.stop()


def test_step_budget_exceeded_fails() -> None:
    kernel, rt = make_runtime()
    try:
        def greedy(ctx):
            ctx.budget.consume(5)  # engine reports 5 steps against a 2-step budget
            return "done"

        h = rt.submit(ExecutionRequest(engine="g", task=greedy, budget=BudgetSpec(steps=2)))
        rt.drain()
        assert h.result().state is ExecutionState.FAILED
        assert "budget" in (h.result().error or "").lower()
    finally:
        rt.stop()


def test_recovery_replays_and_dedups_completed() -> None:
    kernel, rt = make_runtime()
    try:
        handles = [rt.submit(ExecutionRequest(engine="e", task=lambda ctx: 1)) for _ in range(3)]
        rt.drain()
        assert rt.metrics().completed == 3
        replayed = rt.recover()  # verify integrity + ledger replay (RL8)
        assert replayed > 0 and kernel.services().ledger.verify()
        for h in handles:
            assert rt.has_executed(h.id)  # idempotency: known-completed
        # Recovery did not re-run anything (no duplicated execution).
        assert rt.metrics().completed == 3
    finally:
        rt.stop()


def test_escalate_emits_signal_but_never_decides() -> None:
    kernel, rt = make_runtime()
    try:
        received: list[str] = []
        kernel.services().events.subscribe(
            "runtime.escalation", lambda e: received.append(e.payload.get("reason", ""))
        )
        h = rt.submit(ExecutionRequest(engine="calc", task=lambda ctx: 1))
        rt.escalate(h.id, "low_confidence")
        assert received == ["low_confidence"]  # runtime signals; it does not decide (MeL6)
    finally:
        rt.stop()
