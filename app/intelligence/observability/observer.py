"""
Intelligence Observability.

Produces an IntelligenceTrace for every request through the engine.
Every decision made by every module is recorded here for debugging.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator

from loguru import logger

from app.intelligence.models import IntelligenceTrace


@dataclass
class _Timer:
    name: str
    _start: float = field(default_factory=time.monotonic, init=False)

    def elapsed_ms(self) -> float:
        return (time.monotonic() - self._start) * 1000


class IntelligenceObserver:
    """
    Collects timing and decision metadata for a single request.
    Used as a context manager within the engine.
    """

    def __init__(self, request_id: str, message_preview: str) -> None:
        self._trace = IntelligenceTrace(
            request_id=request_id,
            user_message_preview=message_preview[:100],
        )
        self._start = time.monotonic()

    @contextmanager
    def measure(self, stage: str) -> Generator[None, None, None]:
        t = _Timer(stage)
        try:
            yield
        finally:
            elapsed = t.elapsed_ms()
            self._record_timing(stage, elapsed)

    def _record_timing(self, stage: str, ms: float) -> None:
        mapping = {
            "intent":       "intent_ms",
            "complexity":   "complexity_ms",
            "conversation": "conversation_ms",
            "policy":       "policy_ms",
            "context":      "context_build_ms",
            "prompt":       "prompt_compose_ms",
            "llm":          "llm_ms",
            "review":       "review_ms",
        }
        attr = mapping.get(stage)
        if attr:
            setattr(self._trace, attr, ms)

    def record_intent(self, intents: list[str], confidence: float) -> None:
        self._trace.detected_intents = intents
        self._trace.primary_intent_confidence = confidence

    def record_complexity(self, level: str) -> None:
        self._trace.complexity_level = level

    def record_conversation(self, turn_type: str) -> None:
        self._trace.conversation_turn_type = turn_type

    def record_policy(self, decision: str) -> None:
        self._trace.policy_decision = decision

    def record_persona(self, persona: str) -> None:
        self._trace.selected_persona = persona

    def record_strategy(self, strategy: str) -> None:
        self._trace.selected_strategy = strategy

    def record_tool_plan(self, tool_plan) -> None:
        self._trace.tool_plan = tool_plan

    def record_review(self, decision: str) -> None:
        self._trace.review_decision = decision

    def record_prompt_modules(self, modules: list[str], token_estimate: int) -> None:
        self._trace.prompt_modules_used = modules
        self._trace.prompt_token_estimate = token_estimate

    def finalize(self) -> IntelligenceTrace:
        self._trace.total_ms = (time.monotonic() - self._start) * 1000
        self._log()
        return self._trace

    def _log(self) -> None:
        t = self._trace
        logger.debug(
            "Intelligence pipeline complete",
            extra={
                "request_id": t.request_id,
                "intent": t.detected_intents[0] if t.detected_intents else "unknown",
                "confidence": round(t.primary_intent_confidence, 2),
                "complexity": t.complexity_level,
                "persona": t.selected_persona,
                "strategy": t.selected_strategy,
                "policy": t.policy_decision,
                "review": t.review_decision,
                "total_ms": round(t.total_ms, 1),
                "prompt_modules": len(t.prompt_modules_used),
            },
        )
