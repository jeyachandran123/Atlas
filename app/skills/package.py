"""
Skill package extraction — a single SKILL.md or a .zip of a skill folder.

Safety rules (every one enforced before anything is stored):
  - package ≤ 2 MB (compressed AND uncompressed — zip bombs are rejected)
  - ≤ 50 files, text (UTF-8, no NUL bytes) only
  - no absolute paths, drive letters, '..' segments or symlinks
  - SKILL.md required at the root (a single top-level folder is unwrapped)
Nothing in a package is ever executed.
"""

from __future__ import annotations

import io
import posixpath
import stat
import zipfile
from dataclasses import dataclass, field

from app.skills.parser import MAX_SKILL_MD_BYTES, ParsedSkill, SkillValidationError, parse_skill_md

MAX_PACKAGE_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_FILES = 50
MAX_PATH_LEN = 255
SKILL_FILENAME = "SKILL.md"
_IGNORED_PREFIXES = ("__MACOSX/",)
_IGNORED_NAMES = {".DS_Store", "Thumbs.db"}


@dataclass
class SkillPackage:
    skill: ParsedSkill
    files: dict[str, str] = field(default_factory=dict)  # relative path → text (excl. SKILL.md)


def decode_text(data: bytes, path: str) -> str:
    if b"\x00" in data:
        raise SkillValidationError(f"'{path}' is not a text file")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise SkillValidationError(f"'{path}' is not UTF-8 text") from e


def safe_relative_path(raw: str) -> str:
    """Normalize a package path; reject anything that could escape the skill."""
    path = raw.replace("\\", "/")
    if not path or path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        raise SkillValidationError(f"Unsafe path in package: {raw!r}")
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise SkillValidationError(f"Unsafe path in package: {raw!r}")
    norm = posixpath.join(*parts)
    if len(norm) > MAX_PATH_LEN:
        raise SkillValidationError(f"Path too long in package: {raw[:60]!r}…")
    return norm


def build_package(skill_md: str, files: dict[str, str] | None = None) -> SkillPackage:
    """Validate an already-decoded SKILL.md + extra files (editor / installer path)."""
    files = files or {}
    if len(files) + 1 > MAX_PACKAGE_FILES:
        raise SkillValidationError(f"A skill may contain at most {MAX_PACKAGE_FILES} files")
    total = len(skill_md.encode("utf-8"))
    clean: dict[str, str] = {}
    for raw_path, content in files.items():
        path = safe_relative_path(raw_path)
        if path == SKILL_FILENAME:
            continue
        if "\x00" in content:
            raise SkillValidationError(f"'{path}' is not a text file")
        total += len(content.encode("utf-8"))
        clean[path] = content
    if total > MAX_PACKAGE_BYTES:
        raise SkillValidationError(
            f"Skill package must be at most {MAX_PACKAGE_BYTES // 1024 // 1024} MB"
        )
    return SkillPackage(skill=parse_skill_md(skill_md), files=clean)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def extract_zip(data: bytes) -> SkillPackage:
    if len(data) > MAX_PACKAGE_BYTES:
        raise SkillValidationError(
            f"Skill package must be at most {MAX_PACKAGE_BYTES // 1024 // 1024} MB"
        )
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise SkillValidationError("Not a valid .zip file") from e

    with zf:
        entries: list[tuple[str, zipfile.ZipInfo]] = []
        declared_total = 0
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if name.startswith(_IGNORED_PREFIXES) or posixpath.basename(name) in _IGNORED_NAMES:
                continue
            if _is_symlink(info):
                raise SkillValidationError(
                    f"Symlinks are not allowed in packages: {info.filename!r}"
                )
            path = safe_relative_path(name)
            declared_total += info.file_size
            if declared_total > MAX_PACKAGE_BYTES:
                raise SkillValidationError("Skill package is too large once uncompressed")
            entries.append((path, info))
        if len(entries) > MAX_PACKAGE_FILES:
            raise SkillValidationError(f"A skill may contain at most {MAX_PACKAGE_FILES} files")

        # Unwrap a single top-level folder ("review-agent/SKILL.md").
        tops = {p.split("/", 1)[0] for p, _ in entries}
        prefix = ""
        if (
            len(tops) == 1
            and all("/" in p for p, _ in entries)
            and not any(p == SKILL_FILENAME for p, _ in entries)
        ):
            prefix = tops.pop() + "/"

        skill_md: str | None = None
        files: dict[str, str] = {}
        read_total = 0
        for path, info in entries:
            rel = path[len(prefix) :] if prefix else path
            # Read with a hard cap — never trust the declared size alone.
            with zf.open(info) as fh:
                blob = fh.read(MAX_PACKAGE_BYTES + 1 - read_total)
            read_total += len(blob)
            if read_total > MAX_PACKAGE_BYTES:
                raise SkillValidationError("Skill package is too large once uncompressed")
            text = decode_text(blob, rel)
            if rel == SKILL_FILENAME:
                skill_md = text
            else:
                files[rel] = text

    if skill_md is None:
        raise SkillValidationError("Package has no SKILL.md at its root")
    if len(skill_md.encode("utf-8")) > MAX_SKILL_MD_BYTES:
        raise SkillValidationError(f"SKILL.md must be at most {MAX_SKILL_MD_BYTES // 1024} KB")
    return build_package(skill_md, files)


def extract_upload(filename: str, data: bytes) -> SkillPackage:
    """Dispatch on the upload: .zip → package, .md → single SKILL.md."""
    lower = (filename or "").lower()
    if lower.endswith(".zip") or data[:4] == b"PK\x03\x04":
        return extract_zip(data)
    if lower.endswith(".md") or not lower:
        if len(data) > MAX_SKILL_MD_BYTES:
            raise SkillValidationError(f"SKILL.md must be at most {MAX_SKILL_MD_BYTES // 1024} KB")
        return build_package(decode_text(data, filename or SKILL_FILENAME))
    raise SkillValidationError("Upload a .zip skill package or a single .md file")
