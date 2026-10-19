"""
SKILL.md parsing and validation.

A SKILL.md is YAML frontmatter between `---` fences followed by markdown
instructions. Only `name` and `description` are required. Unknown keys are
kept (so a round-trip never loses author data) but never interpreted.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

import yaml  # type: ignore[import-untyped]

MAX_SKILL_MD_BYTES = 50 * 1024
MAX_NAME_LEN = 64
MAX_DESCRIPTION_LEN = 1024
MAX_DISPLAY_NAME_LEN = 120
MAX_TRIGGERS = 30
MAX_TRIGGER_LEN = 64
VALID_MODES = frozenset({"auto", "code", "business"})

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ICON_RE = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.DOTALL)
_KNOWN_KEYS = ("name", "display_name", "description", "icon", "version", "triggers", "modes")


class SkillValidationError(ValueError):
    """The SKILL.md (or package) is invalid. The message is safe to show users."""


@dataclass(frozen=True)
class ParsedSkill:
    name: str
    display_name: str
    description: str
    icon: str
    version: str
    triggers: list[str]
    modes: list[str]
    instructions: str  # markdown after the frontmatter
    raw: str  # the full SKILL.md text
    extra: dict[str, Any] = field(default_factory=dict)


def is_valid_slug(value: str) -> bool:
    return bool(value) and len(value) <= MAX_NAME_LEN and bool(_SLUG_RE.match(value))


def _str_list(value: Any, key: str, max_items: int, max_len: int) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",")]
    if not isinstance(value, list):
        raise SkillValidationError(f"'{key}' must be a list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str | int | float):
            raise SkillValidationError(f"'{key}' must be a list of strings")
        text = str(item).strip()
        if not text:
            continue
        if len(text) > max_len:
            raise SkillValidationError(f"'{key}' entries must be at most {max_len} characters")
        if text not in out:
            out.append(text)
    if len(out) > max_items:
        raise SkillValidationError(f"'{key}' may have at most {max_items} entries")
    return out


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter dict, markdown body). Raises on malformed YAML."""
    text = text.lstrip("﻿")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise SkillValidationError("SKILL.md must start with YAML frontmatter between '---' lines")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as e:
        raise SkillValidationError(f"Invalid YAML frontmatter: {e}") from e
    if not isinstance(meta, dict):
        raise SkillValidationError("Frontmatter must be a YAML mapping")
    return meta, match.group(2)


def parse_skill_md(text: str) -> ParsedSkill:
    if len(text.encode("utf-8")) > MAX_SKILL_MD_BYTES:
        raise SkillValidationError(f"SKILL.md must be at most {MAX_SKILL_MD_BYTES // 1024} KB")
    meta, body = split_frontmatter(text)

    name = str(meta.get("name") or "").strip()
    if not name:
        raise SkillValidationError("Frontmatter field 'name' is required")
    if not is_valid_slug(name):
        raise SkillValidationError(
            f"'name' must be kebab-case (a-z, 0-9, '-') and at most {MAX_NAME_LEN} characters"
        )

    description = str(meta.get("description") or "").strip()
    if not description:
        raise SkillValidationError("Frontmatter field 'description' is required")
    if len(description) > MAX_DESCRIPTION_LEN:
        raise SkillValidationError(
            f"'description' must be at most {MAX_DESCRIPTION_LEN} characters"
        )

    display_name = str(meta.get("display_name") or "").strip() or name.replace("-", " ").title()
    if len(display_name) > MAX_DISPLAY_NAME_LEN:
        raise SkillValidationError(
            f"'display_name' must be at most {MAX_DISPLAY_NAME_LEN} characters"
        )

    icon = str(meta.get("icon") or "sparkles").strip()
    if not _ICON_RE.match(icon):
        raise SkillValidationError("'icon' must be a short icon name (letters, digits, '-', '_')")

    version = str(meta.get("version") or "1.0.0").strip()[:32]
    triggers = _str_list(meta.get("triggers"), "triggers", MAX_TRIGGERS, MAX_TRIGGER_LEN)
    modes = [m.lower() for m in _str_list(meta.get("modes"), "modes", 3, 16)]
    bad_modes = [m for m in modes if m not in VALID_MODES]
    if bad_modes:
        raise SkillValidationError(f"Unknown mode(s) {bad_modes}; allowed: {sorted(VALID_MODES)}")

    instructions = body.strip()
    if not instructions:
        raise SkillValidationError("SKILL.md has no instructions after the frontmatter")

    return ParsedSkill(
        name=name,
        display_name=display_name,
        description=description,
        icon=icon,
        version=version,
        triggers=triggers,
        modes=modes,
        instructions=instructions,
        raw=text.lstrip("﻿"),
        extra={k: v for k, v in meta.items() if k not in _KNOWN_KEYS},
    )


def render_skill_md(
    *,
    name: str,
    description: str,
    instructions: str,
    display_name: str | None = None,
    icon: str | None = None,
    version: str | None = None,
    triggers: list[str] | None = None,
    modes: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Build a SKILL.md from editor fields, then validate it."""
    meta: dict[str, Any] = {"name": name}
    if display_name:
        meta["display_name"] = display_name
    meta["description"] = description
    if icon:
        meta["icon"] = icon
    if version:
        meta["version"] = version
    if triggers:
        meta["triggers"] = list(triggers)
    if modes:
        meta["modes"] = list(modes)
    for k, v in (extra or {}).items():
        meta.setdefault(k, v)
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    text = f"---\n{front}\n---\n\n{instructions.strip()}\n"
    parse_skill_md(text)  # validate
    return text


def instructions_of(skill_md: str) -> str:
    """Markdown body of a stored SKILL.md, tolerant of legacy/odd text."""
    try:
        return split_frontmatter(skill_md)[1].strip()
    except SkillValidationError:
        return skill_md.strip()


def checksum(skill_md: str, files: dict[str, str] | None = None) -> str:
    h = hashlib.sha256(skill_md.encode("utf-8"))
    for path in sorted(files or {}):
        h.update(b"\0" + path.encode("utf-8") + b"\0" + (files or {})[path].encode("utf-8"))
    return h.hexdigest()
