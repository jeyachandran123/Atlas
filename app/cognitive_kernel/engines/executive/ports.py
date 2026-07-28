"""Executive control ports — coordination through the Runtime only (ExL8).

Every faculty the executive governs is reached by submitting a runtime
``ExecutionRequest`` addressed to the engine *by name* — never by importing or
holding a reference to a sibling engine. This is the mechanism that makes "no
direct engine-to-engine communication" structurally true: these ports know only
the Runtime and a string. The Prediction/Risk port is null until a Prediction
engine is wired (the executive requests forecasts; it never predicts).
"""

from __future__ import annotations

from typing import Any, Mapping

from ...runtime import ExecutionRequest


class _RuntimePort:
    def __init__(self, runtime: Any, engine_name: str) -> None:
        self._rt = runtime
        self._name = engine_name

    def _run(self, operation: str, payload: Mapping[str, Any], context: Any) -> Any:
        handle = self._rt.submit(
            ExecutionRequest(
                engine=self._name, operation=operation, payload=dict(payload),
                correlation_id=context.correlation_id, security=context.security,
            )
        )
        self._rt.drain()
        result = handle.result()
        if result.error:
            raise RuntimeError(f"{self._name}.{operation} failed: {result.error}")
        return result.value


class RuntimeReasoningPort(_RuntimePort):
    """Directs and invokes the Reasoning faculty via the Runtime (ExL10)."""

    def __init__(self, runtime: Any, engine_name: str = "reasoning") -> None:
        super().__init__(runtime, engine_name)

    def set_strategy(self, strategy: str, context: Any) -> None:
        self._run("set_strategy_directive", {"strategy": strategy}, context)

    def set_deliberation(self, context: Any, *, max_steps: int | None = None, depth: int | None = None) -> None:
        self._run("set_deliberation", {"max_steps": max_steps, "depth": depth}, context)

    def reason(self, request: Mapping[str, Any], context: Any) -> Mapping[str, Any] | None:
        return self._run("reason", request, context)


class RuntimeAttentionPort(_RuntimePort):
    """Biases the Attention competition via the Runtime (Phase 3 Ch6; bounded by safety)."""

    def __init__(self, runtime: Any, engine_name: str = "attention") -> None:
        super().__init__(runtime, engine_name)

    def bias(self, target: str, delta: float, context: Any) -> None:
        self._run("set_executive_bias", {"target": target, "delta": delta}, context)


class NullPredictionRiskPort:
    """Default risk/prediction hook: no Prediction engine wired (items 20, 21)."""

    def available(self) -> bool:
        return False

    def request(self, scenario: Mapping[str, Any], context: Any) -> Mapping[str, Any] | None:
        return None
