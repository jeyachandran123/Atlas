"""
DocumentProcessingPipeline — orchestrates the Phase 2 stages in order:

  load → detect → parse → ocr(if required) → normalize → metadata →
  structure → tables → images → language → clean → chunk → knowledge → persist

Each stage is an injected service with one responsibility; the pipeline only
sequences them, times them, and records an event per stage. Status flow:
  queued → processing → parsed → normalized → knowledge_ready | failed
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.document_platform.processing.chunker import ChunkingEngine
from app.document_platform.processing.cleaner import ContentCleaner
from app.document_platform.processing.detector import FileTypeDetector
from app.document_platform.processing.images import ImageExtractor
from app.document_platform.processing.knowledge import KnowledgeObjectBuilder
from app.document_platform.processing.language import LanguageDetector
from app.document_platform.processing.loader import DocumentLoader
from app.document_platform.processing.metadata import MetadataExtractor
from app.document_platform.processing.models import DocumentNode, NodeType
from app.document_platform.processing.normalizer import Normalizer
from app.document_platform.processing.ocr import OcrService
from app.document_platform.processing.parsers import get_parser_registry
from app.document_platform.processing.persistence import ProcessingRepository
from app.document_platform.processing.structure import StructuralAnalyzer
from app.document_platform.processing.tables import TableExtractor


class ProcessingFailure(Exception):
    def __init__(self, stage: str, message: str) -> None:
        self.stage = stage
        super().__init__(message)


class DocumentProcessingPipeline:
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
        chunker: ChunkingEngine | None = None,
        knowledge_builder: KnowledgeObjectBuilder | None = None,
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
        self._chunker = chunker or ChunkingEngine()
        self._builder = knowledge_builder or KnowledgeObjectBuilder()
        self._parsers = get_parser_registry()

    async def run(self, document_id: str, job_id: str) -> None:
        job = await self._repo.get_job(job_id)
        doc = await self._repo.get_document(document_id)
        if job is None or doc is None:
            logger.warning(f"Processing job {job_id}: document or job row missing — skipped")
            return

        await self._repo.job_started(job)
        await self._repo.set_processing_status(doc, "processing")
        current_stage = ""

        async def stage(name: str, fn, *args, detail_fn=None, **kwargs) -> Any:
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
                await self._repo.add_event(job.id, doc.id, name, "failed", ms, {"error": str(e)})
                raise ProcessingFailure(name, str(e)) from e
            ms = int((time.monotonic() - started) * 1000)
            detail = detail_fn(result) if detail_fn else None
            await self._repo.add_event(job.id, doc.id, name, "completed", ms, detail)
            return result

        try:
            # Idempotent reprocessing: clear previous derived output first
            await self._repo.wipe_derived(doc.id)

            content: bytes = await stage(
                "load", self._loader.load, doc.storage_key,
                detail_fn=lambda b: {"bytes": len(b)},
            )

            detected = await stage(
                "detect", self._detector.detect, doc.extension, content,
                detail_fn=lambda d: {"family": d.family, "confirmed": d.content_confirmed},
            )

            parser = self._parsers.get(detected.extension)
            if parser is None:
                raise ProcessingFailure("parse", f"No parser for {detected.extension}")

            parsed = await stage(
                "parse",
                lambda: asyncio.to_thread(parser.parse, content, doc.original_filename),
                detail_fn=lambda p: {
                    "parser": p.parser_name,
                    "tables": len(p.tables),
                    "images": len(p.images),
                    "needs_ocr": p.needs_ocr,
                },
            )

            # ── OCR — only when required, never inside parsers ────────────────
            ocr_pending = False
            if parsed.needs_ocr:
                ocr_texts: list[str] = []
                performed_any = False
                for img in parsed.images:
                    if not img.content:
                        continue
                    result = await self._ocr.run(img.content, img.format)
                    performed_any = performed_any or result.performed
                    if result.text:
                        ocr_texts.append(result.text)
                if ocr_texts:
                    for t in ocr_texts:
                        parsed.root.add(DocumentNode(
                            type=NodeType.PARAGRAPH, text=t, meta={"source": "ocr"},
                        ))
                ocr_pending = not performed_any
                await self._repo.add_event(
                    job.id, doc.id, "ocr",
                    "completed" if performed_any else "skipped",
                    None,
                    {"provider": self._ocr.provider_name, "texts": len(ocr_texts)},
                )
            else:
                await self._repo.add_event(
                    job.id, doc.id, "ocr", "skipped", None, {"reason": "not required"},
                )

            tree = await stage("normalize", self._normalizer.normalize, parsed)
            await self._repo.set_processing_status(doc, "parsed")

            metadata = await stage(
                "metadata", self._metadata.extract, parsed, tree,
                detail_fn=lambda m: {"words": m.word_count, "title": m.title[:60]},
            )

            tree, stats = await stage(
                "structure", self._structure.analyze, tree,
                detail_fn=lambda r: {
                    "sections": r[1].section_count, "depth": r[1].max_depth,
                },
            )

            tables = await stage(
                "tables", self._tables.extract, parsed, tree,
                detail_fn=lambda t: {"count": len(t)},
            )

            stored_images = await stage(
                "images", self._images.store, doc.uploaded_by, doc.id, parsed.images,
                detail_fn=lambda s: {"count": len(s)},
            )

            language = await stage(
                "language",
                self._language.detect,
                "\n".join(n.text for n in tree.walk() if n.text)[:8000],
                detail_fn=lambda lang: {"language": lang},
            )

            tree = await stage("clean", self._cleaner.clean_tree, tree)
            await self._repo.set_processing_status(doc, "normalized")

            chunks = await stage(
                "chunk", self._chunker.chunk, tree,
                detail_fn=lambda cs: {
                    "count": len(cs),
                    "tokens": sum(c.token_count for c in cs),
                },
            )

            built = await stage(
                "knowledge",
                self._builder.build,
                doc_type=doc.extension.lstrip("."),
                tree=tree,
                chunks=chunks,
                tables=tables,
                metadata=metadata,
                stats=stats,
                language=language,
                image_count=len(stored_images),
                ocr_pending=ocr_pending,
                detail_fn=lambda b: {"confidence": b.confidence},
            )

            ko = await stage(
                "persist",
                self._repo.persist_knowledge,
                doc.id, built, metadata, language, stored_images, chunks,
                detail_fn=lambda k: {"knowledge_object_id": k.id},
            )

            await self._repo.set_processing_status(doc, "knowledge_ready")
            await self._repo.job_finished(job, "knowledge_ready")
            logger.info(
                f"Document {doc.id} → knowledge_ready "
                f"(ko={ko.id}, chunks={len(chunks)}, tables={len(tables)}, lang={language})"
            )

        except ProcessingFailure as e:
            await self._repo.set_processing_status(doc, "failed")
            await self._repo.job_finished(job, "failed", f"[{e.stage}] {e}")
            logger.error(f"Document {doc.id} processing failed at {e.stage}: {e}")
        except Exception as e:
            await self._repo.add_event(job.id, doc.id, current_stage or "unknown", "failed", None, {"error": str(e)})
            await self._repo.set_processing_status(doc, "failed")
            await self._repo.job_finished(job, "failed", str(e))
            logger.exception(f"Document {doc.id} processing failed unexpectedly: {e}")
