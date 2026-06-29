"""
Abstract vector store interface.

All vector operations go through this interface.
ChromaDB implements it in V1. Qdrant will implement it in V2.
Swapping backends requires zero changes to indexing or retrieval code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.shared.schemas import CodeChunk, SearchResult


class VectorStore(ABC):
    """
    Abstract base for all vector store backends.

    Collections map to repositories: code_{repo_id}, docs_{repo_id}.
    Every operation is scoped to a collection (= one repository).
    Access control is enforced BEFORE reaching this layer.
    """

    @abstractmethod
    async def upsert_chunks(
        self,
        collection_name: str,
        chunks: list[CodeChunk],
        embeddings: list[list[float]],
    ) -> int:
        """Insert or update chunks with their embeddings. Returns count upserted."""
        ...

    @abstractmethod
    async def search(
        self,
        collection_name: str,
        query_embedding: list[float],
        top_k: int = 10,
        filters: Optional[dict] = None,
    ) -> list[SearchResult]:
        """Semantic search. Returns ranked results."""
        ...

    @abstractmethod
    async def delete_by_file(self, collection_name: str, file_path: str) -> int:
        """Delete all chunks from a specific file. Used on incremental re-index."""
        ...

    @abstractmethod
    async def delete_collection(self, collection_name: str) -> None:
        """Delete an entire collection. Used when a repository is removed."""
        ...

    @abstractmethod
    async def collection_exists(self, collection_name: str) -> bool:
        """Check if a collection exists."""
        ...

    @abstractmethod
    async def count(self, collection_name: str) -> int:
        """Return number of chunks in a collection."""
        ...

    @staticmethod
    def code_collection(repo_id: str) -> str:
        """Naming convention for code chunk collections."""
        return f"code_{repo_id.replace('-', '_')}"

    @staticmethod
    def docs_collection(repo_id: str) -> str:
        """Naming convention for documentation collections."""
        return f"docs_{repo_id.replace('-', '_')}"

    @staticmethod
    def memory_collection(user_id: str) -> str:
        """Naming convention for long-term memory collections."""
        return f"memory_{user_id.replace('-', '_')}"
