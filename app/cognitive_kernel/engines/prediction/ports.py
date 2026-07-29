"""Prediction ports — read-only, runtime-routed (no sibling-engine imports).

Prediction consumes conscious content only through Working Memory and responds
only to Executive requests — always via the Runtime, addressed by engine *name*,
never by importing or holding a sibling engine (so "no direct engine-to-engine
communication" is structurally true). ``RuntimePredictionPort`` is the adapter the
Executive uses to reach Prediction (it implements the Executive's ``PredictionRiskPort``
contract) — again through the Runtime only.
"""

from __future__ import annotations

from typing import Any, Mapping

from ...runtime import ExecutionRequest


class RuntimeWMReadPort:
    """Reads the conscious focus via WM's public broadcast op, resolving targets
    from Cognitive State **read-only**. Prediction never mutates Working Memory."""

    def __init__(self, runtime: Any, state: Any, engine_name: str = "working_memory") -> None:
        self._rt = runtime
        self._state = state
        self._name = engine_name

    def conscious_refs(self, context: Any) -> list[str]:
        handle = self._rt.submit(ExecutionRequest(
            engine=self._name, operation="broadcast", payload={"workspace": None},
            correlation_id=getattr(context, "correlation_id", None),
            security=getattr(context, "security", None),
        ))
        self._rt.drain()
        result = handle.result()
        if result.error:
            return []
        targets: list[str] = []
        for ref_handle in (result.value or []):
            if self._state.exists(ref_handle):
                target = self._state.get(ref_handle).payload.get("target")
                if target:
                    targets.append(target)
        return sorted(set(targets))


class NullWMReadPort:
    """No Working Memory wired — the request carries its own context."""

    def conscious_refs(self, context: Any) -> list[str]:
        return []


class NullReasoningFeedbackPort:
    """No reasoning feedback wired (PrL22 reconciliation is inbound and optional)."""

    def note_outcome(self, request_id: str, observed: float, context: Any) -> None:
        return None


class RuntimePredictionPort:
    """The adapter the Executive uses to request risk/forecasts from Prediction —
    routed through the Runtime by name. Implements the Executive's ``PredictionRiskPort``."""

    def __init__(self, runtime: Any, engine_name: str = "prediction") -> None:
        self._rt = runtime
        self._name = engine_name

    def available(self) -> bool:
        return True

    def request(self, scenario: Mapping[str, Any], context: Any) -> Mapping[str, Any] | None:
        handle = self._rt.submit(ExecutionRequest(
            engine=self._name, operation="assess_risk", payload=dict(scenario),
            correlation_id=getattr(context, "correlation_id", None),
            security=getattr(context, "security", None),
        ))
        self._rt.drain()
        result = handle.result()
        if result.error:
            return None
        return result.value
