"""Concurrency and stress tests for the Cognitive State Manager."""

from __future__ import annotations

import threading

from app.cognitive_kernel.state import ObjectType, StateConflictError

from ._st import make_state


def test_concurrent_creates_are_all_committed() -> None:
    kernel, sm, ctx = make_state()
    try:
        def worker(base: int) -> None:
            for i in range(10):
                tx = sm.begin_transaction(ctx)
                tx.create(ObjectType.BELIEF, handle=f"b-{base}-{i}", payload={"v": base + i})
                tx.commit()

        threads = [threading.Thread(target=worker, args=(t * 100,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sm.metrics().object_count == 100
        assert kernel.services().ledger.verify()  # integrity intact under concurrency
    finally:
        sm.stop()


def test_optimistic_concurrency_prevents_lost_updates() -> None:
    kernel, sm, ctx = make_state()
    try:
        tx = sm.begin_transaction(ctx)
        g = tx.create(ObjectType.GOAL, payload={"count": 0})
        tx.commit()

        def increment() -> None:
            while True:
                cur = sm.get(g)
                t = sm.begin_transaction(ctx)
                t.update(g, payload_merge={"count": cur.payload["count"] + 1}, expected_version=cur.version)
                try:
                    t.commit()
                    return
                except StateConflictError:
                    continue  # retry on conflict — OCC guarantees no lost update

        threads = [threading.Thread(target=increment) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sm.get(g).payload["count"] == 10  # every increment applied exactly once
        assert kernel.services().ledger.verify()
    finally:
        sm.stop()


def test_stress_many_objects_integrity() -> None:
    kernel, sm, ctx = make_state()
    try:
        N = 1000
        batch = 100
        for start in range(0, N, batch):
            tx = sm.begin_transaction(ctx)
            for i in range(start, start + batch):
                tx.create(ObjectType.BELIEF, handle=f"o-{i}", payload={"i": i})
            tx.commit()
        m = sm.metrics()
        assert m.object_count == N and m.commits == N // batch
        assert sm.verify_integrity() and kernel.services().ledger.verify()
        # Snapshot digest is stable across recomputation (deterministic integrity).
        assert sm.snapshot().digest == sm.snapshot().digest
    finally:
        sm.stop()
