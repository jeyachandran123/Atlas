"""
Repository indexer — the main indexing pipeline.

Orchestrates: Scanner → Chunker → Embedder → VectorStore + MSSQL

Design decisions:
- Incremental by default: only re-indexes changed files (SHA256 comparison)
- Distributed lock: prevents two workers from indexing the same repo
- Progress streaming: updates Redis so clients can poll status
- Atomic file updates: ChromaDB delete + insert happens per file
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config import get_settings
from app.db.repositories import IndexJobRepository, IndexedFileRepository, RepositoryRepo
from app.indexing.chunker import get_chunker
from app.indexing.embedder import ChunkEmbedder
from app.indexing.scanner import FileRecord, RepositoryScanner
from app.redis_client import (
    acquire_lock,
    release_lock,
    set_index_progress,
)
from app.shared.exceptions import IndexingInProgressError
from app.shared.schemas import CodeChunk
from app.vector_store.base import VectorStore

cfg = get_settings()


class IndexingPipeline:
    """
    Full repository indexing pipeline.

    Flow:
      1. Acquire distributed lock (prevents duplicate jobs)
      2. Scan files (SHA256 comparison for incremental)
      3. For each changed file: chunk → embed → store in ChromaDB + MSSQL
      4. Update job progress in Redis (for real-time client polling)
      5. Mark repo as ready in MSSQL
      6. Release lock

    Designed to run in a background worker (IndexWorker).
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedder: ChunkEmbedder,
        job_repo: IndexJobRepository,
        file_repo: IndexedFileRepository,
        repo_repo: RepositoryRepo,
    ) -> None:
        self._vs = vector_store
        self._embedder = embedder
        self._job_repo = job_repo
        self._file_repo = file_repo
        self._repo_repo = repo_repo

    async def run(
        self,
        job_id: str,
        repo_id: str,
        repo_path: str,
        job_type: str = "full",
    ) -> None:
        """
        Execute the indexing pipeline for a repository.
        Call this from a background worker.
        """
        lock_key = f"lock:index:{repo_id}"
        lock_value = job_id

        # Acquire distributed lock
        acquired = await acquire_lock(lock_key, lock_value, ttl_seconds=3600)
        if not acquired:
            await self._job_repo.fail(job_id, "Another indexing job is already running")
            raise IndexingInProgressError()

        try:
            await self._execute(job_id, repo_id, repo_path, job_type)
        except Exception as e:
            await self._job_repo.fail(job_id, str(e))
            await self._repo_repo.update_status(repo_id, "error")
            raise
        finally:
            await release_lock(lock_key, lock_value)

    async def _execute(
        self,
        job_id: str,
        repo_id: str,
        repo_path: str,
        job_type: str,
    ) -> None:
        # Mark job as running
        await self._job_repo.update_progress(job_id, 0, 0, status="running")
        await self._repo_repo.update_status(repo_id, "indexing")

        await set_index_progress(
            job_id,
            {"status": "scanning", "total": 0, "processed": 0, "chunks": 0},
        )

        # Load existing hashes for incremental indexing
        existing_hashes: dict[str, str] = {}
        if job_type == "incremental":
            existing_hashes = await self._load_existing_hashes(repo_id)

        # Scan the repository
        scanner = RepositoryScanner(repo_path, existing_hashes=existing_hashes)
        all_files = scanner.scan()

        files_to_index = [f for f in all_files if f.is_new]
        total = len(files_to_index)

        # ── Deleted file cleanup (incremental only) ───────────────────────
        if job_type == "incremental" and existing_hashes:
            current_paths = {f.relative_path for f in all_files}
            deleted_paths = set(existing_hashes.keys()) - current_paths
            collection_name_early = VectorStore.code_collection(repo_id)
            for deleted_path in deleted_paths:
                await self._vs.delete_by_file(collection_name_early, deleted_path)
                await self._file_repo.delete(repo_id, deleted_path)

        await self._job_repo.update_progress(job_id, 0, 0, files_total=total)
        await set_index_progress(
            job_id,
            {"status": "indexing", "total": total, "processed": 0, "chunks": 0},
        )

        collection_name = VectorStore.code_collection(repo_id)
        total_chunks = 0
        processed = 0

        # Process files in parallel batches
        batch_size = cfg.index_parallel_workers
        for i in range(0, len(files_to_index), batch_size):
            batch = files_to_index[i : i + batch_size]
            batch_chunks = await asyncio.gather(
                *[self._process_file(f, repo_id, collection_name) for f in batch],
                return_exceptions=True,
            )

            for j, result in enumerate(batch_chunks):
                file_record = batch[j]
                if isinstance(result, Exception):
                    # Log and continue — one bad file shouldn't fail the job
                    continue

                chunk_count = result
                total_chunks += chunk_count
                processed += 1

                # Update file record in MSSQL
                await self._file_repo.upsert(
                    repo_id=repo_id,
                    file_path=file_record.relative_path,
                    language=file_record.language,
                    file_hash=file_record.file_hash,
                    size_bytes=file_record.size_bytes,
                    chunk_count=chunk_count,
                )

            # Update progress in Redis
            await set_index_progress(
                job_id,
                {
                    "status": "indexing",
                    "total": total,
                    "processed": processed,
                    "chunks": total_chunks,
                    "current_file": batch[-1].relative_path if batch else "",
                },
            )
            await self._job_repo.update_progress(job_id, processed, total_chunks)

        # Mark complete
        now = datetime.now(timezone.utc)
        await self._job_repo.update_progress(
            job_id, processed, total_chunks, status="completed"
        )
        await self._repo_repo.update_status(
            repo_id,
            "ready",
            last_indexed_at=now,
            file_count=len(all_files),
            chunk_count=total_chunks,
        )
        await set_index_progress(
            job_id,
            {
                "status": "completed",
                "total": total,
                "processed": processed,
                "chunks": total_chunks,
            },
        )

    async def _process_file(
        self,
        file_record: FileRecord,
        repo_id: str,
        collection_name: str,
    ) -> int:
        """
        Process one file: read → chunk → embed → store.
        Returns number of chunks created.
        """
        # Read file content
        with open(file_record.path, encoding="utf-8", errors="replace") as f:
            content = f.read()

        if not content.strip():
            return 0

        # AST-aware chunking
        chunker = get_chunker(file_record.language)
        chunks = chunker.chunk(file_record, content)

        if not chunks:
            return 0

        # Set repo_id on all chunks
        for chunk in chunks:
            chunk.repo_id = repo_id

        # Delete stale chunks for this file (incremental: file content changed)
        await self._vs.delete_by_file(collection_name, file_record.relative_path)

        # Embed chunks
        embedded = await self._embedder.embed_chunks(chunks)

        if not embedded:
            return 0

        # Store in ChromaDB
        chunk_list = [c for c, _ in embedded]
        embedding_list = [e for _, e in embedded]
        await self._vs.upsert_chunks(collection_name, chunk_list, embedding_list)

        return len(embedded)

    async def _load_existing_hashes(self, repo_id: str) -> dict[str, str]:
        """Load existing file hashes from MSSQL for incremental comparison."""
        from sqlalchemy import select
        from app.db.models import IndexedFile

        # This requires a DB session — in a worker context, create one
        from app.database import get_db_session
        async with get_db_session() as session:
            result = await session.execute(
                select(IndexedFile.file_path, IndexedFile.file_hash).where(
                    IndexedFile.repo_id == repo_id
                )
            )
            return {row.file_path: row.file_hash for row in result}
