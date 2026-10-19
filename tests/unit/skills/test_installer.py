"""Skill installer — GitHub tree/blob and raw URLs, all mocked (no network)."""

from __future__ import annotations

import io
import json
import zipfile

import httpx
import pytest

from app.shared.ssrf import UnsafeURLError
from app.skills.installer import SkillInstaller
from app.skills.parser import SkillValidationError

PUBLIC = "93.184.216.34"
SKILL_MD = "---\nname: gh-skill\ndescription: From GitHub.\n---\n# GH\nSteps.\n"


async def _resolve(host: str, port: int) -> list[str]:
    return [PUBLIC]


def _installer(handler, token: str = "") -> SkillInstaller:
    return SkillInstaller(
        resolver=_resolve, transport=httpx.MockTransport(handler), github_token=token
    )


def _github_handler(seen: list[httpx.Request]):
    tree = {
        "skills/gh-skill": [
            {
                "type": "file",
                "path": "skills/gh-skill/SKILL.md",
                "size": len(SKILL_MD),
                "download_url": "https://raw.githubusercontent.com/o/r/main/skills/gh-skill/SKILL.md",
            },
            {"type": "dir", "path": "skills/gh-skill/references", "size": 0},
        ],
        "skills/gh-skill/references": [
            {
                "type": "file",
                "path": "skills/gh-skill/references/a.md",
                "size": 3,
                "download_url": "https://raw.githubusercontent.com/o/r/main/skills/gh-skill/references/a.md",
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "api.github.com":
            path = request.url.path.split("/contents/", 1)[1]
            return httpx.Response(200, json=tree[path])
        if request.url.path.endswith("SKILL.md"):
            return httpx.Response(200, text=SKILL_MD)
        if request.url.path.endswith("a.md"):
            return httpx.Response(200, text="ref")
        return httpx.Response(404)

    return handler


async def test_install_github_tree() -> None:
    seen: list[httpx.Request] = []
    result = await _installer(_github_handler(seen), token="ghp_secret").install(
        "https://github.com/o/r/tree/main/skills/gh-skill"
    )
    assert result.package.skill.name == "gh-skill"
    assert result.package.files == {"references/a.md": "ref"}
    assert result.source_ref == "https://github.com/o/r/tree/main/skills/gh-skill"
    # token only ever goes to GitHub hosts
    assert all(r.headers.get("authorization") == "Bearer ghp_secret" for r in seen)


async def test_install_github_blob() -> None:
    seen: list[httpx.Request] = []
    result = await _installer(_github_handler(seen)).install(
        "https://github.com/o/r/blob/main/skills/gh-skill/SKILL.md"
    )
    assert result.package.skill.name == "gh-skill"
    assert seen[0].url.host == "raw.githubusercontent.com"
    assert "authorization" not in seen[0].headers  # no token configured


async def test_token_not_sent_to_other_hosts() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=SKILL_MD)

    await _installer(handler, token="ghp_secret").install("https://skills.example.com/SKILL.md")
    assert "authorization" not in seen[0].headers


async def test_install_raw_zip() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("gh-skill/SKILL.md", SKILL_MD)
    data = buf.getvalue()
    result = await _installer(lambda r: httpx.Response(200, content=data)).install(
        "https://cdn.example.com/download?id=1"
    )
    assert result.package.skill.name == "gh-skill"


async def test_tree_without_skill_md() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=(
                json.dumps(
                    [
                        {
                            "type": "file",
                            "path": "x/README.md",
                            "size": 2,
                            "download_url": "https://raw.githubusercontent.com/o/r/main/x/README.md",
                        }
                    ]
                )
                if request.url.host == "api.github.com"
                else "hi"
            ),
        )

    with pytest.raises(SkillValidationError, match="No SKILL.md"):
        await _installer(handler).install("https://github.com/o/r/tree/main/x")


async def test_bad_github_url_shape() -> None:
    with pytest.raises(SkillValidationError, match="tree"):
        await _installer(lambda r: httpx.Response(200)).install("https://github.com/o/r")


async def test_http_url_rejected() -> None:
    with pytest.raises(UnsafeURLError):
        await _installer(lambda r: httpx.Response(200)).install("http://example.com/SKILL.md")
