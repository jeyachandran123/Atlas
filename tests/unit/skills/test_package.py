"""Skill package (.zip / .md) safety."""

from __future__ import annotations

import io
import stat
import zipfile

import pytest

from app.skills.package import (
    MAX_PACKAGE_BYTES,
    MAX_PACKAGE_FILES,
    extract_upload,
    extract_zip,
    safe_relative_path,
)
from app.skills.parser import SkillValidationError

SKILL_MD = "---\nname: zipped\ndescription: A zipped skill.\n---\n# Zipped\nDo it.\n"


def _zip(entries: dict[str, bytes | str], symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


def test_zip_at_root() -> None:
    pkg = extract_zip(_zip({"SKILL.md": SKILL_MD, "references/guide.md": "# Guide"}))
    assert pkg.skill.name == "zipped"
    assert pkg.files == {"references/guide.md": "# Guide"}


def test_zip_single_top_folder_is_unwrapped() -> None:
    pkg = extract_zip(
        _zip({"zipped/SKILL.md": SKILL_MD, "zipped/references/a.md": "A", "__MACOSX/x": "junk"})
    )
    assert pkg.files == {"references/a.md": "A"}


@pytest.mark.parametrize("bad", ["../evil.md", "a/../../evil.md", "/abs/evil.md", "C:/win.md"])
def test_path_traversal_rejected(bad: str) -> None:
    with pytest.raises(SkillValidationError, match="Unsafe path"):
        extract_zip(_zip({"SKILL.md": SKILL_MD, bad: "x"}))


def test_backslash_traversal_rejected() -> None:
    with pytest.raises(SkillValidationError, match="Unsafe path"):
        safe_relative_path("..\\..\\evil")


def test_symlink_rejected() -> None:
    with pytest.raises(SkillValidationError, match="Symlinks"):
        extract_zip(_zip({"SKILL.md": SKILL_MD}, symlink="link.md"))


def test_binary_file_rejected() -> None:
    with pytest.raises(SkillValidationError, match="not a text file"):
        extract_zip(_zip({"SKILL.md": SKILL_MD, "assets/logo.png": b"\x89PNG\x00\x00"}))


def test_too_many_files_rejected() -> None:
    entries: dict[str, bytes | str] = {"SKILL.md": SKILL_MD}
    entries.update({f"references/{i}.md": "x" for i in range(MAX_PACKAGE_FILES)})
    with pytest.raises(SkillValidationError, match="at most 50 files"):
        extract_zip(_zip(entries))


def test_zip_bomb_rejected_by_uncompressed_size() -> None:
    # ~3 MB of zeros compresses to a few KB — must be rejected before reading it all
    data = _zip({"SKILL.md": SKILL_MD, "references/big.md": "0" * (MAX_PACKAGE_BYTES + 1024)})
    assert len(data) < MAX_PACKAGE_BYTES
    with pytest.raises(SkillValidationError, match="too large"):
        extract_zip(data)


def test_compressed_size_limit() -> None:
    with pytest.raises(SkillValidationError, match="2 MB"):
        extract_zip(b"PK\x03\x04" + b"\x00" * MAX_PACKAGE_BYTES)


def test_missing_skill_md() -> None:
    with pytest.raises(SkillValidationError, match="no SKILL.md"):
        extract_zip(_zip({"README.md": "hi"}))


def test_not_a_zip() -> None:
    with pytest.raises(SkillValidationError, match="valid .zip"):
        extract_upload("x.zip", b"definitely not a zip")


def test_single_markdown_upload() -> None:
    pkg = extract_upload("SKILL.md", SKILL_MD.encode())
    assert pkg.skill.name == "zipped" and pkg.files == {}


def test_other_extensions_rejected() -> None:
    with pytest.raises(SkillValidationError, match=".zip skill package or a single .md"):
        extract_upload("skill.exe", b"MZ...")
