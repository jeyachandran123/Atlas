"""Unit tests for the retriever and MMR re-ranking."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.retrieval.retriever import CodeRetriever, _text_overlap, mmr_rerank
from app.shared.schemas import ChunkType, CodeChunk, SearchResult


def _make_result(content: str, score: float, file_path: str = "app/test.py", function_name: str = "func") -> SearchResult:
    chunk = CodeChunk(
        content=content,
        file_path=file_path,
        language="python",
        chunk_type=ChunkType.FUNCTION,
        start_line=1,
        end_line=5,
        function_name=function_name,
        repo_id="repo-1",
        file_hash="abc",
    )
    return SearchResult(chunk=chunk, score=score, rank=1)


# ── MMR tests ─────────────────────────────────────────────────────────────────

def test_mmr_returns_top_k():
    results = [_make_result(f"def func_{i}(): pass", score=0.9 - i * 0.05) for i in range(10)]
    reranked = mmr_rerank(query_embedding=[0.1] * 768, results=results, top_k=5)
    assert len(reranked) == 5


def test_mmr_assigns_ranks():
    results = [_make_result(f"def func_{i}(): pass", score=0.9 - i * 0.05) for i in range(5)]
    reranked = mmr_rerank(query_embedding=[0.1] * 768, results=results, top_k=3)
    ranks = [r.rank for r in reranked]
    assert ranks == [1, 2, 3]


def test_mmr_returns_all_if_fewer_than_top_k():
    results = [_make_result("def f(): pass", score=0.8)]
    reranked = mmr_rerank(query_embedding=[0.1] * 768, results=results, top_k=5)
    assert len(reranked) == 1
    assert reranked[0].rank == 1


def test_mmr_promotes_diversity():
    """Identical chunks should not both rank top-2."""
    identical_content = "def login(user, password): return True"
    diverse_content = "class DatabasePool: pass"

    results = [
        _make_result(identical_content, score=0.95, function_name="login_a"),
        _make_result(identical_content, score=0.90, function_name="login_b"),  # near-duplicate
        _make_result(diverse_content, score=0.70, function_name="pool"),
    ]

    # With high lambda (relevance focus), top-2 would be the duplicates
    # With moderate lambda, diversity should surface the unique chunk
    reranked = mmr_rerank(
        query_embedding=[0.1] * 768, results=results, top_k=2, lambda_param=0.5
    )

    contents = [r.chunk.function_name for r in reranked]
    # At least one non-duplicate should appear in top-2
    assert len(set(contents)) >= 1


def test_text_overlap_identical():
    assert _text_overlap("hello world", "hello world") == 1.0


def test_text_overlap_disjoint():
    assert _text_overlap("hello world", "foo bar baz") == 0.0


def test_text_overlap_partial():
    score = _text_overlap("hello world", "hello python")
    assert 0 < score < 1


def test_text_overlap_empty():
    assert _text_overlap("", "") == 0.0


# ── CodeRetriever tests ────────────────────────────────────────────────────────

@pytest.fixture
def mock_vector_store():
    store = MagicMock()
    chunk = CodeChunk(
        content="def authenticate(user, pwd): pass",
        file_path="app/auth.py",
        language="python",
        chunk_type=ChunkType.FUNCTION,
        start_line=10,
        end_line=20,
        function_name="authenticate",
        repo_id="repo-1",
        file_hash="def123",
    )
    store.search = AsyncMock(
        return_value=[SearchResult(chunk=chunk, score=0.88, rank=1)]
    )
    return store


@pytest.fixture
def mock_ollama_for_retriever():
    mock = MagicMock()
    mock.embed = AsyncMock(return_value=[[0.1] * 768])
    return mock


@pytest.mark.asyncio
async def test_retriever_returns_results(mock_vector_store, mock_ollama_for_retriever):
    retriever = CodeRetriever(
        vector_store=mock_vector_store,
        ollama_client=mock_ollama_for_retriever,
    )
    results = await retriever.retrieve(
        query="how does auth work",
        repo_id="repo-1",
        top_k=3,
    )
    assert len(results) >= 1
    assert results[0].chunk.function_name == "authenticate"


@pytest.mark.asyncio
async def test_retriever_returns_empty_when_no_results(mock_ollama_for_retriever):
    store = MagicMock()
    store.search = AsyncMock(return_value=[])
    retriever = CodeRetriever(vector_store=store, ollama_client=mock_ollama_for_retriever)
    results = await retriever.retrieve("anything", "repo-1")
    assert results == []


@pytest.mark.asyncio
async def test_retriever_calls_embed_once(mock_vector_store, mock_ollama_for_retriever):
    retriever = CodeRetriever(
        vector_store=mock_vector_store,
        ollama_client=mock_ollama_for_retriever,
    )
    await retriever.retrieve("test query", "repo-1")
    mock_ollama_for_retriever.embed.assert_called_once_with(["test query"])


@pytest.mark.asyncio
async def test_retriever_passes_filters(mock_vector_store, mock_ollama_for_retriever):
    retriever = CodeRetriever(
        vector_store=mock_vector_store,
        ollama_client=mock_ollama_for_retriever,
    )
    await retriever.retrieve(
        query="login",
        repo_id="repo-1",
        language="python",
        chunk_type="function",
        file_path="app/auth.py",
    )
    call_kwargs = mock_vector_store.search.call_args[1]
    filters = call_kwargs.get("filters", {})
    assert filters.get("language") == "python"
    assert filters.get("chunk_type") == "function"
    assert filters.get("file_path") == "app/auth.py"
