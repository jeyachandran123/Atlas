"""Meta-Cognition ports — runtime-routed intervention (no sibling-engine imports).

An intervention *request* is submitted through the Runtime to the **Executive**
(MeL2 — meta cannot bypass governance), addressed by name. Meta never performs the
action; the Executive authorizes and acts. Submission is best-effort (if the
Executive is unavailable the request is recorded, not fatal) and every request is
reversible-by-design (MeL20). A ``FLAG`` recommendation is record-only (no request).
"""

from __future__ import annotations

from typing import Any

from ...runtime import ExecutionRequest
from .contracts import InterventionRecommendation


class RuntimeInterventionPort:
    def __init__(self, runtime: Any) -> None:
        self._rt = runtime

    def submit(self, recommendation: InterventionRecommendation, context: Any) -> bool:
        if not recommendation.target_engine:
            return False  # FLAG — record-only, no runtime request
        try:
            handle = self._rt.submit(ExecutionRequest(
                engine=recommendation.target_engine, operation=recommendation.target_op,
                payload=dict(recommendation.payload),
                correlation_id=getattr(context, "correlation_id", None),
                security=getattr(context, "security", None),
            ))
            self._rt.drain()
            return handle.result().error is None
        except Exception:  # governance unavailable -> recorded, never fatal (MeL5)
            return False


class NullInterventionPort:
    def submit(self, recommendation: InterventionRecommendation, context: Any) -> bool:
        return False
