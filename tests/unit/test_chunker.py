"""Unit tests for the AST-aware code chunker."""

from __future__ import annotations

import pytest

from app.indexing.chunker import GenericChunker, PythonChunker, get_chunker
from app.indexing.scanner import FileRecord
from app.shared.schemas import ChunkType


def _make_file_record(content: str, language: str = "python", path: str = "test.py") -> FileRecord:
    return FileRecord(
        path=f"/repo/{path}",
        relative_path=path,
        language=language,
        file_hash="abc123",
        size_bytes=len(content.encode()),
        is_new=True,
    )


PYTHON_CODE = '''"""Module docstring."""

import os
import sys
from typing import Optional


CONSTANT = 42


class MyService:
    """A service class."""

    def __init__(self, name: str) -> None:
        self.name = name

    def process(self, data: dict) -> Optional[str]:
        """Process some data."""
        if not data:
            return None
        return str(data)

    @staticmethod
    def validate(value: str) -> bool:
        return bool(value)


def standalone_function(x: int, y: int) -> int:
    """A standalone function."""
    return x + y
'''


def test_python_chunker_finds_class():
    chunker = PythonChunker()
    record = _make_file_record(PYTHON_CODE)
    chunks = chunker.chunk(record, PYTHON_CODE)

    class_chunks = [c for c in chunks if c.chunk_type == ChunkType.CLASS]
    assert len(class_chunks) >= 1
    assert any(c.class_name == "MyService" for c in class_chunks)


def test_python_chunker_finds_methods():
    chunker = PythonChunker()
    record = _make_file_record(PYTHON_CODE)
    chunks = chunker.chunk(record, PYTHON_CODE)

    method_chunks = [c for c in chunks if c.chunk_type == ChunkType.METHOD]
    method_names = [c.function_name for c in method_chunks]
    assert "__init__" in method_names
    assert "process" in method_names
    assert "validate" in method_names


def test_python_chunker_finds_standalone_function():
    chunker = PythonChunker()
    record = _make_file_record(PYTHON_CODE)
    chunks = chunker.chunk(record, PYTHON_CODE)

    func_chunks = [c for c in chunks if c.chunk_type == ChunkType.FUNCTION]
    assert any(c.function_name == "standalone_function" for c in func_chunks)


def test_python_chunker_includes_file_path():
    chunker = PythonChunker()
    record = _make_file_record(PYTHON_CODE, path="src/service.py")
    chunks = chunker.chunk(record, PYTHON_CODE)
    assert all(c.file_path == "src/service.py" for c in chunks)


def test_python_chunker_line_numbers():
    chunker = PythonChunker()
    record = _make_file_record(PYTHON_CODE)
    chunks = chunker.chunk(record, PYTHON_CODE)
    for chunk in chunks:
        assert chunk.start_line >= 1
        assert chunk.end_line >= chunk.start_line


def test_chunker_falls_back_for_unknown_language():
    chunker = get_chunker("unknown_lang")
    record = FileRecord(
        path="/repo/test.xyz",
        relative_path="test.xyz",
        language="unknown_lang",
        file_hash="abc",
        size_bytes=100,
        is_new=True,
    )
    content = "\n".join(f"line {i}" for i in range(200))
    chunks = chunker.chunk(record, content)
    assert len(chunks) > 0  # fallback produces chunks


def test_get_chunker_returns_python_chunker():
    chunker = get_chunker("python")
    assert isinstance(chunker, PythonChunker)


def test_get_chunker_returns_generic_for_js():
    chunker = get_chunker("javascript")
    assert isinstance(chunker, GenericChunker)


def test_chunker_skips_empty_content():
    chunker = PythonChunker()
    record = _make_file_record("   \n  \n  ")
    chunks = chunker.chunk(record, "   \n  \n  ")
    # Empty/whitespace-only content should produce no meaningful chunks
    assert all(len(c.content.strip()) >= 40 for c in chunks)


def test_chunker_splits_oversized_function():
    """Functions larger than MAX_CHUNK_CHARS should be split."""
    large_func = "def large_function():\n" + "\n".join(
        f"    x_{i} = {i}  # some computation" for i in range(1000)
    )
    chunker = PythonChunker()
    record = _make_file_record(large_func)
    chunks = chunker.chunk(record, large_func)

    for chunk in chunks:
        assert len(chunk.content) <= 8100  # MAX_CHUNK_CHARS * 1.01 tolerance


def test_javascript_chunker():
    js_code = """
function authenticate(user, password) {
    if (!user || !password) return false;
    return checkCredentials(user, password);
}

const validateToken = async (token) => {
    const payload = await decodeJWT(token);
    return payload.exp > Date.now();
};
"""
    chunker = GenericChunker("javascript")
    record = _make_file_record(js_code, language="javascript", path="auth.js")
    chunks = chunker.chunk(record, js_code)
    assert len(chunks) > 0
