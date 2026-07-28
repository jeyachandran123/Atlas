"""Capacity, eviction, activation/decay, refresh, expiration, pinning."""

from __future__ import annotations

from app.cognitive_kernel.engines.working_memory import Zone

from ._wm import idx, make_targets, make_wm, teardown, tick


def test_focus_capacity_is_enforced() -> None:
    kernel, rt, sm, wm, ctx = make_wm(focus=3, periphery=2)
    try:
        targets = make_targets(sm, ctx, 6)
        for t in targets:
            wm.load(t, ctx, activation=1.0)
        # Bounded: focus never exceeds capacity; total active refs <= focus+periphery.
        assert len(wm._focus_slots(wm._active)) == 3  # noqa: SLF001
        assert len(wm._periphery_slots(wm._active)) <= 2  # noqa: SLF001
        total = len(wm.contents(wm._active))  # noqa: SLF001
        assert total <= 3 + 2
    finally:
        teardown(kernel, rt, sm, wm)


def test_eviction_demotes_lowest_effective_activation() -> None:
    kernel, rt, sm, wm, ctx = make_wm(focus=3, periphery=3)
    try:
        t = make_targets(sm, ctx, 4)
        for h in t:  # all base 1.0; earliest-loaded decays most -> lowest effective
            wm.load(h, ctx, activation=1.0)
        focus_ix = {idx(sm, s) for s in wm.read_focus()}
        periphery_ix = {idx(sm, s) for s in wm._periphery_slots(wm._active)}  # noqa: SLF001
        assert 0 in periphery_ix          # the earliest (most decayed) was demoted
        assert focus_ix == {1, 2, 3}       # the three most recent stay in focus
    finally:
        teardown(kernel, rt, sm, wm)


def test_eviction_is_deterministic() -> None:
    def run() -> set[int]:
        kernel, rt, sm, wm, ctx = make_wm(focus=3, periphery=3)
        try:
            for h in make_targets(sm, ctx, 5):
                wm.load(h, ctx, activation=1.0)
            return {idx(sm, s) for s in wm.read_focus()}
        finally:
            teardown(kernel, rt, sm, wm)

    assert run() == run()  # identical outcome across runs (deterministic)


def test_pinned_reference_is_exempt_from_eviction() -> None:
    kernel, rt, sm, wm, ctx = make_wm(focus=3, periphery=3)
    try:
        t = make_targets(sm, ctx, 5)
        wm.load(t[0], ctx, activation=0.1, pinned=True)  # low activation but pinned
        for h in t[1:4]:
            wm.load(h, ctx, activation=1.0)
        wm.load(t[4], ctx, activation=1.0)  # overflow
        focus_ix = {idx(sm, s) for s in wm.read_focus()}
        assert 0 in focus_ix  # pinned survives despite lowest activation
    finally:
        teardown(kernel, rt, sm, wm)


def test_activation_decays_over_logical_time() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        ref = wm.load(make_targets(sm, ctx, 1)[0], ctx, activation=1.0)
        slot0 = wm.contents(wm._active)[0]  # noqa: SLF001
        now0 = kernel.services().clock.current()
        e0 = slot0.effective_activation(now0, wm._config.decay_rate)  # noqa: SLF001
        tick(kernel, 20)
        now1 = kernel.services().clock.current()
        e1 = slot0.effective_activation(now1, wm._config.decay_rate)  # noqa: SLF001
        assert e1 < e0  # decayed
    finally:
        teardown(kernel, rt, sm, wm)


def test_refresh_restores_activation_and_resets_decay() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        ref = wm.load(make_targets(sm, ctx, 1)[0], ctx, activation=0.5)
        tick(kernel, 20)
        wm.refresh(ref, ctx, boost=0.9)
        now = kernel.services().clock.current()
        slot = wm.contents(wm._active)[0]  # noqa: SLF001
        assert slot.effective_activation(now, wm._config.decay_rate) > 0.5  # noqa: SLF001
        assert wm.metrics().refreshes == 1
    finally:
        teardown(kernel, rt, sm, wm)


def test_expire_evicts_below_threshold() -> None:
    kernel, rt, sm, wm, ctx = make_wm(min_activation=0.2, decay_rate=0.3)
    try:
        wm.load(make_targets(sm, ctx, 1)[0], ctx, activation=0.5)
        tick(kernel, 30)  # decay it below the expiration threshold
        evicted = wm.expire(ctx)
        assert evicted == 1 and len(wm.contents(wm._active)) == 0  # noqa: SLF001
    finally:
        teardown(kernel, rt, sm, wm)


def test_chunking_frees_focus_capacity() -> None:
    kernel, rt, sm, wm, ctx = make_wm(focus=3, periphery=3)
    try:
        t = make_targets(sm, ctx, 3)
        refs = [wm.load(h, ctx, activation=1.0) for h in t]
        assert len(wm._focus_slots(wm._active)) == 3  # noqa: SLF001
        wm.chunk([refs[0], refs[1]], ctx)  # bind two into one chunk (CL23)
        # The chunk occupies one focus slot; the two members no longer count.
        assert len(wm._focus_slots(wm._active)) == 2  # noqa: SLF001
        assert wm.metrics().chunks == 1
    finally:
        teardown(kernel, rt, sm, wm)
