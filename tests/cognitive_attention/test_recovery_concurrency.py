"""Recovery, checkpoint, concurrency, and stress for the Attention Engine."""

from __future__ import annotations

import threading

from app.cognitive_kernel.engines.attention import AttentionEngine

from ._at import cand, make_attention, make_targets, teardown


def test_reconstruct_from_R3() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        t = make_targets(sm, ctx, 2)
        att.attend([cand(t[0], goal_relevance=0.9), cand(t[1], urgency=0.8)], ctx)
        # A fresh attention engine rebuilds its ephemeral dynamics from R3.
        att2 = AttentionEngine(kernel.services(), sm, att._wm)  # noqa: SLF001
        att2.start()
        size = att2.reconstruct()
        assert size == 2  # coalition recovered from the durable attention record
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_checkpoint_captures_attention_state() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        t = make_targets(sm, ctx, 2)
        att.attend([cand(t[0], goal_relevance=0.9)], ctx)
        cid = sm.checkpoint()  # attention R3 state captured by the state checkpoint
        att.attend([cand(t[1], goal_relevance=0.9)], ctx)  # change the focus
        sm.restore(cid)
        from app.cognitive_kernel.state import ObjectType, Region

        focus = sm.query(region=Region.R3_ATTENTION, type=ObjectType.ATTENTION_FOCUS)[0]
        assert t[0] in focus.payload["coalition"]  # restored focus
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_concurrent_attends_are_serialised_and_intact() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention(focus=4)
    try:
        t = make_targets(sm, ctx, 20)

        def worker(subset) -> None:
            for h in subset:
                att.attend([cand(h, goal_relevance=0.9)], ctx)

        threads = [threading.Thread(target=worker, args=(t[i::4],)) for i in range(4)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        # No corruption: the conscious field stays bounded and the ledger verifies.
        assert len(wm.read_focus()) <= 4
        assert kernel.services().ledger.verify()
        assert att.metrics().cycles == 20
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_stress_many_cycles_bounded() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention(focus=4)
    try:
        t = make_targets(sm, ctx, 60)
        for i in range(0, 60, 6):
            batch = [cand(h, goal_relevance=0.9) for h in t[i:i + 6]]
            att.attend(batch, ctx)
        assert len(wm.read_focus()) <= 4  # consciousness stays bounded no matter the load
        assert att.metrics().cycles == 10
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, sm, wm, att)
