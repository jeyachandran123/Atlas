"""Unit tests for the repository scanner."""

from __future__ import annotations

import os
import tempfile

import pytest

from app.indexing.scanner import RepositoryScanner, _compute_sha256, _is_binary


@pytest.fixture
def sample_repo(tmp_path):
    """Create a sample repository structure for testing."""
    # Python files
    (tmp_path / "main.py").write_text("def main():\n    pass\n")
    (tmp_path / "utils.py").write_text("def helper():\n    return 42\n")

    # Sub-package
    pkg = tmp_path / "mypackage"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "service.py").write_text("class Service:\n    pass\n")

    # Files that should be skipped
    (tmp_path / "binary_file.bin").write_bytes(b"\x00\x01\x02hello")
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "main.cpython-312.pyc").write_bytes(b"\x00bytecode")

    # .gitignore
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")

    # Ignored by gitignore
    (tmp_path / "debug.log").write_text("log data")
    build = tmp_path / "build"
    build.mkdir()
    (build / "output.py").write_text("# generated")

    # Markdown (should be indexed)
    (tmp_path / "README.md").write_text("# My Project\n")

    return tmp_path


def test_scanner_finds_python_files(sample_repo):
    scanner = RepositoryScanner(str(sample_repo))
    records = scanner.scan()
    paths = [r.relative_path for r in records]
    assert "main.py" in paths
    assert "utils.py" in paths
    assert "mypackage/service.py" in paths or "mypackage\\service.py" in paths


def test_scanner_skips_pycache(sample_repo):
    scanner = RepositoryScanner(str(sample_repo))
    records = scanner.scan()
    paths = [r.relative_path for r in records]
    assert not any("__pycache__" in p for p in paths)


def test_scanner_skips_binary_files(sample_repo):
    scanner = RepositoryScanner(str(sample_repo))
    records = scanner.scan()
    paths = [r.relative_path for r in records]
    assert "binary_file.bin" not in paths


def test_scanner_includes_markdown(sample_repo):
    scanner = RepositoryScanner(str(sample_repo))
    records = scanner.scan()
    paths = [r.relative_path for r in records]
    assert "README.md" in paths


def test_scanner_computes_sha256(sample_repo):
    scanner = RepositoryScanner(str(sample_repo))
    records = scanner.scan()
    main_record = next(r for r in records if r.relative_path == "main.py")
    assert len(main_record.file_hash) == 64  # SHA256 hex = 64 chars
    assert main_record.file_hash.isalnum()


def test_scanner_detects_new_files(sample_repo):
    """Files not in existing_hashes should be marked is_new=True."""
    scanner = RepositoryScanner(str(sample_repo), existing_hashes={})
    records = scanner.scan()
    assert all(r.is_new for r in records)


def test_scanner_skips_unchanged_files(sample_repo):
    """Files with matching hashes should have is_new=False."""
    # First scan
    scanner1 = RepositoryScanner(str(sample_repo))
    records1 = scanner1.scan()
    hashes = {r.relative_path: r.file_hash for r in records1}

    # Second scan with same hashes
    scanner2 = RepositoryScanner(str(sample_repo), existing_hashes=hashes)
    records2 = scanner2.scan()
    assert all(not r.is_new for r in records2)


def test_scanner_detects_changed_file(sample_repo):
    """Modified files should be marked is_new=True even if path exists in hashes."""
    first = RepositoryScanner(str(sample_repo))
    records = first.scan()
    hashes = {r.relative_path: r.file_hash for r in records}

    # Modify a file
    (sample_repo / "main.py").write_text("def main():\n    return 'changed'\n")

    second = RepositoryScanner(str(sample_repo), existing_hashes=hashes)
    records2 = second.scan()
    changed = next((r for r in records2 if r.relative_path == "main.py"), None)
    assert changed is not None
    assert changed.is_new is True


def test_scanner_scan_changed_only(sample_repo):
    """scan_changed_only() returns subset where is_new=True."""
    scanner = RepositoryScanner(str(sample_repo))
    all_records = scanner.scan()
    changed = scanner.scan_changed_only()
    assert len(changed) <= len(all_records)
    assert all(r.is_new for r in changed)


def test_is_binary_detects_null_bytes():
    null_byte_content = b"hello" + b"\x00" + b"world"
    assert _is_binary(null_byte_content) is True
    assert _is_binary(b"hello world\n") is False


def test_sha256_is_deterministic(tmp_path):
    f = tmp_path / "test.py"
    f.write_text("hello world")
    h1 = _compute_sha256(str(f))
    h2 = _compute_sha256(str(f))
    assert h1 == h2
    assert len(h1) == 64
