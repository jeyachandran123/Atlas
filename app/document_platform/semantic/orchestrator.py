"""
EmbeddingOrchestrator (Objective 1) — the only coordinator for semantic
processing. Providers, validators, and registries never coordinate
workflow; they only do their one job when the orchestrator calls them.

Structurally mirrors ProcessingOrchestrator (Phase 2.5) on purpose: same
stage()-closure timing/event pattern, same retry+DLQ shape, same
lifecycle+registry split. Consumes the frozen Knowledge Platform read-only
and never modifies it, aside from the one documented placeholder column
(KnowledgeObject.embedding_status) Phase 2.5 reserved for this exact use.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.document_platform.semantic.embedding_registry import EmbeddingRegistry
from app.document_platform.semantic.events import (
    PersistingSemanticEventPublisher,
    SemanticEvent,
    SemanticEventPublisher,
    SemanticEventType,
)
from app.document_platform.semantic.index_manager import SemanticIndexManager
from app.document_platform.semantic.metrics import SemanticMetricsCollector
from app.document_platform.semantic.providers import (
    AbstractEmbeddingProvider,
    EmbeddingProviderError,
    get_embedding_provider,
)
from app.document_platform.semantic.queue import enqueue_embedding_job, get_embedding_dead_letter_sink
from app.document_platform.semantic.repository import SemanticRepository
from app.document_platform.semantic.semantic_registry import SemanticRegistry
from app.document_platform.semantic.validation import EmbeddingValidationError, EmbeddingValidator
from app.document_platform.semantic.vector_store import (
    VectorRecord,
    collection_name_for,
    get_vector_store,
)
from app.document_platform.semantic.versioning import EMBEDDING_VERSION, SCHEMA_VERSION, VECTOR_VERSION
from app.document_platform.processing.retry import DEFAULT_RETRY_POLICY, RetryPolicy


class SemanticProcessingFailure(Exception):
    def __init__(self, stage: str, message: str) -> None:
        self.stage = stage
        super().__init__(message)


class EmbeddingOrchestrator:
    def __init__(
        self,
        db: AsyncSession,
        *,
        provider: AbstractEmbeddingProvider | None = None,
        validator: EmbeddingValidator | None = None,
        retry_policy: RetryPolicy | None = None,
        event_publisher: SemanticEventPublisher | None = None,
        metrics_collector: SemanticMetricsCollector | None = None,
    ) -> None:
        self._repo = SemanticRepository(db)
        self._provider = provider or get_embedding_provider()
        self._validator = validator or EmbeddingValidator()
        self._retry_policy = retry_policy or DEFAULT_RETRY_POLICY
        self._events: SemanticEventPublisher = event_publisher or PersistingSemanticEventPublisher(self._repo)
        self._metrics = metrics_collector or SemanticMetricsCollector()
        self._embeddings = EmbeddingRegistry(self._repo, self._events)
        self._semantic = SemanticRegistry(self._repo)
        self._index_manager = SemanticIndexManager(self._repo)
        self._vector_store = get_vector_store()
        self._dlq = get_embedding_dead_letter_sink()

    async def run(self, knowledge_id: str, job_id: str) -> None:
        job = await self._repo.get_job(job_id)
        if job is None:
            logger.warning(f"Embedding job {job_id}: job row missing — skipped")
            return
        ko = await self._repo.get_knowledge(knowledge_id)
        if ko is None:
            logger.warning(f"Embedding job {job_id}: knowledge object {knowledge_id} missing — skipped")
            await self._repo.job_finished(job, "failed", "knowledge object not found", dead_lettered=True)
            return

        correlation_id = job.correlation_id
        attempt = job.attempt
        timings_ms: dict[str, int] = {}
        current_stage = ""

        await self._events.publish(job.id, SemanticEvent(
            event_type=SemanticEventType.EMBEDDING_QUEUED,
            knowledge_id=knowledge_id, correlation_id=correlation_id,
            detail={"attempt": attempt},
        ))
        await self._repo.job_started(job)
        await self._repo.update_knowledge_embedding_status(knowledge_id, "generating")

        async def stage(name: str, fn, *args, **kwargs) -> Any:
            nonlocal current_stage
            current_stage = name
            await self._repo.job_stage(job, name)
            started = time.monotonic()
            try:
                result = fn(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
            except Exception as e:
                ms = int((time.monotonic() - started) * 1000)
                timings_ms[name] = ms
                raise SemanticProcessingFailure(name, str(e)) from e
            timings_ms[name] = int((time.monotonic() - started) * 1000)
            return result

        try:
            # Idempotent re-embedding: wipe prior derived output for this
            # knowledge object before generating fresh embeddings.
            await self._repo.wipe_embeddings_for_knowledge(knowledge_id)

            chunks = await stage("load", self._repo.get_chunks, knowledge_id)
            if not chunks:
                raise SemanticProcessingFailure("load", "knowledge object has no chunks to embed")

            document = await self._repo.get_document(ko.document_id)
            org_id = document.org_id if document else "default"
            collection = collection_name_for(org_id)

            await self._events.publish(job.id, SemanticEvent(
                event_type=SemanticEventType.EMBEDDING_STARTED,
                knowledge_id=knowledge_id, correlation_id=correlation_id,
                provider=self._provider.name, detail={"chunk_count": len(chunks)},
            ))

            try:
                results = await stage("generate", self._provider.embed, [c.content for c in chunks])
            except EmbeddingProviderError as e:
                raise SemanticProcessingFailure("generate", str(e)) from e

            if len(results) != len(chunks):
                raise SemanticProcessingFailure(
                    "generate", f"provider returned {len(results)} vectors for {len(chunks)} chunks",
                )

            # ── Validate + register each chunk's embedding ────────────────────
            embedding_records = []
            started_validate = time.monotonic()
            for chunk, result in zip(chunks, results):
                duplicate = await self._embeddings.find_duplicate(chunk.id, EMBEDDING_VERSION)
                try:
                    self._validator.validate(
                        result,
                        expected_dimensions=self._provider.dimensions,
                        knowledge_exists=True,
                        is_duplicate=duplicate is not None,
                    )
                except EmbeddingValidationError as e:
                    raise SemanticProcessingFailure("validate", f"chunk {chunk.seq}: {'; '.join(e.reasons)}") from e

                record = await self._embeddings.register(
                    job_id=job.id, knowledge_id=knowledge_id, chunk_id=chunk.id, result=result,
                    provider_name=self._provider.name, provider_version=self._provider.version,
                    model_name=self._provider.model_name, model_version="1.0.0",
                    embedding_version=EMBEDDING_VERSION, correlation_id=correlation_id,
                )
                embedding_records.append((chunk, result, record))
            timings_ms["validate"] = int((time.monotonic() - started_validate) * 1000)

            # ── Store vectors ──────────────────────────────────────────────────
            vector_records = [
                VectorRecord(
                    id=record.id, text=chunk.content, embedding=result.vector,
                    metadata={
                        "knowledge_id": knowledge_id, "document_id": ko.document_id,
                        "chunk_id": chunk.id, "seq": chunk.seq,
                        "section_path": chunk.section_path, "node_type": chunk.node_type,
                    },
                )
                for chunk, result, record in embedding_records
            ]
            await stage("store_vectors", self._vector_store.upsert, collection, vector_records)

            for _, _, record in embedding_records:
                await self._embeddings.mark_indexed(job.id, record, correlation_id)

            # ── Index (Objective 9) ─────────────────────────────────────────────
            index = await stage(
                "index", self._index_manager.get_or_create,
                collection_name=collection, embedding_version=EMBEDDING_VERSION,
                vector_store_provider=self._vector_store.name, dimension=self._provider.dimensions,
            )
            await self._index_manager.record_upsert(index, self._vector_store, collection)

            # ── Semantic Registry (Objective 8) ─────────────────────────────────
            await stage(
                "register_semantic", self._semantic.register,
                knowledge_id=knowledge_id, vector_store_provider=self._vector_store.name,
                collection_name=collection, index_name=index.index_name,
                embedding_version=EMBEDDING_VERSION, provider_name=self._provider.name,
                model_name=self._provider.model_name, dimension=self._provider.dimensions,
                embedding_count=len(embedding_records), correlation_id=correlation_id,
            )

            await self._repo.update_knowledge_embedding_status(knowledge_id, "completed")
            await self._repo.job_finished(job, "completed")

            metrics = self._metrics.collect(
                knowledge_id=knowledge_id, provider=self._provider.name,
                model_name=self._provider.model_name, dimension=self._provider.dimensions,
                chunk_count=len(chunks), embedded_count=len(embedding_records), failed_count=0,
                stage_durations_ms=timings_ms, vector_store=self._vector_store.name, collection=collection,
            )
            await self._events.publish(job.id, SemanticEvent(
                event_type=SemanticEventType.EMBEDDING_VERIFIED,
                knowledge_id=knowledge_id, correlation_id=correlation_id,
                provider=self._provider.name, version=EMBEDDING_VERSION,
                latency_ms=sum(timings_ms.values()), detail=metrics.to_dict(),
            ))
            logger.info(
                f"Knowledge {knowledge_id} → semantic ready "
                f"(embeddings={len(embedding_records)}, collection={collection}, provider={self._provider.name})"
            )

        except SemanticProcessingFailure as e:
            await self._handle_failure(job, knowledge_id, correlation_id, attempt, e.stage, e)
        except Exception as e:
            await self._handle_failure(job, knowledge_id, correlation_id, attempt, current_stage or "unknown", e)

    async def _handle_failure(
        self, job, knowledge_id: str, correlation_id: str, attempt: int, stage: str, exc: BaseException,
    ) -> None:
        root_exc = exc.__cause__ or exc
        non_retryable = stage == "validate"
        should_retry = self._retry_policy.should_retry(attempt, root_exc) and not non_retryable

        error_message = f"[{stage}] {exc}"
        logger.error(f"Embedding job {job.id} failed at {stage} (attempt {attempt}): {exc}")

        await self._events.publish(job.id, SemanticEvent(
            event_type=SemanticEventType.STAGE_FAILED,
            knowledge_id=knowledge_id, correlation_id=correlation_id,
            errors=[str(exc)], detail={"stage": stage},
        ))

        if should_retry:
            backoff = self._retry_policy.backoff_seconds(attempt)
            await self._repo.job_finished(job, "failed", error_message)
            next_job = await self._repo.create_job(knowledge_id, attempt=attempt + 1, correlation_id=correlation_id)
            await enqueue_embedding_job(knowledge_id, next_job.id, attempt + 1)
            await self._events.publish(job.id, SemanticEvent(
                event_type=SemanticEventType.STAGE_RETRYING,
                knowledge_id=knowledge_id, correlation_id=correlation_id,
                detail={"next_job_id": next_job.id, "next_attempt": attempt + 1, "backoff_seconds": backoff},
            ))
            return

        await self._repo.update_knowledge_embedding_status(knowledge_id, "failed")
        await self._repo.job_finished(job, "failed", error_message, dead_lettered=True)
        try:
            await self._dlq.send(knowledge_id, job.id, attempt, error_message)
        except Exception as dlq_err:
            logger.warning(f"Embedding dead-letter push failed for {knowledge_id} (non-fatal): {dlq_err}")
        await self._events.publish(job.id, SemanticEvent(
            event_type=SemanticEventType.DEAD_LETTERED,
            knowledge_id=knowledge_id, correlation_id=correlation_id,
            errors=[str(exc)], detail={"stage": stage},
        ))
