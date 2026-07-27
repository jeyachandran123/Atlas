"""Shared helpers for runtime tests (imported normally; works with --noconftest)."""

from __future__ import annotations

from typing import Any, Mapping

from app.cognitive_kernel import Bootstrapper, KernelConfig
from app.cognitive_kernel.contracts import ExecutionContext
from app.cognitive_kernel.runtime import CognitiveRuntime, RuntimeConfig


def make_runtime(**cfg: Any) -> tuple[Any, CognitiveRuntime]:
    kernel = Bootstrapper().boot(
        KernelConfig(identity_name="Atlas", identity_core={"safety_first": True})
    )
    runtime = CognitiveRuntime(kernel.services(), RuntimeConfig(**cfg))
    runtime.start()
    return kernel, runtime


class FakeEngine:
    """A minimal ExecutableEngine used to prove orchestration (no cognition)."""

    def __init__(self, fn=None) -> None:
        self._fn = fn or (lambda op, payload, ctx: {"op": op, "echo": dict(payload)})
        self.calls: list[str] = []

    def execute(self, operation: str, payload: Mapping[str, Any], context: ExecutionContext) -> Any:
        self.calls.append(operation)
        return self._fn(operation, payload, context)
