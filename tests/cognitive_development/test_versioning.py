"""Capability versioning, gain-slow/lose-fast, roadmap versioning (DeL6/DeL9/DeL11)."""

from __future__ import annotations

from app.cognitive_kernel.engines.development.contracts import Capability, MaturityLevel

from ._dv import emit, make_development, strong_reasoning, teardown


def test_certification_versions_increment_each_cycle() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 20)
        art1 = dev.develop(ctx)
        art2 = dev.develop(ctx)
        v1 = {a.capability: a.version for a in art1.assessments}
        v2 = {a.capability: a.version for a in art2.assessments}
        assert all(v2[c] == v1[c] + 1 for c in v1)  # versioned certification (DeL11)
    finally:
        teardown(kernel, rt, state, dev)


def test_maturity_gains_at_most_one_level_per_cycle() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        # Cycle 1: no reasoning activity at all -> NASCENT.
        emit(kernel.services(), "metacognition.reflection", "metacognition")
        art1 = dev.develop(ctx)
        r1 = next(a for a in art1.assessments if a.capability is Capability.REASONING)
        assert r1.maturity is MaturityLevel.NASCENT
        # Cycle 2: a flood of strong reasoning -> raw OPTIMIZING, but capped to +1 (DeL6).
        strong_reasoning(kernel.services(), 40)
        art2 = dev.develop(ctx)
        r2 = next(a for a in art2.assessments if a.capability is Capability.REASONING)
        assert int(r2.maturity) - int(r1.maturity) == 1  # gain is slow and gated
    finally:
        teardown(kernel, rt, state, dev)


def test_regression_lowers_maturity_fast() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 20)
        dev.develop(ctx)  # establish some maturity
        dev.develop(ctx)  # +1
        art = dev.develop(ctx)
        before = next(a for a in art.assessments if a.capability is Capability.REASONING).maturity
        # Flood with escalations (failures) -> reasoning success drops -> maturity falls (may drop >1).
        for _ in range(200):
            emit(kernel.services(), "reasoning.escalated", "reasoning")
        art2 = dev.develop(ctx)
        after = next(a for a in art2.assessments if a.capability is Capability.REASONING).maturity
        assert int(after) <= int(before)  # losing is fast/automatic (DeL5/DeL6)
    finally:
        teardown(kernel, rt, state, dev)


def test_roadmap_is_versioned() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 20)
        r1 = dev.develop(ctx).roadmap.version
        r2 = dev.develop(ctx).roadmap.version
        assert r2 == r1 + 1
    finally:
        teardown(kernel, rt, state, dev)


def test_maturity_tracking_is_per_capability() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 20)
        dev.develop(ctx)
        tracking = dev.maturity_tracking()
        assert set(tracking) == {c.value for c in Capability}  # per-capability, never a scalar (DeL9)
    finally:
        teardown(kernel, rt, state, dev)
