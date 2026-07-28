"""The Trace / Justification Builder (Phase 4, Ch2 §11; ReL5).

Records every reasoning step — premise, type, strategy, engine, product,
confidence — and assembles the human-readable justification. A conclusion without
a trace is inadmissible (ReL5): reasoning must be observable, explainable, and
auditable. The builder only records; it never influences the reasoning.
"""

from __future__ import annotations

import hashlib
import json

from .contracts import Conclusion, ReasoningStep, ReasoningStrategy, ReasoningType


class TraceBuilder:
    def __init__(self) -> None:
        self._steps: list[ReasoningStep] = []

    def record(
        self,
        *,
        rtype: ReasoningType,
        strategy: ReasoningStrategy,
        engine: str,
        premises: tuple[str, ...],
        product: str,
        confidence: float,
        rationale: str,
        depth: int = 0,
    ) -> ReasoningStep:
        step = ReasoningStep(
            index=len(self._steps), rtype=rtype, strategy=strategy, engine=engine,
            premises=premises, product=product, confidence=round(confidence, 6),
            rationale=rationale, depth=depth,
        )
        self._steps.append(step)
        return step

    def steps(self) -> tuple[ReasoningStep, ...]:
        return tuple(self._steps)

    def count(self) -> int:
        return len(self._steps)

    def explain(self, conclusion: Conclusion | None) -> str:
        """Assemble the auditable justification narrative from the trace."""
        lines = []
        for s in self._steps:
            prem = f" from [{', '.join(s.premises)}]" if s.premises else ""
            lines.append(
                f"#{s.index} [{s.rtype.value}/{s.strategy.value} via {s.engine}] "
                f"{s.product}{prem} (conf {s.confidence:.3f}) — {s.rationale}"
            )
        if conclusion is not None:
            neg = "¬" if conclusion.negated else ""
            lines.append(
                f"=> conclude {neg}{conclusion.statement} at confidence {conclusion.confidence:.3f} "
                f"({conclusion.uncertainty.value} uncertainty)"
            )
            if conclusion.contradictions:
                lines.append(f"   contradictions handled: {list(conclusion.contradictions)}")
            if conclusion.assumptions:
                lines.append(f"   rests on assumptions: {list(conclusion.assumptions)}")
        return "\n".join(lines)

    def digest(self) -> str:
        blob = json.dumps(
            [
                [s.index, s.rtype.value, s.strategy.value, s.engine, list(s.premises), s.product,
                 s.confidence, s.depth]
                for s in self._steps
            ],
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()
