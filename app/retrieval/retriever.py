"""
Retrieval pipeline.

Query → Embed query → Semantic search in ChromaDB → MMR re-ranking → Results

WHY MMR (Maximal Marginal Relevance):
Without re-ranking, ChromaDB returns the 10 most similar chunks to the query.
For a question like "how does auth work?", this often returns 5 nearly-identical
login function variants. MMR maximises both relevance AND diversity:
the top result is most relevant, but subsequent results must also be
different from already-selected results.

Result: 8 diverse, relevant chunks instead of 8 redundant chunks.
"""

from __future__ import annotations

import math
from typing import Optional

from app.ollama_client import OllamaClient, get_ollama_client
from app.shared.schemas import SearchResult
from app.vector_store.base import VectorStore


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def mmr_rerank(
    query_embedding: list[float],
    results: list[SearchResult],
    top_k: int = 8,
    lambda_param: float = 0.7,
    use_embeddings: bool = True,
) -> list[SearchResult]:
    """
    Maximal Marginal Relevance re-ranking.

    Selects top_k results that balance:
    - Relevance to query (weight: lambda_param, default 0.7)
    - Diversity from already-selected results (weight: 1 - lambda_param)

    lambda_param = 1.0 → pure relevance (no diversity)
    lambda_param = 0.0 → pure diversity (ignore relevance)
    lambda_param = 0.7 → strongly favour relevance, add diversity
    
    Args:
        use_embeddings: If True, use cosine similarity on embeddings (accurate).
                       If False, fall back to Jaccard token overlap (fast).
    """
    if len(results) <= top_k:
        for i, r in enumerate(results):
            r.rank = i + 1
        return results

    selected: list[SearchResult] = []
    candidates = list(results)

    for _ in range(min(top_k, len(candidates))):
        if not candidates:
            break

        if not selected:
            # First selection: pick most relevant
            best = max(candidates, key=lambda r: r.score)
        else:
            # Subsequent selections: MMR score
            def mmr_score(candidate: SearchResult) -> float:
                relevance = candidate.score
                
                if use_embeddings and candidate.chunk.embedding:
                    # Use true cosine similarity on embeddings (V1.2+)
                    max_sim = max(
                        _cosine_similarity(candidate.chunk.embedding, s.chunk.embedding)
                        for s in selected
                        if s.chunk.embedding
                    )
                else:
                    # Fall back to Jaccard token overlap (V1.0 compatibility)
                    max_sim = max(
                        _text_overlap(candidate.chunk.content, s.chunk.content)
                        for s in selected
                    )
                
                return lambda_param * relevance - (1 - lambda_param) * max_sim

            best = max(candidates, key=mmr_score)

        selected.append(best)
        candidates.remove(best)

    for i, result in enumerate(selected):
        result.rank = i + 1

    return selected


def _text_overlap(a: str, b: str) -> float:
    """
    Simple token overlap similarity (Jaccard).
    
    V1.0: Used as primary similarity metric in MMR.
    V1.2+: Fallback when embeddings not available.
    
    Kept for backward compatibility and cases where embedding
    retrieval is disabled or chunks don't have stored embeddings.
    """
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


class CodeRetriever:
    """
    Retrieves relevant code chunks for a user query.

    Pipeline:
      1. Embed the query using Ollama
      2. Search ChromaDB for nearest neighbours
      3. MMR re-rank for diversity
      4. Apply metadata filters (language, chunk_type, file_path)
      5. Return top_k results
    """

    def __init__(
        self,
        vector_store: VectorStore,
        ollama_client: Optional[OllamaClient] = None,
    ) -> None:
        self._vs = vector_store
        self._ollama = ollama_client or get_ollama_client()

    async def retrieve(
        self,
        query: str,
        repo_id: str,
        top_k: int = 8,
        fetch_k: int = 20,
        language: Optional[str] = None,
        chunk_type: Optional[str] = None,
        file_path: Optional[str] = None,
        lambda_param: float = 0.7,
    ) -> list[SearchResult]:
        """
        Main retrieval method.

        Args:
            query: Natural language query from the user.
            repo_id: Repository to search in.
            top_k: Number of results to return after re-ranking.
            fetch_k: Number of candidates to fetch before re-ranking.
                     Must be > top_k; higher = better diversity but slower.
            language: Filter to a specific programming language.
            chunk_type: Filter to a specific chunk type (function, class, etc.).
            file_path: Filter to a specific file.
            lambda_param: MMR diversity parameter (0.7 = favour relevance).
        """
        # 1. Embed the query
        embeddings = await self._ollama.embed([query])
        if not embeddings:
            return []
        query_embedding = embeddings[0]

        # 2. Build filters
        filters: dict = {}
        if language:
            filters["language"] = language
        if chunk_type:
            filters["chunk_type"] = chunk_type
        if file_path:
            filters["file_path"] = file_path

        # 3. Fetch candidates from ChromaDB
        collection_name = VectorStore.code_collection(repo_id)
        candidates = await self._vs.search(
            collection_name=collection_name,
            query_embedding=query_embedding,
            top_k=fetch_k,
            filters=filters if filters else None,
        )

        if not candidates:
            return []

        # 4. MMR re-ranking with embedding-based similarity
        reranked = mmr_rerank(
            query_embedding=query_embedding,
            results=candidates,
            top_k=top_k,
            lambda_param=lambda_param,
            use_embeddings=True,  # V1.2: Use cosine similarity on embeddings
        )

        return reranked

    async def search_by_symbol(
        self,
        symbol_name: str,
        repo_id: str,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """
        Symbol-first search: find a specific function/class by name.
        Uses exact match in metadata before falling back to semantic search.
        """
        collection_name = VectorStore.code_collection(repo_id)

        # Try exact function name match first
        embeddings = await self._ollama.embed([f"function definition: {symbol_name}"])
        query_embedding = embeddings[0] if embeddings else []

        results = await self._vs.search(
            collection_name=collection_name,
            query_embedding=query_embedding,
            top_k=top_k * 2,
            filters={"function_name": symbol_name} if query_embedding else None,
        )

        # Boost exact name matches to top
        exact = [r for r in results if r.chunk.function_name == symbol_name
                 or r.chunk.class_name == symbol_name]
        others = [r for r in results if r not in exact]

        combined = exact + others
        for i, r in enumerate(combined[:top_k]):
            r.rank = i + 1
        return combined[:top_k]
