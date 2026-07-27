"""The execution pipeline and controller.

The pipeline realises the canonical flow every cognitive request follows:

    receive → context → budget → resolve engine → execute → collect events →
    update ledger → emit metrics → complete

Engines never bypass it. The controller adds orchestration (pause/resume/cancel/
retry/timeout/escalate) over the pipeline. Neither performs cognition — they
coordinate a registered engine and record what happened (P1/RL6).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping

from ..contracts import CognitiveEvent, EventPriority, KernelServices
from .budget import RuntimeBudget
from .contracts import (
    BudgetUsage,
    ExecutionResult,
    ExecutionState,
    RecoveryStrategy,
)
from .errors import BudgetExceeded, EngineNotFound
from .execution import Execution
from .metrics import RuntimeMetrics
from .observability import RuntimeObservability
from .orchestrator import EngineOrchestrator

Transitioner = Callable[[Execution, ExecutionState], None]
Emitter = Callable[..., None]


def _invoke_with_timeout(fn: Callable[[], Any], timeout: float | None) -> tuple[str, Any]:
    """Run ``fn`` with an optional wall-clock timeout.

    Returns ("ok", value) | ("error", exc) | ("timeout", None). Timeouts rely on
    cooperative cancellation (a runaway thread is abandoned as a daemon).
    """
    if timeout is None:
        try:
            return ("ok", fn())
        except BaseException as exc:  # noqa: BLE001 - failure is a first-class outcome
            return ("error", exc)

    box: dict[str, Any] = {}

    def work() -> None:
        try:
            box["value"] = fn()
            box["ok"] = True
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc
            box["ok"] = False

    t = threading.Thread(target=work, name="runtime-exec", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return ("timeout", None)
    if box.get("ok"):
        return ("ok", box.get("value"))
    return ("error", box.get("error"))


class ExecutionPipeline:
    def __init__(
        self,
        services: KernelServices,
        orchestrator: EngineOrchestrator,
        metrics: RuntimeMetrics,
        observability: RuntimeObservability,
        emit: Emitter,
        transition: Transitioner,
    ) -> None:
        self._services = services
        self._orchestrator = orchestrator
        self._metrics = metrics
        self._obs = observability
        self._emit = emit
        self._transition = transition

    def run(self, execution: Execution) -> ExecutionResult:
        ex = execution
        ex.attempts += 1
        ex.started_at_logical = self._services.clock.tick()
        ex.started_at_wall = time.monotonic()
        self._transition(ex, ExecutionState.EXECUTING)

        # --- resolve engine (or wrap the request's task) ---------------- #
        try:
            if ex.request.task is not None:
                engine = self._orchestrator.for_task(ex.request.task)
            else:
                engine = self._orchestrator.resolve(ex.request.engine)
        except EngineNotFound as exc:
            return self._finalize(ex, ExecutionState.FAILED, error=str(exc))

        # --- effective timeout ------------------------------------------ #
        timeout = ex.policy.timeout_seconds
        t_rem = ex.budget.time_remaining()
        if t_rem is not None:
            timeout = t_rem if timeout is None else min(timeout, t_rem)

        # --- execute + collect events (bus window) ---------------------- #
        collected = {"n": 0}

        def _count(_e: CognitiveEvent) -> None:
            collected["n"] += 1

        sub = self._services.events.subscribe(
            "*", _count, predicate=lambda e: e.correlation_id == ex.correlation_id
        )
        status, payload = _invoke_with_timeout(
            lambda: engine.execute(ex.request.operation, ex.request.payload, ex.context),
            timeout,
        )
        sub.unsubscribe()
        self._services.observability.counter("runtime.events_collected", int(collected["n"]))

        # --- decide final state (runtime enforces outcome, P3/P5) ------- #
        # Steps/time are reported by the engine via the kernel context budget;
        # extended axes (memory/tokens/tools/simulations) via the runtime budget.
        kb = ex.context.budget
        steps_over = kb.max_steps > 0 and kb.consumed >= kb.max_steps
        time_over = status == "timeout" or ex.budget.time_exceeded()
        extra_over = ex.budget.exceeded() and not ex.budget.time_exceeded()
        if ex.context.cancellation.is_cancelled:
            return self._finalize(ex, ExecutionState.CANCELLED, error="cancelled")
        if time_over:
            return self._finalize(ex, ExecutionState.TIMED_OUT, error="time budget exceeded")
        if status == "error":
            return self._finalize(ex, ExecutionState.FAILED, error=repr(payload))
        if steps_over or extra_over:
            return self._finalize(
                ex, ExecutionState.FAILED, error=str(BudgetExceeded("budget exceeded"))
            )
        ex.value = payload
        return self._finalize(ex, ExecutionState.COMPLETED, value=payload)

    def _finalize(
        self,
        ex: Execution,
        state: ExecutionState,
        *,
        value: Any = None,
        error: str | None = None,
    ) -> ExecutionResult:
        self._transition(ex, state)
        ex.finished_at_logical = self._services.clock.tick()
        ex.finished_at_wall = time.monotonic()
        ex.error = error
        duration = ex.finished_at_wall - ex.started_at_wall
        queue_wait = ex.started_at_wall - ex.queued_at_wall
        self._metrics.on_finished(state, ex.request.engine, duration, ex.budget.utilization())
        usage = ex.budget.usage()
        return ExecutionResult(
            execution_id=ex.id,
            engine=ex.request.engine,
            state=state,
            value=value,
            error=error,
            attempts=ex.attempts,
            queued_at=ex.queued_at_logical,
            started_at=ex.started_at_logical,
            finished_at=ex.finished_at_logical,
            duration_seconds=duration,
            queue_seconds=queue_wait,
            budget=usage,
        )


class ExecutionController:
    """Orchestration over executions: pause/resume/cancel/retry/timeout/escalate."""

    def __init__(
        self,
        queue,
        executions: dict[str, Execution],
        metrics: RuntimeMetrics,
        observability: RuntimeObservability,
        checkpointer,
        emit: Emitter,
        transition: Transitioner,
        ledger_head: Callable[[], int],
    ) -> None:
        self._queue = queue
        self._executions = executions
        self._metrics = metrics
        self._obs = observability
        self._checkpointer = checkpointer
        self._emit = emit
        self._transition = transition
        self._ledger_head = ledger_head

    def cancel(self, execution_id: str, reason: str | None = None) -> bool:
        ex = self._executions.get(execution_id)
        if ex is None or ex.state in (
            ExecutionState.COMPLETED,
            ExecutionState.FAILED,
            ExecutionState.CANCELLED,
        ):
            return False
        cancelled = ex.cancel_subtree(reason)  # cooperative + directional (children only)
        for target in cancelled:
            if target.state in (ExecutionState.CREATED,) or target.state in (
                ExecutionState.QUEUED,
                ExecutionState.SCHEDULED,
                ExecutionState.WAITING,
                ExecutionState.SUSPENDED,
            ):
                self._queue.remove(target.id)
                if target.sm.can(ExecutionState.CANCELLED):
                    self._transition(target, ExecutionState.CANCELLED)
                    self._metrics.on_finished(ExecutionState.CANCELLED, target.request.engine, 0.0, 0.0)
            # An EXECUTING target has its token set; the pipeline finalises it as CANCELLED.
        self._emit("runtime.execution.cancel_requested", {"reason": reason or ""}, correlation_id=ex.correlation_id)
        return True

    def suspend(self, execution_id: str) -> bool:
        ex = self._executions.get(execution_id)
        if ex is None or not ex.sm.can(ExecutionState.SUSPENDED):
            return False
        self._queue.remove(ex.id)
        self._transition(ex, ExecutionState.SUSPENDED)
        # The runtime knows where it stopped — checkpoint the position (RL8).
        self._checkpointer.save(ex.snapshot(self._ledger_head()))
        return True

    def resume(self, execution_id: str) -> bool:
        ex = self._executions.get(execution_id)
        if ex is None or ex.state is not ExecutionState.SUSPENDED:
            return False
        self._transition(ex, ExecutionState.SCHEDULED)
        self._queue.enqueue(ex)
        return True

    def retry(self, execution_id: str) -> bool:
        ex = self._executions.get(execution_id)
        if ex is None or ex.state not in (ExecutionState.FAILED, ExecutionState.TIMED_OUT):
            return False
        if ex.attempts >= ex.policy.max_attempts:
            return False
        self._transition(ex, ExecutionState.SCHEDULED)
        self._metrics.on_retry()
        self._queue.enqueue(ex)
        return True

    def escalate(self, execution_id: str, reason: str) -> None:
        # Runtime signals; it never decides (halt-not-authorize, MeL6 / P10).
        ex = self._executions.get(execution_id)
        cid = ex.correlation_id if ex else execution_id
        self._emit(
            "runtime.escalation",
            {"execution_id": execution_id, "reason": reason},
            correlation_id=cid,
            priority=EventPriority.INTERRUPT,
        )
