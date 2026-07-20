"""
Knowledge Health (Objective 9) — computed on read, never stored.

Storing a health column would need a second write path kept in sync with
the manifest and the capability registry; that's a drift bug waiting to
happen. Deriving it fresh from the manifest + the live capability registry
is always correct and costs nothing meaningful at read time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.document_platform.knowledge.lifecycle import KnowledgeLifecycle
from app.platform.capabilities import CapabilityCategory, CapabilityRegistry


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    NEEDS_REPROCESSING = "needs_reprocessing"
    PARSER_OUTDATED = "parser_outdated"
    EMBEDDING_OUTDATED = "embedding_outdated"
    RELATIONSHIP_OUTDATED = "relationship_outdated"
    DEPRECATED = "deprecated"
    FAILED = "failed"


@dataclass(frozen=True)
class HealthReport:
    status: HealthStatus
    reasons: list[str] = field(default_factory=list)


class KnowledgeHealthEvaluator:
    def __init__(self, capability_registry: CapabilityRegistry) -> None:
        self._capabilities = capability_registry

    def evaluate(
        self,
        *,
        lifecycle: KnowledgeLifecycle,
        parser_name: str,
        parser_version: str,
        chunk_version: str,
        job_status: str,
        job_error: str | None,
        warnings: list[str],
        retry_count: int,
    ) -> HealthReport:
        reasons: list[str] = []

        if job_status == "failed" or job_error:
            return HealthReport(HealthStatus.FAILED, [job_error or "processing job failed"])

        if lifecycle == KnowledgeLifecycle.DEPRECATED:
            return HealthReport(HealthStatus.DEPRECATED, ["lifecycle state is deprecated"])

        if lifecycle in (KnowledgeLifecycle.DRAFT, KnowledgeLifecycle.PROCESSING):
            return HealthReport(HealthStatus.NEEDS_REPROCESSING, ["processing not yet complete"])

        current_parser_version = self._capabilities.current_version(
            CapabilityCategory.DOCUMENT_PARSER, parser_name
        )
        if current_parser_version and current_parser_version != parser_version:
            reasons.append(
                f"parser '{parser_name}' has moved to {current_parser_version} "
                f"(this knowledge was built with {parser_version})"
            )
            return HealthReport(HealthStatus.PARSER_OUTDATED, reasons)

        current_chunk_version = self._capabilities.current_version(
            CapabilityCategory.CHUNK_BUILDER, "structure_aware_chunker"
        )
        if current_chunk_version and current_chunk_version != chunk_version:
            reasons.append(f"chunker has moved to {current_chunk_version} (built with {chunk_version})")
            return HealthReport(HealthStatus.RELATIONSHIP_OUTDATED, reasons)

        if retry_count > 0:
            reasons.append(f"required {retry_count} retry(s) during processing")
            return HealthReport(HealthStatus.WARNING, reasons)

        if warnings:
            return HealthReport(HealthStatus.WARNING, list(warnings))

        return HealthReport(HealthStatus.HEALTHY, [])
