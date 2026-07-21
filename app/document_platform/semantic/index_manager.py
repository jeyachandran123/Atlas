"""
Semantic Index management (Objective 9) — the index as a first-class entity,
independent of any single Knowledge Object. Creation, registration, and
statistics only; no query/retrieval logic (that's Phase 4).
"""
from __future__ import annotations

from app.db.models import SemanticIndex
from app.document_platform.semantic.repository import SemanticRepository


class SemanticIndexManager:
    def __init__(self, repo: SemanticRepository) -> None:
        self._repo = repo

    async def get_or_create(
        self,
        *,
        collection_name: str,
        embedding_version: str,
        vector_store_provider: str,
        dimension: int,
    ) -> SemanticIndex:
        existing = await self._repo.get_index(collection_name, embedding_version)
        if existing is not None:
            return existing
        index = SemanticIndex(
            index_name=collection_name,
            collection_name=collection_name,
            vector_store_provider=vector_store_provider,
            embedding_version=embedding_version,
            dimension=dimension,
            status="active",
            health_status="healthy",
        )
        return await self._repo.create_index(index)

    async def record_upsert(self, index: SemanticIndex, vector_store, collection_name: str) -> None:
        """Refresh vector_count from the vector store's own count() — the
        vector store is the source of truth for how many vectors actually
        exist; we never trust a locally-incremented counter."""
        count = await vector_store.count(collection_name)
        await self._repo.update_index_stats(index, vector_count=count, status="active")
