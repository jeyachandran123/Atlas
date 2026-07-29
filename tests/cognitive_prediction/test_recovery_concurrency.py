"""Recovery, checkpoint, reconciliation, concurrency, and stress."""

from __future__ import annotations

import threading

from ._pr import driver, make_prediction, request, teardown


def test_checkpoint_and_recover_history() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        pred.forecast(request("r1", seed=1, drivers=(driver("d", 0.8, 1.0),)), ctx)
        pred.forecast(request("r2", seed=2, drivers=(driver("d", 0.6, 1.0),)), ctx)
        cid = pred.checkpoint()
        assert len(pred.history()) == 2
        summary = pred.recover(cid)
        assert summary["restored"] and len(pred.history()) == 2
    finally:
        teardown(kernel, rt, state, pred)


def test_recovery_writes_no_canonical_state() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        pred.forecast(request("r", seed=1, drivers=(driver("d", 0.8, 1.0),)), ctx)
        before = pred.canonical_watermark()
        pred.recover(pred.checkpoint())
        assert pred.canonical_watermark() == before and pred.canonical_writes() == 0  # PrL8
    finally:
        teardown(kernel, rt, state, pred)


def test_reconcile_against_reality_computes_surprise() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        f = pred.forecast(request("r", seed=1, drivers=(driver("d", 0.9, 1.0),)), ctx)
        surprise = pred.reconcile("r", observed_outcome=0.0, context=ctx)  # PrL22
        assert abs(surprise - f.outcome_probability) < 1e-6
        assert len(pred.learning_calibration_candidates()) == 1  # a calibration proposal for Learning
    finally:
        teardown(kernel, rt, state, pred)


def test_concurrent_forecasts_are_intact_and_isolated() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        before = pred.canonical_watermark()
        results: list = []
        lock = threading.Lock()

        def worker(i: int) -> None:
            f = pred.forecast(request(f"r{i}", seed=i, drivers=(driver("d", 0.7, 1.0),)), ctx)
            with lock:
                results.append(f)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 16 and pred._sim.open_count() == 0       # noqa: SLF001 - all cleaned up
        assert pred.canonical_watermark() == before                     # isolation held under concurrency
        assert pred.canonical_writes() == 0
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, pred)


def test_stress_many_forecasts_bounded() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        for i in range(50):
            pred.forecast(request(f"r{i}", seed=i, stakes=0.6, num_samples=64,
                                  drivers=(driver("a", 0.6, 1.0), driver("b", 0.3, -1.0))), ctx)
        assert pred.metrics().forecasts == 50 and pred._sim.open_count() == 0  # noqa: SLF001
        assert pred.canonical_writes() == 0
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, pred)
