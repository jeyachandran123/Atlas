"""Recovery, checkpoint, interrupt/resume, concurrency, and stress."""

from __future__ import annotations

import threading

from app.cognitive_kernel.contracts import SecurityContext
from app.cognitive_kernel.state import ObjectType, Region
from app.cognitive_kernel.engines.reasoning import ReasoningRequest

from ._rz import assertion, cause, conscious, make_reasoning, rule, teardown


def test_reconstruct_episode_from_R6() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        a = assertion(state, ctx, "a", confidence=0.9)
        r1 = rule(state, ctx, ["a"], "b")
        conscious(wm_api, [a, r1], ctx)
        res = rz.reason(ReasoningRequest(goal="derive b", question="b"), ctx)
        # A fresh episode's transient space is rebuilt from the durable R6 record (ReL8).
        assert rz.reconstruct(res.episode_id) == len(res.steps)
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_checkpoint_captures_reasoning_state() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        a = assertion(state, ctx, "a", confidence=0.9)
        r1 = rule(state, ctx, ["a"], "b")
        conscious(wm_api, [a, r1], ctx)
        res1 = rz.reason(ReasoningRequest(goal="derive b", question="b"), ctx)
        cid = state.checkpoint()                                  # captures episode-1 R6
        res2 = rz.reason(ReasoningRequest(goal="derive b again", question="b"), ctx)
        state.restore(cid)                                        # roll back
        episodes = {o.handle for o in state.query(region=Region.R6_DELIBERATIVE, type=ObjectType.REASONING_STATE)}
        assert res1.episode_id in episodes and res2.episode_id not in episodes
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_interrupt_then_resume() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        a = assertion(state, ctx, "a", confidence=0.9)
        r1 = rule(state, ctx, ["a"], "b")
        conscious(wm_api, [a, r1], ctx)
        ctx.cancellation.cancel("preempted by a higher-salience matter")
        res = rz.reason(ReasoningRequest(goal="derive b", question="b"), ctx)
        assert res.state.value == "interrupted" and not res.concluded  # ReL8: resumable, not lost
        fresh = kernel.services().new_context(security=SecurityContext("user", "org"))
        resumed = rz.resume(res.episode_id, fresh)
        assert resumed.concluded and resumed.conclusion.statement == "b"
        assert rz.metrics().resumptions == 1
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_concurrent_parallel_reasoning_contexts() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        # Independent conscious premises for independent, parallel episodes.
        prem = []
        for i in range(8):
            a = assertion(state, ctx, f"a{i}", confidence=0.9)
            r = rule(state, ctx, [f"a{i}"], f"b{i}")
            prem += [a, r]
        conscious(wm_api, prem, ctx)

        results: list = []
        lock = threading.Lock()

        def worker(i: int) -> None:
            r = rz.reason(ReasoningRequest(goal=f"derive b{i}", question=f"b{i}"), ctx)
            with lock:
                results.append(r)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 8 and all(r.concluded for r in results)
        assert len({r.episode_id for r in results}) == 8  # parallel contexts don't collide
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_stress_many_episodes() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        e1 = assertion(state, ctx, "effect1", kind=ObjectType.PERCEPT)
        c1 = cause(state, ctx, "C1", "effect1", strength=0.95)
        conscious(wm_api, [e1, c1], ctx)
        for _ in range(30):
            res = rz.reason(ReasoningRequest(goal="explain"), ctx)
            assert res.conclusion.statement == "C1"
        assert rz.metrics().episodes == 30
        assert kernel.services().ledger.verify()
    finally:
        teardown(kernel, rt, state, wm, rz)
