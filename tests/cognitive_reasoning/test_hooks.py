"""Integration hooks: executive, prediction, meta-cognitive, learning, development."""

from __future__ import annotations

import pytest

from app.cognitive_kernel.contracts import SecurityContext
from app.cognitive_kernel.engines.reasoning import (
    ReasoningConfig,
    ReasoningRequest,
    ReasoningSecurityError,
    ReasoningStrategy,
    ReasoningType,
)

from ._rz import assertion, cause, conscious, make_reasoning, teardown


def test_executive_strategy_directive_biases_selection() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        rz.set_strategy_directive(ReasoningStrategy.FAST_HEURISTIC, ctx)  # executive hook (item 33)
        assert rz._strategy_directive is ReasoningStrategy.FAST_HEURISTIC  # noqa: SLF001
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_executive_deliberation_directive_bounds_depth() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        rz.set_deliberation_directive(ctx, max_steps=1, depth=2)
        assert rz._deliberation_directive == {"max_steps": 1, "depth": 2}  # noqa: SLF001
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_prediction_hook_reports_unavailable_by_default() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        # Reasoning never predicts; it requests. No Prediction engine is wired (item 34).
        assert rz.request_prediction({"scenario": "what_if"}, ctx) is None
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_metacognitive_inspection_is_readonly() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        a = assertion(state, ctx, "a", confidence=0.9)
        conscious(wm_api, [a], ctx)
        view = rz.inspect()  # meta-cognitive hook (item 35)
        assert "metrics" in view and "engines" in view and "fatigue" in view
        assert view["prediction_available"] is False
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_learning_candidate_hook_exposes_proposals() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        insts = [assertion(state, ctx, f"swan{i}.white", confidence=1.0) for i in range(3)]
        conscious(wm_api, insts, ctx)
        res = rz.reason(ReasoningRequest(goal="generalise", type_hint=ReasoningType.INDUCTIVE), ctx)
        cands = rz.learning_candidates(res.episode_id)  # proposals for Learning (item 36)
        assert cands and cands[0].payload["generalization"] == res.conclusion.statement
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_feedback_hook_records_signal() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        rz.feedback("some-belief", "confirmed", ctx)  # reasoning records; it never learns
        assert len(rz._feedback_log) == 1 and rz._feedback_log[0][1] == "confirmed"  # noqa: SLF001
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_development_adaptation_requires_admin() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        with pytest.raises(ReasoningSecurityError):
            rz.set_config(ReasoningConfig(confidence_sufficient=0.9), ctx)  # non-admin
        admin = kernel.services().new_context(
            security=SecurityContext("dev", "org", frozenset({"state:admin"}))
        )
        rz.set_config(ReasoningConfig(confidence_sufficient=0.9), admin)  # gated (item 37)
        assert rz._config.confidence_sufficient == 0.9  # noqa: SLF001
    finally:
        teardown(kernel, rt, state, wm, rz)
