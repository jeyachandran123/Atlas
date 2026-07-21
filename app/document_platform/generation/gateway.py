"""
Generation Gateway — validates the request, mints the artifact + correlation,
executes plan → transform → build → store through the lifecycle, and owns
the transaction. Storage goes through the existing BlobStorage abstraction
(S3 in production); downloads prefer presigned URLs and fall back to
proxying bytes — the same dual-mode pattern the DIP document service proved.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.document_platform.generation.builders.factory import (
    UnknownFormatError,
    get_builder_factory,
)
from app.document_platform.generation.events import (
    GenerationEvent,
    GenerationEventType,
    PersistingGenerationEventPublisher,
)
from app.document_platform.generation.lifecycle import GenerationLifecycle
from app.document_platform.generation.metrics import GenerationMetricsCollector
from app.document_platform.generation.planner import GenerationPlanner, PlanningError
from app.document_platform.generation.repository import GenerationRepository
from app.document_platform.generation.transformer import (
    TransformationEngine,
    TransformationError,
)
from app.document_platform.semantic.repository import SemanticRepository
from app.storage import get_blob_storage

STORAGE_PREFIX = "generated_artifacts"

_SLUG = re.compile(r"[^a-z0-9]+")


def _slugify(title: str) -> str:
    return _SLUG.sub("-", title.lower()).strip("-")[:80] or "artifact"


@dataclass
class DownloadInfo:
    mode: str                        # "signed_url" | "proxy"
    url: Optional[str]
    expires_in: Optional[int]
    filename: str
    content_type: str


class GenerationGateway:
    def __init__(self, db: AsyncSession) -> None:
        cfg = get_settings()
        self._db = db
        self._repo = GenerationRepository(db)
        self._events = PersistingGenerationEventPublisher(self._repo)
        self._planner = GenerationPlanner(SemanticRepository(db))
        self._transformer = TransformationEngine()
        self._factory = get_builder_factory()
        self._storage = get_blob_storage(STORAGE_PREFIX)
        self._signed_ttl = cfg.dip_signed_url_ttl_seconds

    async def generate(
        self, user_id: str, org_id: str, prompt: str, format_name: str,
        document_id: str | None = None,
    ):
        builder = self._factory.get(format_name)   # UnknownFormatError → 422 upstream
        artifact = await self._repo.create_artifact(
            user_id, org_id, prompt, format_name, document_id,
        )
        result = artifact
        async for kind, payload in self._pipeline(
            artifact, builder, prompt, org_id, document_id,
        ):
            if kind in ("ready", "failed"):
                result = payload
        return result

    async def generate_stream(
        self, user_id: str, org_id: str, prompt: str, format_name: str,
        document_id: str | None = None,
    ):
        """SSE variant: emits live per-stage progress (planning → shaping →
        building → storing) so the UI can show what is actually happening,
        then a final `done` with the artifact summary. Same pipeline, same
        lifecycle, same registry rows as generate()."""
        import json as _json

        def fmt(event: str, payload: dict) -> str:
            return f"event: {event}\ndata: {_json.dumps(payload)}\n\n"

        try:
            builder = self._factory.get(format_name)
        except Exception as e:
            yield fmt("error", {"message": str(e)})
            return
        artifact = await self._repo.create_artifact(
            user_id, org_id, prompt, format_name, document_id,
        )
        yield fmt("meta", {"artifact_id": artifact.id,
                           "correlation_id": artifact.correlation_id,
                           "format": format_name})
        final = artifact
        async for kind, payload in self._pipeline(
            artifact, builder, prompt, org_id, document_id,
        ):
            if kind == "stage":
                yield fmt("stage", payload)
            else:
                final = payload
        yield fmt("done", {
            "artifact_id": final.id, "status": final.status,
            "title": final.title, "filename": final.filename,
            "format": final.format, "size_bytes": final.size_bytes,
            "checksum": final.checksum, "grounded": final.grounded,
            "error": final.error, "total_ms": final.total_ms,
        })

    async def _pipeline(
        self, artifact, builder, prompt: str, org_id: str,
        document_id: str | None,
    ):
        """The one generation pipeline. Yields ("stage", {stage, detail})
        progress tuples, then exactly one terminal ("ready"|"failed",
        artifact). Owns lifecycle transitions, events, and the commit."""
        collector = GenerationMetricsCollector()
        await self._publish(artifact, GenerationEventType.GENERATION_REQUESTED,
                            detail={"format": artifact.format})
        try:
            # ── Plan (LLM decides WHAT) ─────────────────────────────────────
            yield "stage", {"stage": "planning",
                            "detail": {"note": "AI is planning the document content"}}
            await self._repo.transition(artifact, GenerationLifecycle.PLANNING)
            with collector.timed("planning_ms"):
                plan = await self._planner.plan(prompt, org_id, artifact.format, document_id)
            collector.metrics.prompt_tokens = plan.prompt_tokens
            collector.metrics.completion_tokens = plan.completion_tokens
            await self._publish(artifact, GenerationEventType.PLAN_COMPLETED,
                                duration_ms=collector.metrics.planning_ms,
                                detail={"grounded": plan.grounded,
                                        "sources": len(plan.source_knowledge_ids)})

            # ── Transform (engine decides HOW data is shaped) ───────────────
            yield "stage", {"stage": "shaping_content",
                            "detail": {"grounded": plan.grounded}}
            await self._repo.transition(artifact, GenerationLifecycle.TRANSFORMING)
            with collector.timed("transform_ms"):
                model = self._transformer.transform(plan.spec)
            await self._publish(artifact, GenerationEventType.TRANSFORM_COMPLETED,
                                duration_ms=collector.metrics.transform_ms,
                                detail={"sections": len(model.sections),
                                        "tables": len(model.tables)})

            # ── Build (builder decides HOW the file is written) ─────────────
            yield "stage", {"stage": "building_file",
                            "detail": {"format": builder.format_name,
                                       "sections": len(model.sections)}}
            await self._repo.transition(artifact, GenerationLifecycle.BUILDING)
            with collector.timed("build_ms"):
                data = builder.build(model)
            checksum = hashlib.sha256(data).hexdigest()
            collector.metrics.size_bytes = len(data)
            await self._publish(artifact, GenerationEventType.BUILD_COMPLETED,
                                duration_ms=collector.metrics.build_ms,
                                detail={"builder": builder.format_name,
                                        "size_bytes": len(data)})

            # ── Store (storage decides WHERE) ───────────────────────────────
            yield "stage", {"stage": "storing",
                            "detail": {"size_bytes": len(data)}}
            await self._repo.transition(artifact, GenerationLifecycle.STORING)
            storage_key = f"{org_id}/{artifact.id}.{builder.extension}"
            with collector.timed("store_ms"):
                await self._storage.put(storage_key, data, builder.content_type)
            await self._publish(artifact, GenerationEventType.ARTIFACT_STORED,
                                duration_ms=collector.metrics.store_ms,
                                detail={"storage_key": storage_key})

            # ── Ready ───────────────────────────────────────────────────────
            await self._repo.transition(artifact, GenerationLifecycle.READY)
            filename = f"{_slugify(model.title)}.{builder.extension}"
            await self._repo.finish_artifact(
                artifact, metrics=collector.finish(), title=model.title,
                filename=filename, storage_key=storage_key,
                content_type=builder.content_type, checksum=checksum,
                size_bytes=len(data), builder_name=builder.format_name,
                builder_version=builder.version, grounded=plan.grounded,
                source_knowledge_ids=plan.source_knowledge_ids,
                llm_provider=plan.llm_provider, llm_model=plan.llm_model,
            )
            await self._publish(artifact, GenerationEventType.ARTIFACT_READY,
                                duration_ms=collector.metrics.total_ms,
                                detail={"checksum": checksum})
            await self._db.commit()
            yield "ready", artifact
        except (PlanningError, TransformationError, Exception) as e:
            if not isinstance(e, (PlanningError, TransformationError)):
                logger.exception(f"Generation {artifact.id} crashed: {e}")
            await self._repo.transition(artifact, GenerationLifecycle.FAILED)
            await self._repo.finish_artifact(
                artifact, metrics=collector.finish(), error=str(e)[:2000],
            )
            await self._publish(artifact, GenerationEventType.GENERATION_FAILED,
                                status="failed", detail={"error": str(e)[:500]})
            await self._db.commit()
            yield "failed", artifact

    # ── Download Service (Objective 13) ──────────────────────────────────────

    async def download(self, artifact) -> tuple[DownloadInfo, Optional[bytes]]:
        """Signed URL when the backend can mint one; proxied bytes otherwise."""
        url = await self._storage.signed_url(
            artifact.storage_key, expires_in=self._signed_ttl,
            download_filename=artifact.filename,
        )
        if url is not None:
            info = DownloadInfo(
                mode="signed_url", url=url, expires_in=self._signed_ttl,
                filename=artifact.filename, content_type=artifact.content_type,
            )
            data = None
        else:
            data = await self._storage.get(artifact.storage_key)
            info = DownloadInfo(
                mode="proxy", url=None, expires_in=None,
                filename=artifact.filename, content_type=artifact.content_type,
            )
        await self._publish(artifact, GenerationEventType.ARTIFACT_DOWNLOADED,
                            detail={"mode": info.mode})
        await self._db.commit()
        return info, data

    async def _publish(
        self, artifact, event_type: GenerationEventType,
        status: str = "completed", duration_ms: int | None = None,
        detail: dict | None = None,
    ) -> None:
        await self._events.publish(GenerationEvent(
            event_type=event_type, artifact_id=artifact.id,
            correlation_id=artifact.correlation_id, status=status,
            duration_ms=duration_ms, detail=detail or {},
        ))
