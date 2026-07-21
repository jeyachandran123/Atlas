"""Conversation Metrics (Objective 15) — one collector per turn; the final
snapshot is persisted onto the turn row for future dashboards."""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class TurnMetrics:
    retrieval_ms: int | None = None
    ranking_ms: int | None = None
    llm_ms: int | None = None
    streaming_ms: int | None = None
    total_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_estimate: float = 0.0       # local Ollama — zero; cloud providers set real rates
    grounding_score: float | None = None
    citation_count: int = 0

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


class ConversationMetricsCollector:
    def __init__(self) -> None:
        self.metrics = TurnMetrics()
        self._start = time.monotonic()

    @contextmanager
    def timed(self, phase: str):
        """with collector.timed('retrieval_ms'): ... — records elapsed ms."""
        start = time.monotonic()
        try:
            yield
        finally:
            setattr(self.metrics, phase, int((time.monotonic() - start) * 1000))

    def finish(self) -> TurnMetrics:
        self.metrics.total_ms = int((time.monotonic() - self._start) * 1000)
        return self.metrics
