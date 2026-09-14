"""
A crash *before* the orchestrator starts must terminate the job, not strand it.

The failure this guards against is not hypothetical: a broken container bind
mount made a function-local import inside ``_wipe_stale_embeddings`` raise
ModuleNotFoundError on every run. That happens before
``ProcessingOrchestrator.run()`` — so the orchestrator's own failure path
(``job_finished(..., dead_lettered=True)`` + DLQ) never executed, and the job
row stayed in exactly the state ``recover_orphaned_jobs`` looks for: status
``queued``, ``dead_lettered`` false, ``error`` NULL.

The recovery sweep therefore re-enqueued it every 60s forever, re-publishing
the SAME attempt number, so ``MAX_RECOVERY_ATTEMPTS`` never tripped. The user
saw "Processing…" indefinitely, with the reason visible only in a container log.

These tests build their own in-memory database rather than using the shared
async fixtures — the worker swaps in its own session factory, so the fewer
moving parts around that swap, the clearer the failure signal.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.db.models import Document, DocumentProcessingJob, Organization, User
from app.workers import document_worker


@asynccontextmanager
async def stranded_job(monkeypatch):
    """Yield (session, document, job) in the state the upload path leaves behind."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        org = Organization(name="Test Org", slug="test-org", plan="free")
        session.add(org)
        await session.flush()

        user = User(
            org_id=org.id,
            email="dev@test.com",
            hashed_password="x",
            full_name="Test Developer",
            role="developer",
        )
        session.add(user)
        await session.flush()

        doc = Document(
            org_id=org.id,
            uploaded_by=user.id,
            original_filename="UAT-EMOS-Dish Template.xlsx",
            stored_filename="stored.xlsx",
            extension="xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=1234,
            checksum_sha256="a" * 64,
            storage_provider="local",
            storage_key="documents/stored.xlsx",
            upload_status="completed",
            processing_status="queued",
        )
        session.add(doc)
        await session.flush()

        job = DocumentProcessingJob(document_id=doc.id, status="queued", attempt=1)
        session.add(job)
        await session.commit()

        # The worker opens its own sessions; point them all at this one.
        @asynccontextmanager
        async def _fake_session():
            yield session

        monkeypatch.setattr(document_worker, "get_db_session", _fake_session)

        yield session, doc, job

    await engine.dispose()


async def test_precondition_crash_marks_job_failed_instead_of_stranding_it(monkeypatch):
    async with stranded_job(monkeypatch) as (session, doc, job):

        async def _explode(session, document_id):
            raise ModuleNotFoundError(
                "No module named 'app.document_platform.semantic.repository'"
            )

        monkeypatch.setattr(document_worker, "_wipe_stale_embeddings", _explode)

        await document_worker.process_job(
            {"document_id": doc.id, "job_id": job.id, "attempt": 1}
        )

        await session.refresh(job)
        await session.refresh(doc)

        # Terminal, not retriable-forever.
        assert job.status == "failed"
        assert job.dead_lettered is True
        assert job.finished_at is not None
        # The operator must see WHY without reading container logs.
        assert job.error and "semantic.repository" in job.error
        # And the UI must stop showing "Processing…".
        assert doc.processing_status == "failed"


async def test_stranded_job_is_no_longer_a_recovery_candidate(monkeypatch):
    """The exact query recover_orphaned_jobs uses must no longer match."""
    async with stranded_job(monkeypatch) as (session, doc, job):

        async def _explode(session, document_id):
            raise RuntimeError("boom")

        monkeypatch.setattr(document_worker, "_wipe_stale_embeddings", _explode)

        await document_worker.process_job(
            {"document_id": doc.id, "job_id": job.id, "attempt": 1}
        )

        rows = (
            await session.execute(
                select(Document.id)
                .join(
                    DocumentProcessingJob,
                    DocumentProcessingJob.document_id == Document.id,
                )
                .where(
                    Document.processing_status == "queued",
                    DocumentProcessingJob.status == "queued",
                    DocumentProcessingJob.dead_lettered.is_(False),
                    Document.id == doc.id,
                )
            )
        ).all()

        assert rows == [], "job still matches the recovery sweep — infinite re-enqueue loop"


async def test_successful_precondition_still_runs_the_orchestrator(monkeypatch):
    """The crash handler must not swallow the happy path."""
    async with stranded_job(monkeypatch) as (session, doc, job):
        ran = {}

        async def _noop(session, document_id):
            ran["wiped"] = True

        class _FakeOrchestrator:
            def __init__(self, *a, **kw):
                pass

            async def run(self, document_id, job_id):
                ran["orchestrated"] = (document_id, job_id)

        monkeypatch.setattr(document_worker, "_wipe_stale_embeddings", _noop)
        monkeypatch.setattr(document_worker, "ProcessingOrchestrator", _FakeOrchestrator)

        await document_worker.process_job(
            {"document_id": doc.id, "job_id": job.id, "attempt": 1}
        )

        assert ran.get("wiped") is True
        assert ran.get("orchestrated") == (doc.id, job.id)
        # Untouched by the crash handler.
        await session.refresh(job)
        assert job.status == "queued"
