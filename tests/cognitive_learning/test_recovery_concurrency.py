"""Checkpoint, recovery, concurrency, and stress for Learning."""

from __future__ import annotations

import threading

from ._ln import episodes, learned, make_learning, reconciled, teardown


def test_checkpoint_and_recover_history_and_calibration() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        episodes(state, ctx, "fact", 3)
        learn.learn(ctx)
        for i in range(6):
            reconciled(kernel.services(), f"r{i}", surprise=0.2)
        learn.learn(ctx)
        cal = learn.calibration()
        cid = learn.checkpoint()
        summary = learn.recover(cid)
        assert summary["restored"] and learn.calibration() == cal
    finally:
        teardown(kernel, rt, state, learn)


def test_concurrent_learning_is_serialised_and_intact() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        for i in range(8):
            episodes(state, ctx, f"claim{i}", 3)

        results: list = []
        lock = threading.Lock()

        def worker() -> None:
            report = learn.learn(ctx)
            with lock:
                results.append(report)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each claim consolidates exactly once (no double-commit under concurrency).
        for i in range(8):
            assert len(learned(state, f"claim{i}")) == 1
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, learn)


def test_stress_many_learning_cycles() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        for i in range(30):
            episodes(state, ctx, f"c{i}", 3)
            learn.learn(ctx)
        assert learn.metrics().committed == 30
        ok, _ = learn.verify_knowledge_integrity()
        assert ok and kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, learn)
