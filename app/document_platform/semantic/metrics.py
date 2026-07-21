"""Semantic Metrics (Objective 12) — same assembled-on-completion pattern as
processing/metrics.py, riding as the detail payload of the final semantic event."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class SemanticMetrics:
    knowledge_id: str
    provider: str
    model_name: str
    dimension: int
    chunk_count: int
    embedded_count: int
    failed_count: int
    total_duration_ms: int
    generation_ms: int
    validation_ms: int
    indexing_ms: int
    avg_latency_per_chunk_ms: float
    vector_store: str
    collection: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SemanticMetricsCollector:
    def collect(
        self,
        *,
        knowledge_id: str,
        provider: str,
        model_name: str,
        dimension: int,
        chunk_count: int,
        embedded_count: int,
        failed_count: int,
        stage_durations_ms: dict[str, int],
        vector_store: str,
        collection: str,
    ) -> SemanticMetrics:
        total = sum(stage_durations_ms.values())
        gen = stage_durations_ms.get("generate", 0)
        avg = (gen / embedded_count) if embedded_count else 0.0
        return SemanticMetrics(
            knowledge_id=knowledge_id,
            provider=provider,
            model_name=model_name,
            dimension=dimension,
            chunk_count=chunk_count,
            embedded_count=embedded_count,
            failed_count=failed_count,
            total_duration_ms=total,
            generation_ms=gen,
            validation_ms=stage_durations_ms.get("validate", 0),
            indexing_ms=stage_durations_ms.get("index", 0),
            avg_latency_per_chunk_ms=round(avg, 1),
            vector_store=vector_store,
            collection=collection,
        )
