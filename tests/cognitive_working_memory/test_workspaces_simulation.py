"""Workspaces, context switching, nested contexts, simulation isolation."""

from __future__ import annotations

from app.cognitive_kernel.engines.working_memory import WorkspaceKind

from ._wm import idx, make_targets, make_wm, teardown


def test_open_switch_and_isolate_workspaces() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        t = make_targets(sm, ctx, 4)
        goal_ws = wm.open_workspace(WorkspaceKind.GOAL, ctx)
        task_ws = wm.open_workspace(WorkspaceKind.TASK, ctx)
        wm.switch_workspace(goal_ws)
        wm.load(t[0], ctx)
        wm.load(t[1], ctx)
        wm.switch_workspace(task_ws)
        wm.load(t[2], ctx)
        assert {idx(sm, s) for s in wm.contents(goal_ws)} == {0, 1}
        assert {idx(sm, s) for s in wm.contents(task_ws)} == {2}  # isolated per workspace
        assert wm.metrics().context_switches == 2
    finally:
        teardown(kernel, rt, sm, wm)


def test_nested_workspace_has_parent() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        parent = wm.open_workspace(WorkspaceKind.TASK, ctx)
        child = wm.open_workspace(WorkspaceKind.NESTED, ctx, parent=parent)
        info = wm._workspaces.get(child)  # noqa: SLF001
        assert info.parent == parent and info.kind is WorkspaceKind.NESTED
    finally:
        teardown(kernel, rt, sm, wm)


def test_close_workspace_evicts_and_reports_consolidation() -> None:
    kernel, rt, sm, wm, ctx = make_wm(decay_rate=0.01)  # low decay: both stay salient
    try:
        t = make_targets(sm, ctx, 2)
        ws = wm.open_workspace(WorkspaceKind.GOAL, ctx)
        wm.switch_workspace(ws)
        wm.load(t[0], ctx, activation=1.0)
        wm.load(t[1], ctx, activation=1.0)
        candidates = wm.close_workspace(ws, ctx)  # returns #consolidation candidates
        assert candidates == 2
        assert not wm._workspaces.exists(ws)  # noqa: SLF001
        assert len(wm.contents(ws)) == 0  # refs evicted; targets still in State
        assert sm.exists(t[0]) and sm.exists(t[1])
    finally:
        teardown(kernel, rt, sm, wm)


def test_simulation_workspace_is_isolated() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        t = make_targets(sm, ctx, 3)
        base = wm.open_workspace(WorkspaceKind.GOAL, ctx)
        wm.switch_workspace(base)
        wm.load(t[0], ctx)
        wm.load(t[1], ctx)
        sim = wm.branch_simulation(base, ctx)
        assert {idx(sm, s) for s in wm.contents(sim)} == {0, 1}  # copied membership
        # Mutate the simulation: add + evict inside it.
        wm.load(t[2], ctx, workspace=sim)
        sim_slots = wm.contents(sim)
        wm.evict(sim_slots[0].handle, ctx)
        # The base workspace is completely untouched (PrL8 isolation).
        assert {idx(sm, s) for s in wm.contents(base)} == {0, 1}
        wm.discard_simulation(sim, ctx)
        assert {idx(sm, s) for s in wm.contents(base)} == {0, 1}  # still intact after discard
    finally:
        teardown(kernel, rt, sm, wm)


def test_switch_to_unknown_workspace_raises() -> None:
    from app.cognitive_kernel.engines.working_memory import UnknownWorkspaceError

    kernel, rt, sm, wm, ctx = make_wm()
    try:
        import pytest

        with pytest.raises(UnknownWorkspaceError):
            wm.switch_workspace("does-not-exist")
    finally:
        teardown(kernel, rt, sm, wm)
