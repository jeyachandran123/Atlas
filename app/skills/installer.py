"""
Install a skill package from a URL.

Supported:
  https://github.com/{owner}/{repo}/tree/{ref}/{path}   → whole skill folder
  https://github.com/{owner}/{repo}/blob/{ref}/{path}   → one SKILL.md / .zip
  https://raw.githubusercontent.com/...                 → one SKILL.md / .zip
  any other public https URL                            → one SKILL.md / .zip

Every request goes through app.shared.ssrf.safe_get (https only, public
addresses only, every redirect re-checked). GITHUB_TOKEN is attached only to
GitHub hosts and never logged.
"""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

import httpx

from app.config import get_settings
from app.shared.ssrf import FetchError, Resolver, safe_get
from app.skills.package import (
    MAX_PACKAGE_BYTES,
    MAX_PACKAGE_FILES,
    SKILL_FILENAME,
    SkillPackage,
    build_package,
    decode_text,
    extract_upload,
    safe_relative_path,
)
from app.skills.parser import MAX_SKILL_MD_BYTES, SkillValidationError

_GITHUB_HOSTS = {"github.com", "api.github.com", "raw.githubusercontent.com", "codeload.github.com"}
_GH_PATH_RE = re.compile(r"^/([^/]+)/([^/]+)/(tree|blob)/([^/]+)(?:/(.*))?$")
_MAX_DEPTH = 4


@dataclass(frozen=True)
class InstallResult:
    package: SkillPackage
    source_ref: str


class SkillInstaller:
    def __init__(
        self,
        resolver: Resolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        github_token: str | None = None,
    ) -> None:
        self._resolver = resolver
        self._transport = transport
        token = github_token
        if token is None:
            token = get_settings().github_token.get_secret_value()
        self._token = token or ""

    def _headers_for(self, url: str) -> dict[str, str]:
        host = (urlsplit(url).hostname or "").lower()
        headers = {"User-Agent": "Atlas-Skill-Installer"}
        if host == "api.github.com":
            headers["Accept"] = "application/vnd.github+json"
        if self._token and host in _GITHUB_HOSTS:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _get(self, url: str, max_bytes: int) -> bytes:
        result = await safe_get(
            url,
            max_bytes=max_bytes,
            headers_for=self._headers_for,
            resolver=self._resolver,
            transport=self._transport,
        )
        return result.content

    async def install(self, url: str) -> InstallResult:
        url = url.strip()
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if host == "github.com":
            match = _GH_PATH_RE.match(parts.path.rstrip("/"))
            if not match:
                raise SkillValidationError(
                    "Use a GitHub URL of the form github.com/{owner}/{repo}/tree/{ref}/{path} "
                    "or .../blob/{ref}/{path}/SKILL.md"
                )
            owner, repo, kind, ref, path = match.groups()
            path = (path or "").strip("/")
            if kind == "tree":
                return InstallResult(await self._install_tree(owner, repo, ref, path), url)
            raw = (
                f"https://raw.githubusercontent.com/{quote(owner)}/{quote(repo)}/"
                f"{quote(ref)}/{quote(path)}"
            )
            return InstallResult(await self._install_single(raw, path), url)
        return InstallResult(await self._install_single(url, posixpath.basename(parts.path)), url)

    async def _install_single(self, url: str, filename: str) -> SkillPackage:
        data = await self._get(url, MAX_PACKAGE_BYTES)
        name = filename if filename.lower().endswith((".zip", ".md")) else ""
        return extract_upload(name, data)

    async def _install_tree(self, owner: str, repo: str, ref: str, root: str) -> SkillPackage:
        files: dict[str, str] = {}
        total = 0

        async def walk(path: str, depth: int) -> None:
            nonlocal total
            if depth > _MAX_DEPTH:
                return
            api = (
                f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/contents/"
                f"{quote(path)}?ref={quote(ref)}"
            )
            try:
                listing = json.loads(await self._get(api, 512 * 1024))
            except json.JSONDecodeError as e:
                raise FetchError("GitHub returned an unexpected response") from e
            if isinstance(listing, dict):  # the path is a file, not a folder
                listing = [listing]
            if not isinstance(listing, list):
                raise FetchError("GitHub returned an unexpected response")
            for entry in listing:
                if not isinstance(entry, dict):
                    continue
                etype, epath = entry.get("type"), str(entry.get("path") or "")
                rel = posixpath.relpath(epath, root) if root else epath
                if etype == "dir":
                    await walk(epath, depth + 1)
                elif etype == "file":
                    rel = safe_relative_path(rel)
                    size = int(entry.get("size") or 0)
                    if len(files) + 1 > MAX_PACKAGE_FILES:
                        raise SkillValidationError(
                            f"A skill may contain at most {MAX_PACKAGE_FILES} files"
                        )
                    total += size
                    if total > MAX_PACKAGE_BYTES:
                        raise SkillValidationError("Skill package must be at most 2 MB")
                    download = entry.get("download_url")
                    if not download:
                        continue
                    blob = await self._get(str(download), MAX_PACKAGE_BYTES)
                    files[rel] = decode_text(blob, rel)
                # symlinks / submodules are ignored on purpose

        await walk(root, 0)
        skill_md = files.pop(SKILL_FILENAME, None)
        if skill_md is None:
            raise SkillValidationError(
                f"No {SKILL_FILENAME} found at {root or 'the repository root'}"
            )
        if len(skill_md.encode("utf-8")) > MAX_SKILL_MD_BYTES:
            raise SkillValidationError(f"SKILL.md must be at most {MAX_SKILL_MD_BYTES // 1024} KB")
        return build_package(skill_md, files)
