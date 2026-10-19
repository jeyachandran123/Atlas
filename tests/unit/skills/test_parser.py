"""SKILL.md parsing and validation."""

from __future__ import annotations

import pytest

from app.skills.parser import (
    MAX_SKILL_MD_BYTES,
    SkillValidationError,
    checksum,
    instructions_of,
    parse_skill_md,
    render_skill_md,
)

VALID = """---
name: review-agent
display_name: Review Agent
description: Find actionable bugs in code changes.
icon: bug
version: 1.2.0
triggers: [review, pull request, diff]
modes: [code, auto]
author: someone
---
# Review Agent
Report only actionable bugs.
"""


def _md(front: str, body: str = "Do the thing.") -> str:
    return f"---\n{front}\n---\n{body}\n"


def test_parses_all_fields() -> None:
    p = parse_skill_md(VALID)
    assert p.name == "review-agent"
    assert p.display_name == "Review Agent"
    assert p.description == "Find actionable bugs in code changes."
    assert p.icon == "bug"
    assert p.version == "1.2.0"
    assert p.triggers == ["review", "pull request", "diff"]
    assert p.modes == ["code", "auto"]
    assert p.instructions.startswith("# Review Agent")
    assert p.extra == {"author": "someone"}
    assert p.raw == VALID


def test_defaults_for_optional_fields() -> None:
    p = parse_skill_md(_md("name: my-skill\ndescription: Does things."))
    assert p.display_name == "My Skill"
    assert p.icon == "sparkles"
    assert p.version == "1.0.0"
    assert p.triggers == [] and p.modes == []


def test_triggers_accept_comma_string_and_dedupe() -> None:
    p = parse_skill_md(_md("name: a\ndescription: d\ntriggers: 'foo, bar, foo'"))
    assert p.triggers == ["foo", "bar"]


@pytest.mark.parametrize(
    "front,message",
    [
        ("description: d", "'name' is required"),
        ("name: a", "'description' is required"),
        ("name: Not_Kebab\ndescription: d", "kebab-case"),
        ("name: -bad-\ndescription: d", "kebab-case"),
        (f"name: {'a' * 65}\ndescription: d", "kebab-case"),
        (f"name: a\ndescription: {'x' * 1025}", "at most 1024"),
        ("name: a\ndescription: d\nmodes: [code, chaos]", "Unknown mode"),
        ("name: a\ndescription: d\nicon: '<script>'", "'icon'"),
        ("name: a\ndescription: d\ntriggers: {x: 1}", "list of strings"),
        ("- just\n- a list", "mapping"),
        ("name: [unclosed", "Invalid YAML"),
    ],
)
def test_rejects_invalid_frontmatter(front: str, message: str) -> None:
    with pytest.raises(SkillValidationError, match=message):
        parse_skill_md(_md(front))


def test_requires_frontmatter() -> None:
    with pytest.raises(SkillValidationError, match="frontmatter"):
        parse_skill_md("# No frontmatter\nhello")


def test_requires_instructions() -> None:
    with pytest.raises(SkillValidationError, match="no instructions"):
        parse_skill_md("---\nname: a\ndescription: d\n---\n   \n")


def test_size_limit() -> None:
    big = _md("name: a\ndescription: d", "x" * MAX_SKILL_MD_BYTES)
    with pytest.raises(SkillValidationError, match="50 KB"):
        parse_skill_md(big)


def test_bom_and_crlf_tolerated() -> None:
    text = "﻿---\r\nname: a\r\ndescription: d\r\n---\r\nBody\r\n"
    assert parse_skill_md(text).instructions == "Body"


def test_render_round_trip() -> None:
    md = render_skill_md(
        name="x-skill",
        description="Desc",
        instructions="# X\nSteps",
        display_name="X Skill",
        triggers=["one", "two"],
        modes=["auto"],
    )
    p = parse_skill_md(md)
    assert (p.name, p.display_name, p.triggers, p.modes) == (
        "x-skill",
        "X Skill",
        ["one", "two"],
        ["auto"],
    )
    assert instructions_of(md) == "# X\nSteps"


def test_render_validates() -> None:
    with pytest.raises(SkillValidationError):
        render_skill_md(name="Bad Name", description="d", instructions="i")


def test_checksum_covers_files() -> None:
    assert checksum(VALID) != checksum(VALID, {"references/a.md": "x"})
    assert checksum(VALID, {"a": "1", "b": "2"}) == checksum(VALID, {"b": "2", "a": "1"})
