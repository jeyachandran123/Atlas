"""Concurrency, determinism, and stress tests."""

from __future__ import annotations

import threading
import time

from app.cognitive_kernel.runtime import ExecutionRequest, ExecutionState

from ._rt import make_runtime


def test_concurrent_submission_with_background_pump() -> None:
    kernel, rt = make_runtime(background_pump=True, pump_interval=0.001)
    try:
        handles = []
        handles_lock = threading.Lock()

        def submitter(base: int) -> None:
            for i in range(10):
                h = rt.submit(ExecutionRequest(engine="w", task=lambda ctx, v=base + i: v))
                with handles_lock:
                    handles.append(h)

        threads = [threading.Thread(target=submitter, args=(t * 100,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 50 executions complete (background pump drains them).
        for h in handles:
            result = h.result(timeout=3.0)
            assert result.state is ExecutionState.COMPLETED
        assert len(handles) == 50
        assert rt.metrics().completed == 50
        assert kernel.services().ledger.verify()  # integrity intact under concurrency
    finally:
        rt.stop()


def test_deterministic_completion_order_same_priority() -> None:
    kernel, rt = make_runtime()
    try:
        order: list[int] = []
        for i in range(20):
            rt.submit(ExecutionRequest(engine="e", task=lambda ctx, v=i: order.append(v)))
        rt.drain()  # single-threaded deterministic dispatch
        assert order == list(range(20))  # FIFO within equal priority (RL4)
    finally:
        rt.stop()


def test_stress_many_executions() -> None:
    kernel, rt = make_runtime()
    try:
        N = 500
        for i in range(N):
            rt.submit(ExecutionRequest(engine="e", task=lambda ctx, v=i: v * 2))
        ran = rt.drain()
        assert ran == N
        m = rt.metrics()
        assert m.completed == N and m.failed == 0 and m.cancelled == 0
        assert kernel.services().ledger.verify()
    finally:
        rt.stop()


def test_mixed_outcomes_under_load() -> None:
    kernel, rt = make_runtime()
    try:
        def maybe_fail(ctx, v):
            if v % 7 == 0:
                raise ValueError("planned")
            return v

        for i in range(100):
            rt.submit(ExecutionRequest(engine="e", task=lambda ctx, v=i: maybe_fail(ctx, v)))
        rt.drain()
        m = rt.metrics()
        expected_fail = sum(1 for i in range(100) if i % 7 == 0)
        assert m.failed == expected_fail
        assert m.completed == 100 - expected_fail
        assert m.submitted == 100
        assert kernel.services().ledger.verify()
    finally:
        rt.stop()
