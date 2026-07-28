"""Integration hooks: executive/prediction bias, inspection, feedback, adaptation."""

from __future__ import annotations

import pytest

from app.cognitive_kernel.contracts import SecurityContext
from app.cognitive_kernel.engines.attention import AttentionConfig, AttentionSecurityError

from ._at import cand, make_attention, make_targets, teardown


def test_executive_bias_tilts_competition() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        t = make_targets(sm, ctx, 1)
        # A weak candidate does not ignite on its own...
        r0 = att.attend([cand(t[0], novelty=0.2)], ctx)
        assert not r0.ignited
        # ...but the executive can bias attention toward it (AL8).
        att.set_executive_bias(t[0], 0.6, ctx)
        r1 = att.attend([cand(t[0], novelty=0.2)], ctx)
        assert r1.ignited and t[0] in r1.coalition
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_executive_bias_cannot_suppress_safety() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        t = make_targets(sm, ctx, 1)
        att.set_executive_bias(t[0], -0.9, ctx)  # executive tries to suppress...
        r = att.attend([cand(t[0], safety_implications=0.95)], ctx)
        assert r.ignited and t[0] in r.coalition  # ...safety floor holds (AL8 safety-bounded)
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_prediction_surprise_raises_salience() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        t = make_targets(sm, ctx, 1)
        r0 = att.attend([cand(t[0])], ctx)  # neutral -> does not ignite
        assert not r0.ignited
        att.set_prediction_surprise(t[0], 0.9, ctx)  # prediction error feeds surprise
        r1 = att.attend([cand(t[0])], ctx)
        assert r1.ignited
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_inspect_is_readonly_and_reports_state() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        t = make_targets(sm, ctx, 2)
        att.attend([cand(t[0], goal_relevance=0.9), cand(t[1], novelty=0.1)], ctx)
        view = att.inspect()  # meta-cognitive inspection hook
        assert t[0] in view["coalition"]
        assert "salience_map" in view and "fatigue" in view and "metrics" in view
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_learning_feedback_hook() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        t = make_targets(sm, ctx, 1)
        att.feedback(t[0], "useful", ctx)  # learning feedback (attention never learns; it records)
        assert len(att._feedback_log) == 1 and att._feedback_log[0][1] == "useful"  # noqa: SLF001
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_development_adaptation_requires_admin() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        with pytest.raises(AttentionSecurityError):
            att.set_config(AttentionConfig(ignition_threshold=0.9), ctx)  # non-admin
        admin = kernel.services().new_context(security=SecurityContext("dev", "org", frozenset({"state:admin"})))
        att.set_config(AttentionConfig(ignition_threshold=0.9), admin)  # Development hook (gated)
        assert att._config.ignition_threshold == 0.9  # noqa: SLF001
    finally:
        teardown(kernel, rt, sm, wm, att)
