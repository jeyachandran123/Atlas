"""Checkpoint, recovery, concurrency, and stress for Meta-Cognition."""

from __future__ import annotations

import threading

from ._mc import emit, make_meta, teardown


def test_checkpoint_and_recover_history() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        for _ in range(3):
            emit(kernel.services(), "reasoning.concluded", "reasoning", confidence=0.8)
            meta.reflect(ctx)
        cid = meta.checkpoint()
        assert meta.recover(cid)["restored"]
    finally:
        teardown(kernel, rt, state, meta)


def test_recovery_writes_no_canonical_state() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        meta.reflect(ctx)
        before = meta.canonical_watermark()
        meta.recover(meta.checkpoint())
        assert meta.canonical_watermark() == before and meta.canonical_writes() == 0
    finally:
        teardown(kernel, rt, state, meta)


def test_concurrent_reflections_are_intact() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        before = meta.canonical_watermark()
        results: list = []
        lock = threading.Lock()

        def worker() -> None:
            art = meta.reflect(ctx)
            with lock:
                results.append(art)

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 12 and meta.metrics().reflections == 12
        assert meta.canonical_watermark() == before and meta.canonical_writes() == 0
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, meta)


def test_stress_many_reflections_and_audits() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        for i in range(40):
            emit(kernel.services(), "prediction.forecast", "prediction", hypothetical=True, confidence=0.7)
            meta.reflect(ctx)
            meta.constitutional_audit(ctx)
        assert meta.metrics().reflections == 40 and meta.canonical_writes() == 0
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, meta)
