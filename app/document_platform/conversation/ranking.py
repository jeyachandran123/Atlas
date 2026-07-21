"""
Ranking Engine (Objective 5) — independent from retrieval: takes retrieved
chunks + manifest facts in, returns confidence-ordered chunks out. Signals
are pluggable; user-feedback and business-rule signals later are one new
RankingSignal subclass each, registered with a weight.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.document_platform.conversation.retrieval import RetrievedChunk
from app.document_platform.semantic.versioning import EMBEDDING_VERSION


@dataclass(frozen=True)
class RankedChunk:
    chunk: RetrievedChunk
    confidence: float                # weighted composite, 0..1
    signal_scores: dict[str, float]


class RankingSignal(ABC):
    name: str = "abstract"
    weight: float = 1.0

    @abstractmethod
    def score(self, chunk: RetrievedChunk, facts: dict[str, Any]) -> float:
        """Return a score in [0, 1] for one chunk."""


class SemanticSimilaritySignal(RankingSignal):
    name = "similarity"
    weight = 0.6

    def score(self, chunk: RetrievedChunk, facts: dict[str, Any]) -> float:
        return max(0.0, min(1.0, chunk.score))


class KnowledgeHealthSignal(RankingSignal):
    name = "health"
    weight = 0.15

    def score(self, chunk: RetrievedChunk, facts: dict[str, Any]) -> float:
        return 1.0 if facts.get("status") == "indexed" else 0.0


class VersionSignal(RankingSignal):
    name = "version"
    weight = 0.1

    def score(self, chunk: RetrievedChunk, facts: dict[str, Any]) -> float:
        return 1.0 if facts.get("embedding_version") == EMBEDDING_VERSION else 0.0


class FreshnessSignal(RankingSignal):
    """Newer knowledge ranks slightly higher; decays over ~180 days."""

    name = "freshness"
    weight = 0.15

    def score(self, chunk: RetrievedChunk, facts: dict[str, Any]) -> float:
        created_at = facts.get("created_at")
        if created_at is None:
            return 0.5
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created_at).total_seconds() / 86400
        return max(0.0, 1.0 - age_days / 180.0)


class RankingEngine:
    name = "multi_signal"

    def __init__(self, signals: list[RankingSignal] | None = None) -> None:
        self._signals = signals or [
            SemanticSimilaritySignal(), KnowledgeHealthSignal(),
            VersionSignal(), FreshnessSignal(),
        ]

    def rank(
        self, chunks: list[RetrievedChunk], manifest_facts: dict[str, dict[str, Any]],
    ) -> list[RankedChunk]:
        total_weight = sum(s.weight for s in self._signals) or 1.0
        ranked = []
        for chunk in chunks:
            facts = manifest_facts.get(chunk.knowledge_id, {})
            scores = {s.name: s.score(chunk, facts) for s in self._signals}
            confidence = sum(scores[s.name] * s.weight for s in self._signals) / total_weight
            ranked.append(RankedChunk(chunk=chunk, confidence=confidence, signal_scores=scores))
        ranked.sort(key=lambda r: r.confidence, reverse=True)
        return ranked
