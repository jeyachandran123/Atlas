"""
Retrieval Engine (Objective 4). Consumes ONLY the Semantic Platform's public
interfaces: the embedding provider (to embed the query in the same vector
space as the chunks) and the vector store's search() — the seam Phase 3
deliberately left for this phase. Chunk text and provenance come back from
the vector store itself; the only Postgres reads are SemanticRepository's
read-only manifest accessors for lifecycle/version/health awareness. The
Knowledge Platform is never called directly.

Strategy-keyed so hybrid retrieval later is one new AbstractRetriever
subclass + one registry entry.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.document_platform.semantic.providers import get_embedding_provider
from app.document_platform.semantic.repository import SemanticRepository
from app.document_platform.semantic.vector_store import (
    collection_name_for,
    get_vector_store,
)
from app.document_platform.semantic.versioning import EMBEDDING_VERSION


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    knowledge_id: str
    document_id: str
    text: str
    score: float                     # raw semantic similarity from the store
    seq: int = 0
    section_path: str = ""
    node_type: str = "paragraph"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResult:
    chunks: list[RetrievedChunk]
    # knowledge_id → manifest facts the Ranking Engine's signals consume.
    manifest_facts: dict[str, dict[str, Any]]
    dropped_stale: int = 0           # hits filtered by lifecycle/version gates


class AbstractRetriever(ABC):
    name: str = "abstract"

    @abstractmethod
    async def retrieve(
        self, question: str, org_id: str, top_k: int,
        document_id: str | list[str] | None = None,
    ) -> RetrievalResult: ...


class SemanticRetriever(AbstractRetriever):
    name = "semantic"

    def __init__(self, semantic_repo: SemanticRepository) -> None:
        self._semantic = semantic_repo
        self._provider = get_embedding_provider()
        self._vector_store = get_vector_store()

    async def retrieve(
        self, question: str, org_id: str, top_k: int,
        document_id: str | list[str] | None = None,
    ) -> RetrievalResult:
        query_vec = (await self._provider.embed([question]))[0].vector
        # Phase 5.5 seam: a list scope maps to the vector store's $in filter.
        filters = {"document_id": document_id} if document_id else None
        hits = await self._vector_store.search(
            collection_name_for(org_id), query_vec, top_k=top_k, filters=filters,
        )

        # Lifecycle / version / health awareness: a hit is only trusted if
        # its knowledge object's semantic manifest is currently indexed at
        # the active embedding version. Superseded vectors are dropped here.
        manifest_facts: dict[str, dict[str, Any]] = {}
        chunks: list[RetrievedChunk] = []
        dropped = 0
        for hit in hits:
            knowledge_id = str(hit.metadata.get("knowledge_id", ""))
            if not knowledge_id:
                dropped += 1
                continue
            if knowledge_id not in manifest_facts:
                manifest = await self._semantic.get_semantic_manifest(knowledge_id)
                manifest_facts[knowledge_id] = {
                    "exists": manifest is not None,
                    "status": manifest.status if manifest else "missing",
                    "embedding_version": manifest.embedding_version if manifest else "",
                    "created_at": manifest.created_at if manifest else None,
                }
            facts = manifest_facts[knowledge_id]
            if not facts["exists"] or facts["status"] != "indexed" \
                    or facts["embedding_version"] != EMBEDDING_VERSION:
                dropped += 1
                continue
            chunks.append(RetrievedChunk(
                chunk_id=str(hit.metadata.get("chunk_id", hit.id)),
                knowledge_id=knowledge_id,
                document_id=str(hit.metadata.get("document_id", "")),
                text=hit.text,
                score=hit.score,
                seq=int(hit.metadata.get("seq", 0)),
                section_path=str(hit.metadata.get("section_path", "")),
                node_type=str(hit.metadata.get("node_type", "paragraph")),
                metadata=dict(hit.metadata),
            ))
        return RetrievalResult(chunks=chunks, manifest_facts=manifest_facts, dropped_stale=dropped)


class RetrievalEngine:
    """Strategy dispatcher — retrieval logic lives in retrievers, not here."""

    def __init__(self, semantic_repo: SemanticRepository) -> None:
        self._strategies: dict[str, AbstractRetriever] = {
            "semantic": SemanticRetriever(semantic_repo),
        }

    async def retrieve(
        self, strategy: str, question: str, org_id: str, top_k: int,
        document_id: str | list[str] | None = None,
    ) -> RetrievalResult:
        retriever = self._strategies.get(strategy)
        if retriever is None:
            raise ValueError(f"Unknown retrieval strategy: {strategy}")
        return await retriever.retrieve(question, org_id, top_k, document_id)
