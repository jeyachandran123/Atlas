"""Recovery, checkpoint, concurrency, and stress for the Executive Engine."""

from __future__ import annotations

import threading

from app.cognitive_kernel.engines.executive import Policy, PolicyEffect, PolicyFamily, ResourceKind

from ._ex import make_executive, proposal, teardown


def test_governance_checkpoint_and_recovery() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        ex.enact_policy(admin, Policy("p", PolicyFamily.REASONING, "depth", PolicyEffect.ALLOW,
                                      predicate={"always": True}))
        ex.allocate(ctx, ResourceKind.REASONING, "m1", 0.4)
        cid = ex.checkpoint()                        # governance config sealed (ExL27)
        ex.allocate(ctx, ResourceKind.ATTENTION, "m2", 0.3)  # mutate after checkpoint
        summary = ex.recover(cid)
        assert summary["restored"]
        # allocations restored to the checkpoint (m2 gone).
        matters = {a.matter_id for a in ex._resources.allocations()}  # noqa: SLF001
        assert "m1" in matters and "m2" not in matters
    finally:
        teardown(kernel, rt, state, ex)


def test_state_checkpoint_captures_executive_decisions() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        out1 = ex.govern(proposal("p1", "a", 0.9, stakes=0.1), ctx)
        cid = state.checkpoint()
        out2 = ex.govern(proposal("p2", "b", 0.9, stakes=0.1), ctx)
        state.restore(cid)
        handles = {o.handle for o in ex.audit_trail()}
        assert out1.decision.handle in handles and out2.decision.handle not in handles
    finally:
        teardown(kernel, rt, state, ex)


def test_concurrent_governance_is_serialised_and_intact() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        results: list = []
        lock = threading.Lock()

        def worker(i: int) -> None:
            out = ex.govern(proposal(f"p{i}", f"claim{i}", 0.9, stakes=0.1), ctx)
            with lock:
                results.append(out)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 16 and all(o.authorized for o in results)
        assert len({o.decision.decision_id for o in results}) == 16  # no collision
        assert ex.metrics().governance_passes == 16
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, ex)


def test_stress_many_governance_passes() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        for i in range(40):
            ex.govern(proposal(f"p{i}", "ok", 0.9, stakes=0.1), ctx)
        assert ex.metrics().governance_passes == 40
        assert ex.executive_health().budget_ok
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, ex)
