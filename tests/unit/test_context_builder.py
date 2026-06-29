"""Unit tests for the context builder."""

from __future__ import annotations

import pytest

from app.retrieval.context_builder import ContextBuilder, _compress_chunk, _estimate_tokens
from app.shared.schemas import ChunkType, CodeChunk, SearchResult


def _make_result(
    content: str,
    score: float = 0.9,
    file_path: str = "app/service.py",
    function_name: str | None = "my_func",
    start_line: int = 1,
    end_line: int | None = None,
) -> SearchResult:
    chunk = CodeChunk(
        content=content,
        file_path=file_path,
        language="python",
        chunk_type=ChunkType.FUNCTION,
        start_line=start_line,
        end_line=end_line or start_line + content.count("\n"),
        function_name=function_name,
        repo_id="repo-1",
        file_hash="abc123",
    )
    return SearchResult(chunk=chunk, score=score, rank=1)


def test_empty_results_returns_empty_window():
    builder = ContextBuilder()
    window = builder.build([])
    assert window.total_tokens == 0
    assert window.chunks == []
    assert window.budget_used == 0.0


def test_builds_context_from_results():
    results = [
        _make_result("def foo():\n    return 42\n", score=0.9, start_line=1, end_line=3),
        _make_result("def bar():\n    return 'hello'\n", score=0.8, function_name="bar", start_line=10, end_line=12),
    ]
    builder = ContextBuilder()
    window = builder.build(results)
    assert len(window.chunks) == 2
    assert window.total_tokens > 0


def test_deduplication():
    """Chunks with same file + start line should appear only once."""
    result = _make_result("def foo(): pass", start_line=10)
    builder = ContextBuilder()
    window = builder.build([result, result, result])
    assert len(window.chunks) == 1


def test_focus_file_prioritized():
    """Chunks from the focus file should appear first."""
    results = [
        _make_result("def other():\n    pass", score=0.95, file_path="other.py"),
        _make_result("def focused():\n    pass", score=0.7, file_path="focus.py"),
    ]
    builder = ContextBuilder()
    window = builder.build(results, focus_file="focus.py")

    assert len(window.chunks) >= 1
    # Focus file should be ranked first
    assert window.chunks[0].chunk.file_path == "focus.py"


def test_token_budget_respected():
    """Context should not exceed the available token budget."""
    # Very small budget
    builder = ContextBuilder(model_context_window=1000, reserved_tokens=900)
    # Available: 100 tokens

    large_content = "x = 1\n" * 200  # ~300 tokens
    results = [_make_result(large_content, score=0.9)]
    window = builder.build(results)

    assert window.total_tokens <= 110  # small tolerance


def test_low_relevance_filtered():
    """Chunks below MIN_RELEVANCE_SCORE should be excluded."""
    results = [
        _make_result("def good(): pass", score=0.8),
        _make_result("def bad(): pass", score=0.1),  # below threshold
    ]
    builder = ContextBuilder()
    window = builder.build(results)

    scores = [r.score for r in window.chunks]
    assert 0.1 not in scores


def test_format_for_prompt_includes_file_paths():
    results = [_make_result("def hello(): pass", file_path="src/greeting.py")]
    builder = ContextBuilder()
    window = builder.build(results)
    formatted = builder.format_context_block(window)
    assert "src/greeting.py" in formatted


def test_format_for_prompt_includes_code_fences():
    results = [_make_result("def hello(): pass")]
    builder = ContextBuilder()
    window = builder.build(results)
    formatted = builder.format_context_block(window)
    assert "```python" in formatted
    assert "```" in formatted


def test_format_empty_context():
    builder = ContextBuilder()
    window = builder.build([])
    formatted = builder.format_context_block(window)
    assert "No relevant code context" in formatted


def test_estimate_tokens():
    assert _estimate_tokens("") == 1
    assert _estimate_tokens("a" * 100) == 25  # 100/4


def test_compress_chunk():
    chunk = CodeChunk(
        content="x" * 1000,
        file_path="app/big.py",
        language="python",
        chunk_type=ChunkType.FUNCTION,
        start_line=50,
        end_line=150,
        function_name="big_function",
        repo_id="r1",
        file_hash="h1",
    )
    compressed = _compress_chunk(chunk)
    assert len(compressed) < 200  # much smaller than original
    assert "big.py" in compressed
    assert "big_function" in compressed
