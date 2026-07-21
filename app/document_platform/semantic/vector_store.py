"""
Vector Store abstraction (Objective 7).

Deliberately NOT reusing app/vector_store/ — that module is hard-coupled to
repo-indexing's CodeChunk/SearchResult dataclasses. This one is generic
(ids/texts/embeddings/metadata dicts) so it works for Knowledge Objects
today and any future embedding consumer without redesign. Qdrant/Milvus/
PGVector/Pinecone/Weaviate each become one new class here.

`search()` is part of the contract (a vector store isn't a real interface
without one) but Phase 3 never calls it — no retrieval exists yet.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class VectorRecord:
    id: str
    text: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorSearchHit:
    id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStoreError(Exception):
    """The vector store operation failed."""


class AbstractVectorStore(ABC):
    name: str = "abstract"

    @abstractmethod
    async def upsert(self, collection: str, records: list[VectorRecord]) -> int:
        """Insert or update vectors. Returns the number written."""

    @abstractmethod
    async def delete(self, collection: str, ids: list[str]) -> int:
        """Delete vectors by id. Returns the number removed."""

    @abstractmethod
    async def collection_exists(self, collection: str) -> bool: ...

    @abstractmethod
    async def count(self, collection: str) -> int: ...

    @abstractmethod
    async def search(
        self, collection: str, query_embedding: list[float],
        top_k: int = 10, filters: Optional[dict] = None,
    ) -> list[VectorSearchHit]:
        """Defined for interface completeness (Objective 7). Not called in Phase 3 —
        no retrieval exists yet; that's Phase 4."""


class ChromaVectorStoreProvider(AbstractVectorStore):
    """
    First implementation, using the SAME ChromaDB server as repo-indexing
    (same host/port config) but its own collections — one per organization
    (`dip_{org_id}`), mirroring the proven per-repo isolation pattern.
    """

    name = "chroma"

    def __init__(self, client=None) -> None:
        self._client = client  # lazy — set on first use via _get_client()

    async def _get_client(self):
        if self._client is None:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
            from app.config import get_settings
            cfg = get_settings()
            self._client = await chromadb.AsyncHttpClient(
                host=cfg.chroma_host,
                port=cfg.chroma_port,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        return self._client

    async def upsert(self, collection: str, records: list[VectorRecord]) -> int:
        if not records:
            return 0
        try:
            client = await self._get_client()
            coll = await client.get_or_create_collection(
                name=collection, metadata={"hnsw:space": "cosine"},
            )
            await coll.upsert(
                ids=[r.id for r in records],
                documents=[r.text for r in records],
                embeddings=[r.embedding for r in records],
                metadatas=[r.metadata for r in records],
            )
            return len(records)
        except Exception as e:
            raise VectorStoreError(f"Chroma upsert failed for '{collection}': {e}") from e

    async def delete(self, collection: str, ids: list[str]) -> int:
        if not ids:
            return 0
        try:
            client = await self._get_client()
            coll = await client.get_collection(name=collection)
            await coll.delete(ids=ids)
            return len(ids)
        except Exception:
            return 0  # collection or ids already gone — deletion is idempotent

    async def collection_exists(self, collection: str) -> bool:
        try:
            client = await self._get_client()
            await client.get_collection(name=collection)
            return True
        except Exception:
            return False

    async def count(self, collection: str) -> int:
        try:
            client = await self._get_client()
            coll = await client.get_collection(name=collection)
            return await coll.count()
        except Exception:
            return 0

    async def search(
        self, collection: str, query_embedding: list[float],
        top_k: int = 10, filters: Optional[dict] = None,
    ) -> list[VectorSearchHit]:
        # Implemented in Phase 4 — this was the deliberately-stubbed seam the
        # Phase 3 contract defined for the Retrieval Engine to fill in.
        try:
            client = await self._get_client()
            coll = await client.get_collection(name=collection)
            where = None
            if filters:
                clauses = [{k: {"$eq": v}} for k, v in filters.items()]
                where = clauses[0] if len(clauses) == 1 else {"$and": clauses}
            res = await coll.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            ids = (res.get("ids") or [[]])[0]
            docs = (res.get("documents") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            dists = (res.get("distances") or [[]])[0]
            hits = []
            for i, hit_id in enumerate(ids):
                # Collections are created with hnsw:space=cosine, so
                # distance = 1 - cosine_similarity; invert for a score.
                score = 1.0 - float(dists[i]) if i < len(dists) else 0.0
                hits.append(VectorSearchHit(
                    id=hit_id,
                    text=docs[i] if i < len(docs) else "",
                    score=score,
                    metadata=dict(metas[i]) if i < len(metas) and metas[i] else {},
                ))
            return hits
        except Exception as e:
            raise VectorStoreError(f"Chroma search failed for '{collection}': {e}") from e


def get_vector_store(provider_name: str | None = None) -> AbstractVectorStore:
    from app.config import get_settings
    cfg = get_settings()
    name = provider_name or cfg.dip_vector_store_provider
    if name == "chroma":
        return ChromaVectorStoreProvider()
    raise ValueError(f"Unknown vector store provider: {name}")


def collection_name_for(org_id: str) -> str:
    return f"dip_{org_id}"
