"""
Semantic Health (Objective 14) — computed on read, never stored, same
principle as knowledge/health.py: a stored health column would need a
second write path kept in sync with the capability registry, which is a
drift bug waiting to happen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.platform.capabilities import CapabilityCategory, CapabilityRegistry


class SemanticHealthStatus(str, Enum):
    HEALTHY = "healthy"
    GENERATING = "generating"
    NEEDS_REGENERATION = "needs_regeneration"
    PROVIDER_OUTDATED = "provider_outdated"
    MODEL_DEPRECATED = "model_deprecated"
    INDEX_OUTDATED = "index_outdated"
    FAILED = "failed"


@dataclass(frozen=True)
class SemanticHealthReport:
    status: SemanticHealthStatus
    reasons: list[str] = field(default_factory=list)


class SemanticHealthEvaluator:
    def __init__(self, capability_registry: CapabilityRegistry) -> None:
        self._capabilities = capability_registry

    def evaluate(
        self,
        *,
        lifecycle_status: str,
        provider_name: str,
        provider_version: str,
        model_name: str,
        job_status: str,
        job_error: str | None,
    ) -> SemanticHealthReport:
        if job_status == "failed" or job_error:
            return SemanticHealthReport(SemanticHealthStatus.FAILED, [job_error or "embedding job failed"])

        if lifecycle_status in ("queued", "generating", "validating"):
            return SemanticHealthReport(SemanticHealthStatus.GENERATING, ["embedding still in progress"])

        if lifecycle_status == "deprecated":
            return SemanticHealthReport(SemanticHealthStatus.NEEDS_REGENERATION, ["lifecycle marked deprecated"])

        current_version = self._capabilities.current_version(CapabilityCategory.EMBEDDING_PROVIDER, provider_name)
        if current_version and current_version != provider_version:
            return SemanticHealthReport(
                SemanticHealthStatus.PROVIDER_OUTDATED,
                [f"provider '{provider_name}' has moved to {current_version} (embedded with {provider_version})"],
            )

        return SemanticHealthReport(SemanticHealthStatus.HEALTHY, [])
