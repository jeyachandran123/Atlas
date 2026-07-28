"""Shared helpers for cognitive-state tests."""

from __future__ import annotations

from typing import Any

from app.cognitive_kernel import Bootstrapper, KernelConfig
from app.cognitive_kernel.contracts import SecurityContext
from app.cognitive_kernel.state import CognitiveStateManager, StateConfig


def make_state(**cfg: Any):
    kernel = Bootstrapper().boot(KernelConfig(identity_name="Atlas", identity_core={"safety_first": True}))
    sm = CognitiveStateManager(kernel.services(), StateConfig(**cfg))
    sm.start()
    ctx = kernel.services().new_context(security=SecurityContext("user", "org"))
    return kernel, sm, ctx


def ctx_with(kernel, *scopes: str):
    return kernel.services().new_context(
        security=SecurityContext("admin", "org", frozenset(scopes))
    )
