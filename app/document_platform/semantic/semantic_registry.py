"""
Semantic Registry (Objective 8) — owns the semantic representation of a
Knowledge Object as a whole (which vector store, which collection, how many
embeddings, what strategy). Knowledge Registry (Phase 2) owns content;
this owns semantics. Knowledge never references vectors directly — only
this registry and the Embedding Registry know the vector store exists.
"""
from __future__ import annotations

from typing import Optional

from app.db.models import SemanticManifest
from app.document_platform.semantic.repository import SemanticRepository

_STATUS_FIELDS = {"status"}


class SemanticRegistry:
    def __init__(self, repo: SemanticRepository) -> None:
        self._repo = repo

    async def register(
        self,
        *,
        knowledge_id: str,
        vector_store_provider: str,
        collection_name: str,
        index_name: str,
        embedding_version: str,
        provider_name: str,
        model_name: str,
        dimension: int,
        embedding_count: int,
        correlation_id: str,
        status: str = "indexed",
    ) -> SemanticManifest:
        manifest = SemanticManifest(
            knowledge_id=knowledge_id,
            vector_store_provider=vector_store_provider,
            collection_name=collection_name,
            index_name=index_name,
            embedding_version=embedding_version,
            provider_name=provider_name,
            model_name=model_name,
            dimension=dimension,
            embedding_count=embedding_count,
            status=status,
            correlation_id=correlation_id,
        )
        await self._repo.create_semantic_manifest(manifest)
        return manifest

    async def get(self, knowledge_id: str) -> Optional[SemanticManifest]:
        return await self._repo.get_semantic_manifest(knowledge_id)
