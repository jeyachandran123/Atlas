"""Generation Metrics (Objective 17) — one collector per generation."""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class GenerationMetrics:
    planning_ms: int | None = None
    transform_ms: int | None = None
    build_ms: int | None = None
    store_ms: int | None = None
    total_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    size_bytes: int = 0


class GenerationMetricsCollector:
    def __init__(self) -> None:
        self.metrics = GenerationMetrics()
        self._start = time.monotonic()

    @contextmanager
    def timed(self, phase: str):
        start = time.monotonic()
        try:
            yield
        finally:
            setattr(self.metrics, phase, int((time.monotonic() - start) * 1000))

    def finish(self) -> GenerationMetrics:
        self.metrics.total_ms = int((time.monotonic() - self._start) * 1000)
        return self.metrics
