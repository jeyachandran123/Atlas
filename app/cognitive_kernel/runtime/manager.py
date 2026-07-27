"""The Cognitive Runtime Manager — owner of every cognitive execution.

Coordinates cognition; performs none of it. It composes the kernel services with
the runtime's pipeline, controller, queue, budgets, policies, orchestrator,
metrics, observability, checkpointing, recovery, and health — and drives the
canonical execution pipeline. Engines only *register* and *submit*; they never
call one another (P1/RL6). Deterministic by default (manual ``drain``); an
optional background pump provides real-time coordination (RL1).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from ..contracts import (
    EventPriority,
    ExecutionBudget,
    HealthReport,
    HealthStatus,
    KernelServices,
    SecurityContext,
)
from .budget import BudgetManager
from .contracts import (
    BudgetSpec,
    ExecutableEngine,
    ExecutionRequest,
    ExecutionResult,
    ExecutionState,
    QueueKind,
    RuntimeHealth,
    RuntimeHealthReport,
    RuntimeLifecycleState,
    RuntimeMetricsSnapshot,
)
from .errors import RuntimeStateError
from .execution import Execution
from .metrics import RuntimeMetrics
from .observability import RuntimeObservability
from .orchestrator import EngineOrchestrator
from .pipeline import ExecutionController, ExecutionPipeline
from .policies import PolicyRegistry
from .queue import ExecutionQueue
from .recovery import ExecutionCheckpointer, ExecutionRecovery

_HEALTH_MAP = {
    RuntimeHealth.HEALTHY: HealthStatus.HEALTHY,
    RuntimeHealth.BUSY: HealthStatus.HEALTHY,
    RuntimeHealth.DEGRADED: HealthStatus.DEGRADED,
    RuntimeHealth.RECOVERING: HealthStatus.DEGRADED,
    RuntimeHealth.UNAVAILABLE: HealthStatus.UNHEALTHY,
}


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    default_budget: BudgetSpec = field(default_factory=BudgetSpec)
    background_pump: bool = False
    pump_interval: float = 0.005
    busy_active_threshold: int = 8
    busy_queue_threshold: int = 32


class RuntimeExecutionHandle:
    __slots__ = ("_runtime", "_execution")

    def __init__(self, runtime: "CognitiveRuntime", execution: Execution) -> None:
        self._runtime = runtime
        self._execution = execution

    @property
    def id(self) -> str:
        return self._execution.id

    @property
    def state(self) -> ExecutionState:
        return self._execution.state

    def result(self, timeout: float | None = None) -> ExecutionResult:
        return self._runtime._result_for(self._execution, timeout)


class CognitiveRuntime:
    def __init__(self, services: KernelServices, config: RuntimeConfig | None = None) -> None:
        self._services = services
        self._config = config or RuntimeConfig()
        self._lifecycle = RuntimeLifecycleState.CREATED
        self._recovering = 0

        # Runtime subsystems (built on kernel services).
        self._budgets = BudgetManager(self._config.default_budget)
        self._policies = PolicyRegistry()
        self._queue = ExecutionQueue()
        self._orchestrator = EngineOrchestrator()
        self._metrics = RuntimeMetrics()
        self._obs = RuntimeObservability(services.observability)
        self._checkpointer = ExecutionCheckpointer(services)
        self._recovery = ExecutionRecovery(services, self._checkpointer)

        self._executions: dict[str, Execution] = {}
        self._results: dict[str, ExecutionResult] = {}
        self._completed_ids: set[str] = set()
        self._lock = threading.RLock()

        self._pipeline = ExecutionPipeline(
            services, self._orchestrator, self._metrics, self._obs, self._emit, self._transition
        )
        self._controller = ExecutionController(
            self._queue, self._executions, self._metrics, self._obs,
            self._checkpointer, self._emit, self._transition, services.ledger.head,
        )

        self._pump_thread: threading.Thread | None = None
        self._pump_running = False
        services.health.register_probe("runtime", self._health_probe)

    # --- Runtime Manager lifecycle --------------------------------------- #

    @property
    def lifecycle(self) -> RuntimeLifecycleState:
        return self._lifecycle

    def start(self) -> None:
        with self._lock:
            if self._lifecycle is RuntimeLifecycleState.RUNNING:
                return
            self._lifecycle = RuntimeLifecycleState.RUNNING
        if self._config.background_pump:
            self._start_pump()

    def pause(self) -> None:
        with self._lock:
            if self._lifecycle is RuntimeLifecycleState.RUNNING:
                self._lifecycle = RuntimeLifecycleState.PAUSED

    def resume(self) -> None:
        with self._lock:
            if self._lifecycle is RuntimeLifecycleState.PAUSED:
                self._lifecycle = RuntimeLifecycleState.RUNNING

    def stop(self) -> None:
        with self._lock:
            if self._lifecycle is RuntimeLifecycleState.STOPPED:
                return
            self._lifecycle = RuntimeLifecycleState.DRAINING
        self._stop_pump()
        # Graceful drain of remaining ready work.
        self._lifecycle = RuntimeLifecycleState.RUNNING
        self.drain()
        with self._lock:
            self._lifecycle = RuntimeLifecycleState.STOPPED

    # --- submission & the RuntimeApi surface ----------------------------- #

    def register_engine(self, name: str, engine: ExecutableEngine) -> None:
        self._orchestrator.register(name, engine)

    def submit(self, request: ExecutionRequest) -> RuntimeExecutionHandle:
        if self._lifecycle is RuntimeLifecycleState.STOPPED:
            raise RuntimeStateError("Runtime is stopped; cannot accept executions.")
        policy = self._policies.get(request.policy)
        budget = self._budgets.create(request.budget)
        parent = self._executions.get(request.parent_id) if request.parent_id else None
        context = self._make_context(request, policy, parent)
        ex = Execution(uuid.uuid4().hex, request, context, budget, policy, parent)
        with self._lock:
            self._executions[ex.id] = ex
        if parent is not None:
            parent.add_child(ex)
        self._obs.open(
            ex.id, ex.correlation_id, ex.context.trace.trace_id,
            parent.id if parent else None, request.engine,
        )
        ex.queued_at_logical = self._services.clock.tick()
        ex.queued_at_wall = time.monotonic()
        self._transition(ex, ExecutionState.QUEUED)
        self._metrics.on_submitted()
        self._queue.enqueue(ex)
        return RuntimeExecutionHandle(self, ex)

    def cancel(self, execution_id: str, reason: str | None = None) -> bool:
        return self._controller.cancel(execution_id, reason)

    def status(self, execution_id: str) -> ExecutionState:
        ex = self._executions.get(execution_id)
        if ex is None:
            raise RuntimeStateError(f"Unknown execution: {execution_id}")
        return ex.state

    # Controller delegation.
    def suspend(self, execution_id: str) -> bool:
        return self._controller.suspend(execution_id)

    def resume_execution(self, execution_id: str) -> bool:
        return self._controller.resume(execution_id)

    def retry(self, execution_id: str) -> bool:
        return self._controller.retry(execution_id)

    def escalate(self, execution_id: str, reason: str) -> None:
        self._controller.escalate(execution_id, reason)

    # --- dispatch (the execution loop) ----------------------------------- #

    def run_pending(self, now: float | None = None, max_items: int | None = None) -> int:
        if self._lifecycle is not RuntimeLifecycleState.RUNNING:
            return 0
        ran = 0
        while True:
            ex = self._queue.pop_ready(now)
            if ex is None:
                break
            self._dispatch(ex)
            ran += 1
            if max_items is not None and ran >= max_items:
                break
        return ran

    def drain(self, now: float | None = None) -> int:
        total = 0
        while self._lifecycle is RuntimeLifecycleState.RUNNING:
            n = self.run_pending(now)
            total += n
            if n == 0:
                break
        return total

    def _dispatch(self, ex: Execution) -> None:
        if ex.state is ExecutionState.QUEUED:
            self._transition(ex, ExecutionState.SCHEDULED)
        elif ex.state is ExecutionState.SCHEDULED:
            pass  # resumed executions are already SCHEDULED
        else:
            return  # cancelled/terminal — skip
        self._metrics.on_dequeued(time.monotonic() - ex.queued_at_wall)
        result = self._pipeline.run(ex)
        with self._lock:
            self._results[ex.id] = result
            if result.state is ExecutionState.COMPLETED:
                self._completed_ids.add(ex.id)  # idempotency (no duplicated execution)
        # Periodic re-scheduling (a fresh execution due in the future).
        if ex.kind is QueueKind.PERIODIC and result.state is ExecutionState.COMPLETED:
            if self._lifecycle is RuntimeLifecycleState.RUNNING:
                self.submit(ex.request)

    # --- recovery -------------------------------------------------------- #

    def recover(self) -> int:
        """Verify integrity and replay the ledger deterministically (RL8).

        Completed executions are never re-run (idempotency de-dup).
        """
        with self._lock:
            self._recovering += 1
        try:
            self._recovery.verify_integrity()
            replayed = self._recovery.replay(lambda _e: None)
            self._metrics.on_recovered()
            return replayed
        finally:
            with self._lock:
                self._recovering = max(0, self._recovering - 1)

    def has_executed(self, execution_id: str) -> bool:
        with self._lock:
            return execution_id in self._completed_ids

    # --- health, metrics, diagnostics ------------------------------------ #

    def metrics(self) -> RuntimeMetricsSnapshot:
        return self._metrics.snapshot()

    def _runtime_status(self) -> RuntimeHealth:
        if self._lifecycle is RuntimeLifecycleState.STOPPED:
            return RuntimeHealth.UNAVAILABLE
        if self._recovering:
            return RuntimeHealth.RECOVERING
        active = self._metrics.snapshot().active
        depth = self._queue.depth()
        if active >= self._config.busy_active_threshold or depth >= self._config.busy_queue_threshold:
            return RuntimeHealth.BUSY
        return RuntimeHealth.HEALTHY

    def health(self) -> RuntimeHealthReport:
        status = self._runtime_status()
        # Kernel health, excluding our own probe to avoid recursion.
        reports = {k: v for k, v in self._services.health.report().items() if k != "runtime"}
        kernel_worst = HealthStatus.HEALTHY
        order = {HealthStatus.HEALTHY: 0, HealthStatus.UNKNOWN: 1, HealthStatus.DEGRADED: 2, HealthStatus.UNHEALTHY: 3}
        for r in reports.values():
            if order[r.status] > order[kernel_worst]:
                kernel_worst = r.status
        if kernel_worst in (HealthStatus.DEGRADED, HealthStatus.UNHEALTHY) and status is RuntimeHealth.HEALTHY:
            status = RuntimeHealth.DEGRADED
        return RuntimeHealthReport(
            status=status,
            lifecycle=self._lifecycle,
            detail=f"{status.value}/{self._lifecycle.value}",
            queue_depth=self._queue.depth(),
            active_executions=self._metrics.snapshot().active,
            recovering=self._recovering,
            kernel_health=kernel_worst,
        )

    def diagnostics(self) -> dict:
        h = self.health()
        return {
            "lifecycle": self._lifecycle.value,
            "health": h.status.value,
            "metrics": self.metrics(),
            "queue_order": self._queue.peek_order(),
            "engines": list(self._orchestrator.names()),
        }

    def _health_probe(self) -> HealthReport:
        status = self._runtime_status()  # no kernel call -> no recursion
        return HealthReport(
            component="runtime",
            status=_HEALTH_MAP[status],
            detail=f"{status.value}/{self._lifecycle.value}",
            metrics={"queue_depth": float(self._queue.depth())},
        )

    # --- internals ------------------------------------------------------- #

    def _make_context(self, request: ExecutionRequest, policy, parent: Execution | None):
        security = request.security or SecurityContext(principal="runtime", org_id="system")
        correlation = request.correlation_id
        if correlation is None and parent is not None and not policy.isolated:
            correlation = parent.correlation_id
        parent_span = parent.context.trace.span_id if parent is not None else None
        kernel_budget = ExecutionBudget(
            max_steps=request.budget.steps or 0,
            max_wall_seconds=request.budget.time_seconds,
        )
        return self._services.new_context(
            security=security,
            workspace_id=request.workspace_id or (parent.context.workspace_id if parent else None),
            conversation_id=request.conversation_id or (parent.context.conversation_id if parent else None),
            active_engine=request.engine,
            budget=kernel_budget,
            correlation_id=correlation,
            parent_span_id=parent_span,
        )

    def _transition(self, ex: Execution, target: ExecutionState) -> None:
        ex.sm.transition(target)  # validated (RL3) — raises on illegal transition
        logical = self._services.clock.tick()
        self._obs.record(ex.id, target, logical)
        self._emit(
            f"runtime.execution.{target.value}",
            {"execution_id": ex.id, "attempt": ex.attempts},
            correlation_id=ex.correlation_id,
        )

    def _emit(self, event_type, payload, *, correlation_id, causation_id=None, priority=EventPriority.NORMAL):
        from ..contracts import CognitiveEvent

        event = CognitiveEvent(
            event_id=uuid.uuid4().hex,
            type=event_type,
            sequence=self._services.clock.tick(),
            source="runtime",
            correlation_id=correlation_id,
            payload=payload,
            priority=priority,
            causation_id=causation_id,
        )
        self._services.events.publish(event)

    def _result_for(self, ex: Execution, timeout: float | None) -> ExecutionResult:
        with self._lock:
            if ex.id in self._results:
                return self._results[ex.id]
        if timeout:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                with self._lock:
                    if ex.id in self._results:
                        return self._results[ex.id]
                time.sleep(0.001)
        # Fallback for terminal-without-pipeline (e.g. cancelled while queued).
        if ex.state in (ExecutionState.CANCELLED, ExecutionState.COMPLETED, ExecutionState.FAILED):
            return ExecutionResult(
                execution_id=ex.id, engine=ex.request.engine, state=ex.state,
                error=ex.error, attempts=ex.attempts,
            )
        raise RuntimeStateError(f"Execution {ex.id} has not finished.")

    # --- background pump (optional, real-time coordination, RL1) ---------- #

    def _start_pump(self) -> None:
        with self._lock:
            if self._pump_running:
                return
            self._pump_running = True

        def loop() -> None:
            while True:
                with self._lock:
                    if not self._pump_running:
                        return
                    running = self._lifecycle is RuntimeLifecycleState.RUNNING
                if running:
                    self.run_pending()
                time.sleep(self._config.pump_interval)

        self._pump_thread = threading.Thread(target=loop, name="runtime-pump", daemon=True)
        self._pump_thread.start()

    def _stop_pump(self) -> None:
        with self._lock:
            self._pump_running = False
        t = self._pump_thread
        if t is not None:
            t.join(timeout=2.0)
            self._pump_thread = None
