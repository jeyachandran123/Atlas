"""
Reasoning Trace.

Assembles the complete internal reasoning record for a single request.
Internal only — never exposed to users.
Used for debugging, observability, and adaptive learning.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator

from loguru import logger

from app.intelligence.reasoning.models import ReasoningTrace


class ReasoningTraceBuilder:
    """
    Builds a ReasoningTrace incrementally as the reasoning pipeline executes.
    Used as a context manager for timing each stage.
    """

    def __init__(self, request_id: str) -> None:
        self._trace = ReasoningTrace(request_id=request_id)
        self._start = time.monotonic()

    @contextmanager
    def measure(self, stage: str) -> Generator[None, None, None]:
        t = time.monotonic()
        try:
            yield
        finally:
            elapsed_ms = (time.monotonic() - t) * 1000
            self._record_timing(stage, elapsed_ms)

    def _record_timing(self, stage: str, ms: float) -> None:
        mapping = {
            "goal":         "goal_analysis_ms",
            "rewrite":      "query_rewrite_ms",
            "decompose":    "decomposition_ms",
            "plan":         "planning_ms",
            "confidence":   "confidence_ms",
            "validate":     "validation_ms",
            "reflect":      "reflection_ms",
        }
        attr = mapping.get(stage)
        if attr:
            setattr(self._trace, attr, ms)

    def set_goal(self, goal) -> None:
        self._trace.inferred_goal = goal

    def set_rewritten_query(self, query) -> None:
        self._trace.rewritten_query = query

    def set_decomposition(self, decomposition) -> None:
        self._trace.task_decomposition = decomposition

    def set_execution_plan(self, plan) -> None:
        self._trace.execution_plan = plan
        self._trace.reasoning_depth = plan.reasoning_depth

    def set_confidence(self, report) -> None:
        self._trace.confidence_report = report

    def set_validation(self, result) -> None:
        self._trace.strategy_validation = result

    def set_reflection(self, result) -> None:
        self._trace.reflection = result

    def set_expansion_plan(self, plan) -> None:
        self._trace.expansion_plan = plan

    def set_active_goal_context(self, context) -> None:
        self._trace.active_goal_context = context

    def add_quality_signal(self, signal) -> None:
        self._trace.quality_signals.append(signal)

    def build(self) -> ReasoningTrace:
        self._trace.total_ms = (time.monotonic() - self._start) * 1000
        self._log()
        return self._trace

    def _log(self) -> None:
        t = self._trace
        goal_type = t.inferred_goal.goal_type.value if t.inferred_goal else "unknown"
        confidence = t.confidence_report.overall if t.confidence_report else 0.0
        depth = t.reasoning_depth.value if t.reasoning_depth else "unknown"

        logger.debug(
            "Reasoning pipeline complete",
            extra={
                "request_id": t.request_id,
                "goal_type": goal_type,
                "confidence": round(confidence, 2),
                "depth": depth,
                "tasks": t.task_decomposition.total_tasks if t.task_decomposition else 0,
                "steps": t.execution_plan.total_steps if t.execution_plan else 0,
                "reflection": t.reflection.verdict.value if t.reflection else "none",
                "total_ms": round(t.total_ms, 1),
                "signals": len(t.quality_signals),
            },
        )
