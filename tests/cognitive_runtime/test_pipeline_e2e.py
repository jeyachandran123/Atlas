"""Integration / E2E tests: pipeline, orchestration, metrics, observability."""

from __future__ import annotations

from app.cognitive_kernel.runtime import ExecutionRequest, ExecutionState, RuntimeHealth
from app.cognitive_kernel.runtime.contracts import RuntimeLifecycleState

from ._rt import FakeEngine, make_runtime


def test_full_pipeline_task_completes() -> None:
    kernel, rt = make_runtime()
    try:
        h = rt.submit(ExecutionRequest(engine="calc", task=lambda ctx: 6 * 7))
        assert rt.drain() == 1
        result = h.result()
        assert result.state is ExecutionState.COMPLETED and result.value == 42
        assert result.attempts == 1 and result.finished_at > result.started_at
    finally:
        rt.stop()


def test_engine_orchestration_routes_by_name() -> None:
    kernel, rt = make_runtime()
    try:
        engine = FakeEngine()
        rt.register_engine("echo", engine)
        h = rt.submit(ExecutionRequest(engine="echo", operation="ping", payload={"n": 1}))
        rt.drain()
        result = h.result()
        assert result.state is ExecutionState.COMPLETED
        assert result.value == {"op": "ping", "echo": {"n": 1}}
        assert engine.calls == ["ping"]  # runtime called the engine's contract
    finally:
        rt.stop()


def test_metrics_track_executions() -> None:
    kernel, rt = make_runtime()
    try:
        for i in range(3):
            rt.submit(ExecutionRequest(engine=f"e{i}", task=lambda ctx: 1))
        rt.drain()
        m = rt.metrics()
        assert m.submitted == 3 and m.completed == 3 and m.failed == 0
        assert m.throughput >= 0.0 and m.failure_rate == 0.0
        assert set(m.engine_utilization) == {"e0", "e1", "e2"}
    finally:
        rt.stop()


def test_observability_timeline_and_ledger_events() -> None:
    kernel, rt = make_runtime()
    try:
        before = kernel.services().ledger.head()
        h = rt.submit(ExecutionRequest(engine="calc", task=lambda ctx: "ok"))
        rt.drain()
        timeline = rt._obs.timeline(h.id)  # noqa: SLF001 - observability introspection
        states = [t.state for t in timeline]
        assert ExecutionState.EXECUTING in states and ExecutionState.COMPLETED in states
        # Runtime lifecycle events were recorded to the append-only ledger.
        after = kernel.services().ledger.head()
        assert after > before and kernel.services().ledger.verify()
        types = {e.event.type for e in kernel.services().ledger.read(since=before)}
        assert "runtime.execution.executing" in types
        assert "runtime.execution.completed" in types
    finally:
        rt.stop()


def test_pause_blocks_dispatch_then_resume() -> None:
    kernel, rt = make_runtime()
    try:
        rt.pause()
        rt.submit(ExecutionRequest(engine="calc", task=lambda ctx: 1))
        assert rt.drain() == 0  # nothing runs while paused
        rt.resume()
        assert rt.drain() == 1
    finally:
        rt.stop()


def test_runtime_api_status_and_cancel() -> None:
    kernel, rt = make_runtime()
    try:
        h = rt.submit(ExecutionRequest(engine="calc", task=lambda ctx: 1))
        assert rt.status(h.id) is ExecutionState.QUEUED
        assert rt.cancel(h.id) is True
        assert rt.status(h.id) is ExecutionState.CANCELLED
    finally:
        rt.stop()


def test_health_and_diagnostics() -> None:
    kernel, rt = make_runtime()
    try:
        assert rt.health().status is RuntimeHealth.HEALTHY
        diag = rt.diagnostics()
        assert diag["lifecycle"] == "running" and "metrics" in diag and "queue_order" in diag
        rt.stop()
        assert rt.health().status is RuntimeHealth.UNAVAILABLE
        assert rt.lifecycle is RuntimeLifecycleState.STOPPED
    finally:
        pass
