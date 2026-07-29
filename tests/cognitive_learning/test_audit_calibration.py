"""Audit, calibration, integrity, and constitutional constraints."""

from __future__ import annotations

from ._ln import candidate, episodes, learned, make_learning, reconciled, teardown


def test_calibration_learns_only_from_realized_outcomes() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        # Too few reconciled outcomes -> no recalibration (LeL26).
        for i in range(3):
            reconciled(kernel.services(), f"a{i}", surprise=0.3)
        learn.learn(ctx)
        assert learn.metrics().calibrations == 0
        # Enough realized outcomes -> a calibration is committed.
        for i in range(6):
            reconciled(kernel.services(), f"b{i}", surprise=0.3)
        learn.learn(ctx)
        assert learn.metrics().calibrations == 1
    finally:
        teardown(kernel, rt, state, learn)


def test_knowledge_integrity_holds_after_learning() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        episodes(state, ctx, "fact_a", 3)
        episodes(state, ctx, "fact_b", 3)
        learn.learn(ctx)
        ok, issues = learn.verify_knowledge_integrity()
        assert ok and not issues                       # every learned belief has provenance (LeL24)
    finally:
        teardown(kernel, rt, state, learn)


def test_constitution_change_is_rejected() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        episodes(state, ctx, "rewrite_constitution", 3)
        report = learn.learn(ctx)
        assert report.committed == 0 and not learned(state, "rewrite_constitution")  # LeL5
    finally:
        teardown(kernel, rt, state, learn)


def test_false_learning_rate_is_measured() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        candidate(state, ctx, "weak", "one")          # rejected (single event)
        episodes(state, ctx, "strong", 3)             # committed
        learn.learn(ctx)
        m = learn.metrics()
        assert 0.0 <= m.false_learning_rate <= 1.0 and m.examined >= 2  # LeL39
    finally:
        teardown(kernel, rt, state, learn)


def test_development_evidence_export() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        episodes(state, ctx, "trend", 3)
        learn.learn(ctx)
        evidence = learn.development_evidence_export()
        assert evidence["committed"] >= 1 and "kinds" in evidence   # item 33/38
    finally:
        teardown(kernel, rt, state, learn)
