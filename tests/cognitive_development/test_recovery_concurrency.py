"""Checkpoint, recovery, concurrency, and stress for Development."""

from __future__ import annotations

import threading

from ._dv import make_development, strong_reasoning, teardown


def test_checkpoint_and_recover_history_and_versions() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 20)
        dev.develop(ctx)
        dev.develop(ctx)
        tracking = dev.maturity_tracking()
        cid = dev.checkpoint()
        summary = dev.recover(cid)
        assert summary["restored"] and dev.maturity_tracking() == tracking
    finally:
        teardown(kernel, rt, state, dev)


def test_recovery_writes_no_canonical_state() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 20)
        dev.develop(ctx)
        before = dev.canonical_watermark()
        dev.recover(dev.checkpoint())
        assert dev.canonical_watermark() == before and dev.canonical_writes() == 0
    finally:
        teardown(kernel, rt, state, dev)


def test_concurrent_development_is_intact() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 20)
        before = dev.canonical_watermark()
        results: list = []
        lock = threading.Lock()

        def worker() -> None:
            art = dev.develop(ctx)
            with lock:
                results.append(art)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 10 and dev.metrics().cycles == 10
        assert dev.canonical_watermark() == before and dev.canonical_writes() == 0
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, dev)


def test_stress_many_development_cycles() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 20)
        for _ in range(40):
            dev.develop(ctx)
        assert dev.metrics().cycles == 40 and dev.canonical_writes() == 0
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, dev)
