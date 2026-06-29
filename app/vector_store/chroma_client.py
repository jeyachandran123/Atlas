"""
ChromaDB vector store implementation.

Uses ChromaDB HTTP client (client-server mode) for production,
or an in-memory client for tests.

Collection strategy: one collection per repository.
This gives hard isolation — a bug in repo A's indexing cannot
corrupt repo B's vectors.
"""

from __future__ import annotations

import json
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.shared.schemas import ChunkType, CodeChunk, SearchResult
from app.vector_store.base import VectorStore

cfg = get_settings()


def _chunk_to_metadata(chunk: CodeChunk) -> dict:
    """Convert a CodeChunk to ChromaDB metadata (flat dict, string values)."""
    return {
        "file_path": chunk.file_path,
        "language": chunk.language,
        "chunk_type": chunk.chunk_type.value,
        "start_line": str(chunk.start_line),
        "end_line": str(chunk.end_line),
        "function_name": chunk.function_name or "",
        "class_name": chunk.class_name or "",
        "repo_id": chunk.repo_id,
        "file_hash": chunk.file_hash,
    }


def _metadata_to_chunk(content: str, metadata: dict, repo_id: str) -> CodeChunk:
    """Reconstruct a CodeChunk from ChromaDB metadata."""
    return CodeChunk(
        content=content,
        file_path=metadata["file_path"],
        language=metadata["language"],
        chunk_type=ChunkType(metadata["chunk_type"]),
        start_line=int(metadata["start_line"]),
        end_line=int(metadata["end_line"]),
        function_name=metadata.get("function_name") or None,
        class_name=metadata.get("class_name") or None,
        repo_id=metadata.get("repo_id", repo_id),
        file_hash=metadata.get("file_hash", ""),
    )


class ChromaVectorStore(VectorStore):
    """
    ChromaDB implementation of VectorStore.

    In production: uses HTTP client pointing at ChromaDB server.
    In tests: uses EphemeralClient (in-memory, zero setup).
    """

    def __init__(self, client: chromadb.AsyncClientAPI) -> None:
        self._client = client

    async def upsert_chunks(
        self,
        collection_name: str,
        chunks: list[CodeChunk],
        embeddings: list[list[float]],
    ) -> int:
        if not chunks:
            return 0

        collection = await self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        # Stable IDs: repo_id + file_path + start_line
        ids = [
            f"{c.repo_id}::{c.file_path}::{c.start_line}::{c.chunk_type.value}"
            for c in chunks
        ]
        documents = [c.content for c in chunks]
        metadatas = [_chunk_to_metadata(c) for c in chunks]

        await collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        return len(chunks)

    async def search(
        self,
        collection_name: str,
        query_embedding: list[float],
        top_k: int = 10,
        filters: Optional[dict] = None,
    ) -> list[SearchResult]:
        try:
            collection = await self._client.get_collection(name=collection_name)
        except Exception:
            return []  # Collection doesn't exist = repo not indexed

        where = self._build_where(filters) if filters else None

        results = await collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, await collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        search_results = []
        if not results["documents"] or not results["documents"][0]:
            return []

        for i, (doc, meta, distance) in enumerate(
            zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
                strict=False,
            )
        ):
            # ChromaDB cosine distance: 0=identical, 2=opposite
            # Convert to similarity score: 1 - (distance / 2)
            score = max(0.0, 1.0 - (distance / 2.0))
            chunk = _metadata_to_chunk(doc, meta, "")
            search_results.append(SearchResult(chunk=chunk, score=score, rank=i + 1))

        return search_results

    async def delete_by_file(self, collection_name: str, file_path: str) -> int:
        try:
            collection = await self._client.get_collection(name=collection_name)
        except Exception:
            return 0

        # Get all IDs for this file
        existing = await collection.get(
            where={"file_path": file_path},
            include=[],
        )
        ids = existing.get("ids", [])
        if ids:
            await collection.delete(ids=ids)
        return len(ids)

    async def delete_collection(self, collection_name: str) -> None:
        try:
            await self._client.delete_collection(name=collection_name)
        except Exception:
            pass  # Already gone

    async def collection_exists(self, collection_name: str) -> bool:
        try:
            await self._client.get_collection(name=collection_name)
            return True
        except Exception:
            return False

    async def count(self, collection_name: str) -> int:
        try:
            collection = await self._client.get_collection(name=collection_name)
            return await collection.count()
        except Exception:
            return 0

    @staticmethod
    def _build_where(filters: dict) -> dict:
        """
        Convert filter dict to ChromaDB where clause.
        Supports: language, chunk_type, file_path (prefix), class_name.
        """
        conditions = []

        if lang := filters.get("language"):
            conditions.append({"language": {"$eq": lang}})
        if ct := filters.get("chunk_type"):
            conditions.append({"chunk_type": {"$eq": ct}})
        if fp := filters.get("file_path"):
            conditions.append({"file_path": {"$eq": fp}})
        if cn := filters.get("class_name"):
            conditions.append({"class_name": {"$eq": cn}})

        if not conditions:
            return {}
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}


# ── Factory functions ─────────────────────────────────────────────────────────

_store: ChromaVectorStore | None = None


async def get_chroma_store() -> ChromaVectorStore:
    """Return the production ChromaDB store (HTTP client)."""
    global _store
    if _store is None:
        client = await chromadb.AsyncHttpClient(
            host=cfg.chroma_host,
            port=cfg.chroma_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        _store = ChromaVectorStore(client)
    return _store


async def get_test_store() -> ChromaVectorStore:
    """Return an in-memory ChromaDB store for tests."""
    client = chromadb.AsyncEphemeralClient(
        settings=ChromaSettings(anonymized_telemetry=False)
    )
    return ChromaVectorStore(client)
