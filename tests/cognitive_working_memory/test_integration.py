"""Integration: references-only, state-manager writes, ledger events, runtime path."""

from __future__ import annotations

from app.cognitive_kernel.contracts import SecurityContext
from app.cognitive_kernel.runtime import ExecutionRequest
from app.cognitive_kernel.state import ObjectStatus, ObjectType, Region
from app.cognitive_kernel.state.contracts import RelationshipType
from app.cognitive_kernel.engines.working_memory import WorkingMemoryRuntimeApi
from app.cognitive_kernel.engines.working_memory.refs import WM_REF_TYPE

from ._wm import make_targets, make_wm, teardown


def test_working_memory_stores_only_references_never_copies() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        tx = sm.begin_transaction(ctx)
        target = tx.create(ObjectType.BELIEF, payload={"secret": "sensitive-content", "size": 9999})
        tx.commit()
        ref = wm.load(target, ctx)
        ref_obj = sm.get(ref)
        # The WM reference holds the target HANDLE, not the target's content.
        assert ref_obj.payload["target"] == target
        assert "secret" not in ref_obj.payload and "size" not in ref_obj.payload
        # And it ACTIVATES the target (a relationship edge, not a copy).
        assert any(e.rel_type is RelationshipType.ACTIVATION and e.target == target for e in ref_obj.relationships)
    finally:
        teardown(kernel, rt, sm, wm)


def test_all_wm_state_lives_in_the_state_manager_R4() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        for t in make_targets(sm, ctx, 3):
            wm.load(t, ctx)
        # Every WM reference is a Cognitive-State object in Region R4.
        refs = sm.query(region=Region.R4_WORKING_MEMORY, type=WM_REF_TYPE, status=ObjectStatus.ACTIVE)
        assert len(refs) == 3
        for r in refs:
            assert r.region is Region.R4_WORKING_MEMORY
    finally:
        teardown(kernel, rt, sm, wm)


def test_eviction_archives_ref_but_target_persists() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        t = make_targets(sm, ctx, 1)[0]
        ref = wm.load(t, ctx)
        wm.evict(ref, ctx)
        assert sm.get(ref).status is ObjectStatus.ARCHIVED  # ref cooled out of WM
        assert sm.exists(t) and sm.get(t).status is ObjectStatus.ACTIVE  # target still in State
    finally:
        teardown(kernel, rt, sm, wm)


def test_wm_operations_recorded_in_kernel_ledger() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        before = kernel.services().ledger.head()
        wm.load(make_targets(sm, ctx, 1)[0], ctx)
        types = {e.event.type for e in kernel.services().ledger.read(since=before)}
        assert "working_memory.loaded" in types
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, sm, wm)


def test_operation_flows_through_the_runtime() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        t = make_targets(sm, ctx, 1)[0]
        # Submit a WM load as a runtime execution (the canonical cross-engine path).
        h = rt.submit(ExecutionRequest(engine="working_memory", operation="load", payload={"target": t}))
        rt.drain()
        result = h.result()
        assert result.state.value == "completed" and result.value  # a WM-ref handle
        assert sm.exists(result.value)  # the ref exists in State
    finally:
        teardown(kernel, rt, sm, wm)


def test_runtime_api_facade() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        api = WorkingMemoryRuntimeApi(rt)
        t = make_targets(sm, ctx, 1)[0]
        ref = api.ignite(t, ctx)  # attention hook -> routed through the runtime
        assert sm.exists(ref)
    finally:
        teardown(kernel, rt, sm, wm)


def test_health_probe_registered_and_broadcast() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        assert "working_memory" in kernel.services().health.report()
        assert wm.wm_health().healthy
        t = make_targets(sm, ctx, 2)
        for h in t:
            wm.load(h, ctx)
        before = kernel.services().ledger.head()
        focus = wm.broadcast(None, ctx)
        assert len(focus) == 2
        types = {e.event.type for e in kernel.services().ledger.read(since=before)}
        assert "working_memory.broadcast" in types  # Global Workspace broadcast
    finally:
        teardown(kernel, rt, sm, wm)


def test_capacity_evolution_requires_admin() -> None:
    import pytest

    from app.cognitive_kernel.engines.working_memory import WMConfig, WorkingMemorySecurityError

    kernel, rt, sm, wm, ctx = make_wm()
    try:
        with pytest.raises(WorkingMemorySecurityError):
            wm.set_capacity(WMConfig(focus_capacity=8), ctx)  # non-admin
        admin = kernel.services().new_context(
            security=SecurityContext("dev", "org", frozenset({"state:admin"}))
        )
        wm.set_capacity(WMConfig(focus_capacity=8), admin)  # Development hook (gated)
        assert wm.capacity().focus_capacity == 8
    finally:
        teardown(kernel, rt, sm, wm)
