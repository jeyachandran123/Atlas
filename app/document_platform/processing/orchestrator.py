"""
ProcessingOrchestrator (Objective 1) — the single coordinator of the
document processing lifecycle.

Stages never call each other and never see one another; the orchestrator is
the only code that sequences them, owns the ProcessingContext, publishes
events, collects metrics, decides retries, and registers the resulting
Knowledge Object. This module is the new home of the coordination logic that
used to live in pipeline.py — behaviour for the "standard" profile is
unchanged; only the internal architecture around it changed.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.document_platform.identity import DocumentIdentityBuilder
from app.document_platform.knowledge.events import (
    KnowledgeEventPublisher,
    PersistingKnowledgeEventPublisher,
)
from app.document_platform.knowledge.lineage import LineageNodeType, LineageTracker
from app.document_platform.knowledge.manifest_service import KnowledgeManifestService
from app.document_platform.knowledge.repository import KnowledgeManifestRepository
from app.document_platform.processing.capabilities import ParserCapabilities
from app.document_platform.processing.chunker import ChunkingEngine
from app.document_platform.processing.cleaner import ContentCleaner
from app.document_platform.processing.context import ProcessingContext
from app.document_platform.processing.detector import FileTypeDetector
from app.document_platform.processing.events import (
    EventPublisher,
    PersistingEventPublisher,
    ProcessingEvent,
    ProcessingEventType,
)
from app.document_platform.processing.images import ImageExtractor
from app.document_platform.processing.knowledge import KnowledgeObjectBuilder
from app.document_platform.processing.knowledge_validation import (
    KnowledgeValidationError,
    KnowledgeValidator,
)
from app.document_platform.processing.language import LanguageDetector
from app.document_platform.processing.loader import DocumentLoader
from app.document_platform.processing.metadata import MetadataExtractor
from app.document_platform.processing.metrics import MetricsCollector
from app.document_platform.processing.models import DocumentNode, NodeType
from app.document_platform.processing.normalizer import Normalizer
from app.document_platform.processing.ocr import OcrService
from app.document_platform.processing.parsers import get_parser_registry
from app.document_platform.processing.persistence import ProcessingRepository
from app.document_platform.processing.profiles import get_profile
from app.document_platform.processing.queue import enqueue_processing_job
from app.document_platform.processing.registry import KnowledgeRegistry
from app.document_platform.processing.retry import DEFAULT_RETRY_POLICY, RetryPolicy, get_dead_letter_sink
from app.document_platform.processing.structure import StructuralAnalyzer
from app.document_platform.processing.tables import TableExtractor
from app.document_platform.processing.versioning import CHUNK_VERSION, PROCESSING_VERSION, SCHEMA_VERSION
from app.platform.capabilities import CapabilityCategory, get_capability_registry


class ProcessingFailure(Exception):
    def __init__(self, stage: str, message: str) -> None:
        self.stage = stage
        super().__init__(message)


class ProcessingOrchestrator:
    def __init__(
        self,
        db: AsyncSession,
        *,
        loader: DocumentLoader | None = None,
        detector: FileTypeDetector | None = None,
        ocr: OcrService | None = None,
        normalizer: Normalizer | None = None,
        metadata_extractor: MetadataExtractor | None = None,
        structural_analyzer: StructuralAnalyzer | None = None,
        table_extractor: TableExtractor | None = None,
        image_extractor: ImageExtractor | None = None,
        language_detector: LanguageDetector | None = None,
        cleaner: ContentCleaner | None = None,
        knowledge_builder: KnowledgeObjectBuilder | None = None,
        validator: KnowledgeValidator | None = None,
        retry_policy: RetryPolicy | None = None,
        event_publisher: EventPublisher | None = None,
        metrics_collector: MetricsCollector | None = None,
    ) -> None:
        self._repo = ProcessingRepository(db)
        self._loader = loader or DocumentLoader()
        self._detector = detector or FileTypeDetector()
        self._ocr = ocr or OcrService()
        self._normalizer = normalizer or Normalizer()
        self._metadata = metadata_extractor or MetadataExtractor()
        self._structure = structural_analyzer or StructuralAnalyzer()
        self._tables = table_extractor or TableExtractor()
        self._images = image_extractor or ImageExtractor()
        self._language = language_detector or LanguageDetector()
        self._cleaner = cleaner or ContentCleaner()
        self._builder = knowledge_builder or KnowledgeObjectBuilder()
        self._validator = validator or KnowledgeValidator()
        self._retry_policy = retry_policy or DEFAULT_RETRY_POLICY
        self._events: EventPublisher = event_publisher or PersistingEventPublisher(self._repo)
        self._metrics = metrics_collector or MetricsCollector()
        self._registry = KnowledgeRegistry(self._repo, self._events)
        self._dlq = get_dead_letter_sink()
        self._parsers = get_parser_registry()

        # Phase 2.6 — Knowledge Platform layer
        self._manifest_repo = KnowledgeManifestRepository(db)
        self._knowledge_events: KnowledgeEventPublisher = PersistingKnowledgeEventPublisher(self._manifest_repo)
        self._manifests = KnowledgeManifestService(self._manifest_repo, self._knowledge_events)
        self._lineage = LineageTracker(self._manifest_repo)
        self._identity = DocumentIdentityBuilder()
        self._capabilities = get_capability_registry()

    async def run(self, document_id: str, job_id: str) -> None:
        job = await self._repo.get_job(job_id)
        doc = await self._repo.get_document(document_id)
        if job is None or doc is None:
            logger.warning(f"Processing job {job_id}: document or job row missing — skipped")
            return

        profile = get_profile(job.profile)
        ctx = ProcessingContext(
            document_id=doc.id, job_id=job.id, profile_name=profile.name, attempt=job.attempt,
            # Objective 4 — the job's correlation_id is the platform-wide root
            # for this document (minted at upload, reused across retries).
            correlation_id=job.correlation_id,
        )
        chunker = ChunkingEngine(
            target_tokens=profile.chunk_target_tokens, max_tokens=profile.chunk_max_tokens,
        )

        await self._events.publish(job.id, ProcessingEvent(
            event_type=ProcessingEventType.PROCESSING_STARTED,
            document_id=doc.id, correlation_id=ctx.correlation_id,
            detail={"profile": profile.name, "attempt": ctx.attempt},
        ))
        await self._repo.job_started(job)
        await self._repo.set_processing_status(doc, "processing")
        current_stage = ""

        async def stage(name: str, fn, *args, detail_fn=None, **kwargs) -> Any:
            nonlocal current_stage
            current_stage = name
            started = time.monotonic()
            try:
                result = fn(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
            except Exception as e:
                ms = int((time.monotonic() - started) * 1000)
                ctx.record_timing(name, ms)
                await self._events.publish(job.id, ProcessingEvent(
                    event_type=ProcessingEventType.STAGE_FAILED,
                    document_id=doc.id, correlation_id=ctx.correlation_id,
                    stage=name, status="failed", duration_ms=ms, detail={"error": str(e)},
                ))
                raise ProcessingFailure(name, str(e)) from e
            ms = int((time.monotonic() - started) * 1000)
            ctx.record_timing(name, ms)
            detail = detail_fn(result) if detail_fn else None
            await self._events.publish(job.id, ProcessingEvent(
                event_type=ProcessingEventType.STAGE_COMPLETED,
                document_id=doc.id, correlation_id=ctx.correlation_id,
                stage=name, status="completed", duration_ms=ms, detail=detail or {},
            ))
            return result

        async def skip(name: str, reason: str) -> None:
            await self._events.publish(job.id, ProcessingEvent(
                event_type=ProcessingEventType.STAGE_SKIPPED,
                document_id=doc.id, correlation_id=ctx.correlation_id,
                stage=name, status="skipped", detail={"reason": reason},
            ))

        try:
            # Idempotent reprocessing: clear previous derived output first.
            # Manifests reference knowledge_objects via FK — they must be
            # deleted before the KnowledgeObject rows they point to, or the
            # delete below violates the foreign key constraint.
            await self._manifest_repo.delete_manifests_for_document(doc.id)
            await self._repo.wipe_derived(doc.id)

            content: bytes = await stage(
                "load", self._loader.load, doc.storage_key,
                detail_fn=lambda b: {"bytes": len(b)},
            )
            ctx.content = content

            detected = await stage(
                "detect", self._detector.detect, doc.extension, content,
                detail_fn=lambda d: {"family": d.family, "confirmed": d.content_confirmed},
            )
            ctx.detected_extension = detected.extension
            ctx.detected_family = detected.family

            parser = self._parsers.get(detected.extension)
            if parser is None:
                raise ProcessingFailure("parse", f"No parser for {detected.extension}")
            caps: ParserCapabilities = parser.capabilities

            parsed = await stage(
                "parse",
                lambda: asyncio.to_thread(parser.parse, content, doc.original_filename),
                detail_fn=lambda p: {
                    "parser": p.parser_name, "parser_version": parser.version,
                    "tables": len(p.tables), "images": len(p.images), "needs_ocr": p.needs_ocr,
                },
            )
            ctx.parsed = parsed

            # ── OCR — only when required and the parser can ever trigger it ────
            if parsed.needs_ocr and caps.supports_ocr_trigger and profile.enable_ocr:
                await self._events.publish(job.id, ProcessingEvent(
                    event_type=ProcessingEventType.OCR_STARTED,
                    document_id=doc.id, correlation_id=ctx.correlation_id, stage="ocr",
                ))
                ocr_texts: list[str] = []
                performed_any = False
                for img in parsed.images:
                    if not img.content:
                        continue
                    result = await self._ocr.run(img.content, img.format)
                    performed_any = performed_any or result.performed
                    if result.text:
                        ocr_texts.append(result.text)
                for t in ocr_texts:
                    parsed.root.add(DocumentNode(type=NodeType.PARAGRAPH, text=t, meta={"source": "ocr"}))
                ctx.ocr_pending = not performed_any
                await self._events.publish(job.id, ProcessingEvent(
                    event_type=ProcessingEventType.OCR_COMPLETED,
                    document_id=doc.id, correlation_id=ctx.correlation_id, stage="ocr",
                    status="completed" if performed_any else "skipped",
                    detail={"provider": self._ocr.provider_name, "texts": len(ocr_texts)},
                ))
            else:
                await skip("ocr", "not required" if not parsed.needs_ocr else "unsupported by parser or profile")

            tree = await stage("normalize", self._normalizer.normalize, parsed)
            ctx.tree = tree
            await self._events.publish(job.id, ProcessingEvent(
                event_type=ProcessingEventType.NORMALIZATION_COMPLETED,
                document_id=doc.id, correlation_id=ctx.correlation_id, stage="normalize",
            ))
            await self._repo.set_processing_status(doc, "parsed")

            metadata = await stage(
                "metadata", self._metadata.extract, parsed, tree,
                detail_fn=lambda m: {"words": m.word_count, "title": m.title[:60]},
            )
            ctx.metadata = metadata

            # Structure always runs — it computes stats (section/table/image
            # counts) the Knowledge Object needs regardless of whether this
            # format has heading-based hierarchy to build.
            tree, stats = await stage(
                "structure", self._structure.analyze, tree,
                detail_fn=lambda r: {"sections": r[1].section_count, "depth": r[1].max_depth},
            )
            ctx.tree = tree

            if caps.supports_tables and profile.enable_tables:
                tables = await stage(
                    "tables", self._tables.extract, parsed, tree,
                    detail_fn=lambda t: {"count": len(t)},
                )
            else:
                await skip("tables", "unsupported by parser or disabled by profile")
                tables = []
            ctx.tables = tables

            if (caps.supports_images or caps.supports_embedded_images) and profile.enable_images:
                stored_images = await stage(
                    "images", self._images.store, doc.uploaded_by, doc.id, parsed.images,
                    detail_fn=lambda s: {"count": len(s)},
                )
            else:
                await skip("images", "unsupported by parser or disabled by profile")
                stored_images = []
            ctx.image_count = len(stored_images)

            if caps.supports_language_detection:
                language = await stage(
                    "language", self._language.detect,
                    "\n".join(n.text for n in tree.walk() if n.text)[:8000],
                    detail_fn=lambda lang: {"language": lang},
                )
            else:
                await skip("language", "unsupported by parser")
                language = "unknown"
            ctx.language = language

            tree = await stage("clean", self._cleaner.clean_tree, tree)
            ctx.tree = tree
            await self._repo.set_processing_status(doc, "normalized")

            chunks = await stage(
                "chunk", chunker.chunk, tree,
                detail_fn=lambda cs: {"count": len(cs), "tokens": sum(c.token_count for c in cs)},
            )
            ctx.chunks = chunks
            await self._events.publish(job.id, ProcessingEvent(
                event_type=ProcessingEventType.CHUNKING_COMPLETED,
                document_id=doc.id, correlation_id=ctx.correlation_id, stage="chunk",
                detail={"count": len(chunks)},
            ))

            built = await stage(
                "knowledge", self._builder.build,
                doc_type=doc.extension.lstrip("."), tree=tree, chunks=chunks, tables=tables,
                metadata=metadata, stats=stats, language=language,
                image_count=ctx.image_count, ocr_pending=ctx.ocr_pending,
                detail_fn=lambda b: {"confidence": b.confidence},
            )
            ctx.knowledge = built
            await self._events.publish(job.id, ProcessingEvent(
                event_type=ProcessingEventType.KNOWLEDGE_BUILT,
                document_id=doc.id, correlation_id=ctx.correlation_id, stage="knowledge",
                detail={"confidence": built.confidence},
            ))

            # ── Knowledge Validation (Objective 9) — reject before persist ────
            try:
                self._validator.validate(built, chunks)
            except KnowledgeValidationError as e:
                raise ProcessingFailure("validate", "; ".join(e.reasons)) from e
            await self._events.publish(job.id, ProcessingEvent(
                event_type=ProcessingEventType.KNOWLEDGE_VALIDATED,
                document_id=doc.id, correlation_id=ctx.correlation_id, stage="validate",
            ))

            # ── Register (not just store) the Knowledge Object ────────────────
            entry = await stage(
                "persist", self._registry.register,
                document_id=doc.id, built=built, metadata=metadata, language=language,
                stored_images=stored_images, chunks=chunks,
                parser_version=parser.version, chunk_version=CHUNK_VERSION,
                processing_version=PROCESSING_VERSION, schema_version=SCHEMA_VERSION,
                job_id=job.id, correlation_id=ctx.correlation_id,
                detail_fn=lambda e: {"knowledge_id": e.knowledge_id},
            )

            # ── Knowledge Platform layer (Phase 2.6): manifest + lineage ──────
            content_identity = self._identity.content_identity(
                tree, language, metadata.custom,
            )
            capabilities_snapshot = {
                "parser": f"{parser.name}@{parser.version}",
                "chunker": f"structure_aware_chunker@{CHUNK_VERSION}",
            }
            await stage(
                "manifest",
                self._register_manifest_and_lineage,
                entry.knowledge_id, doc.id, parser, ctx, content_identity, capabilities_snapshot,
                detail_fn=lambda m: {"lifecycle": m.lifecycle_state},
            )

            await self._repo.set_processing_status(doc, "knowledge_ready")
            await self._repo.job_finished(job, "knowledge_ready")

            metrics = self._metrics.collect(ctx, parser.name, parser.version)
            await self._events.publish(job.id, ProcessingEvent(
                event_type=ProcessingEventType.PROCESSING_COMPLETED,
                document_id=doc.id, correlation_id=ctx.correlation_id,
                duration_ms=ctx.total_duration_ms, detail=metrics.to_dict(),
            ))
            logger.info(
                f"Document {doc.id} → knowledge_ready "
                f"(ko={entry.knowledge_id}, chunks={len(chunks)}, tables={len(tables)}, lang={language})"
            )

        except ProcessingFailure as e:
            await self._handle_failure(ctx, job, doc, e.stage, e)
        except Exception as e:
            await self._handle_failure(ctx, job, doc, current_stage or "unknown", e)

    async def _register_manifest_and_lineage(
        self, knowledge_id: str, document_id: str, parser, ctx: ProcessingContext,
        content_identity, capabilities_snapshot: dict[str, str],
    ):
        manifest = await self._manifests.register(
            document_id=document_id,
            knowledge_object_id=knowledge_id,
            parser_name=parser.name,
            parser_version=parser.version,
            chunk_version=CHUNK_VERSION,
            processing_version=PROCESSING_VERSION,
            schema_version=SCHEMA_VERSION,
            correlation_id=ctx.correlation_id,
            content_identity=content_identity,
            capabilities_snapshot=capabilities_snapshot,
            warnings=ctx.warnings,
            retry_count=ctx.attempt - 1,
        )
        # Lineage (Objective 8): Document → KnowledgeObject is recorded here
        # because the generic graph is what future non-relational node types
        # (embedding, retrieval, generation) will attach to. Chunk-level
        # provenance already exists via DocumentChunk.knowledge_object_id —
        # duplicating it as lineage edges here would just be redundant rows.
        await self._lineage.record(
            LineageNodeType.KNOWLEDGE_OBJECT, knowledge_id,
            LineageNodeType.DOCUMENT, document_id, ctx.correlation_id,
        )
        return manifest

    async def _handle_failure(self, ctx: ProcessingContext, job, doc, stage: str, exc: BaseException) -> None:
        root_exc = exc.__cause__ or exc
        # A validated-but-broken Knowledge Object is a deterministic failure —
        # retrying the same input produces the same broken output.
        non_retryable_stage = stage == "validate"
        retryable = self._retry_policy.is_retryable(root_exc) and not non_retryable_stage
        should_retry = self._retry_policy.should_retry(ctx.attempt, root_exc) and not non_retryable_stage

        error_message = f"[{stage}] {exc}"
        logger.error(f"Document {doc.id} processing failed at {stage} (attempt {ctx.attempt}): {exc}")

        if should_retry:
            backoff = self._retry_policy.backoff_seconds(ctx.attempt)
            await self._repo.job_finished(job, "failed", error_message)
            await self._repo.set_processing_status(doc, "queued")
            next_job = await self._repo.create_job(
                doc.id, attempt=ctx.attempt + 1, profile=ctx.profile_name,
                correlation_id=ctx.correlation_id,
            )
            await enqueue_processing_job(doc.id, next_job.id, ctx.attempt + 1)
            await self._events.publish(job.id, ProcessingEvent(
                event_type=ProcessingEventType.STAGE_RETRYING,
                document_id=doc.id, correlation_id=ctx.correlation_id, stage=stage,
                status="retrying",
                detail={"next_job_id": next_job.id, "next_attempt": ctx.attempt + 1, "backoff_seconds": backoff},
            ))
            return

        await self._repo.set_processing_status(doc, "failed")
        await self._repo.job_finished(job, "failed", error_message, dead_lettered=True)
        try:
            await self._dlq.send(doc.id, job.id, ctx.attempt, error_message)
        except Exception as dlq_err:
            logger.warning(f"Dead-letter push failed for {doc.id} (non-fatal): {dlq_err}")
        await self._events.publish(job.id, ProcessingEvent(
            event_type=ProcessingEventType.DEAD_LETTERED,
            document_id=doc.id, correlation_id=ctx.correlation_id, stage=stage,
            status="failed", detail={"reason": "retries exhausted" if retryable else "non-retryable"},
        ))
        await self._events.publish(job.id, ProcessingEvent(
            event_type=ProcessingEventType.PROCESSING_FAILED,
            document_id=doc.id, correlation_id=ctx.correlation_id, stage=stage,
            status="failed", duration_ms=ctx.total_duration_ms, detail={"error": str(exc)},
        ))
