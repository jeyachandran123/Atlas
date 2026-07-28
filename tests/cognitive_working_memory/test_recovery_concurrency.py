"""Recovery/reconstruction, checkpoint, concurrency, and stress."""

from __future__ import annotations

import threading

from app.cognitive_kernel.engines.working_memory import WMConfig, WorkingMemoryEngine

from ._wm import make_targets, make_wm, teardown


def test_reconstruct_from_persistent_state() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        for t in make_targets(sm, ctx, 3):
            wm.load(t, ctx)
        # A fresh WM engine (empty registry) rebuilds its workspaces from R4 (§5.6).
        wm2 = WorkingMemoryEngine(kernel.services(), sm, WMConfig())
        wm2.start()
        reconstructed = wm2.reconstruct()
        assert reconstructed == 3
        # The reconstructed engine sees the same references (from persistent state).
        assert len(wm2.contents(wm._active)) == 3  # noqa: SLF001
        wm2.stop()
    finally:
        teardown(kernel, rt, sm, wm)


def test_checkpoint_captures_working_memory() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        t = make_targets(sm, ctx, 2)
        r0 = wm.load(t[0], ctx)
        wm.load(t[1], ctx)
        cid = sm.checkpoint()  # WM lives in R4 -> captured by the state checkpoint
        wm.evict(r0, ctx)
        assert len(wm.contents(wm._active)) == 1  # noqa: SLF001
        sm.restore(cid)
        assert len(wm.contents(wm._active)) == 2  # noqa: SLF001 - WM restored with state
    finally:
        teardown(kernel, rt, sm, wm)


def test_wm_snapshot() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        for t in make_targets(sm, ctx, 2):
            wm.load(t, ctx)
        snap = wm.snapshot()
        assert len(snap.slots) == 2 and snap.workspace == wm._active  # noqa: SLF001
    finally:
        teardown(kernel, rt, sm, wm)


def test_concurrent_loads_respect_capacity() -> None:
    kernel, rt, sm, wm, ctx = make_wm(focus=4, periphery=3)
    try:
        targets = make_targets(sm, ctx, 30)

        def worker(subset) -> None:
            for t in subset:
                wm.load(t, ctx, activation=1.0)

        threads = [threading.Thread(target=worker, args=(targets[i::5],)) for i in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        # Capacity holds under concurrency (WM serialises its own mutations).
        assert len(wm._focus_slots(wm._active)) <= 4  # noqa: SLF001
        assert len(wm._periphery_slots(wm._active)) <= 3  # noqa: SLF001
        assert wm.metrics().loads == 30
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, sm, wm)


def test_stress_many_loads_bounded_and_intact() -> None:
    kernel, rt, sm, wm, ctx = make_wm(focus=4, periphery=3)
    try:
        for t in make_targets(sm, ctx, 200):
            wm.load(t, ctx, activation=1.0)
        # Working memory stays bounded no matter how much is loaded.
        active_refs = len(wm.contents(wm._active))  # noqa: SLF001
        assert active_refs <= 4 + 3
        assert wm.metrics().loads == 200
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, sm, wm)
