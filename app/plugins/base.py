"""Shared types and the small bits of language understanding plugins use.

Which tool to run for a message is decided by rules, not by the model. On a
CPU-only machine a second model call to "choose a tool" costs as much as the
answer itself, and a small model chooses badly; a plain pattern ("my open PRs",
"/gmail unread") is instant, predictable and testable. The price is that a
phrasing the rules don't know is simply not recognised, and `/github`, `/gmail`
and `/drive` are the sure-fire way to ask.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx


class PluginError(Exception):
    """A plugin call failed in a way the user can act on (rejected token, no access)."""


@dataclass(frozen=True)
class PluginSpec:
    id: str
    name: str
    description: str
    icon: str
    auth: Literal["token", "oauth"]
    examples: tuple[str, ...]
    setup_hint: str = ""


@dataclass
class PluginResult:
    plugin: str            # spec id
    tool: str              # e.g. "open_prs"
    title: str             # shown to the model above the data
    lines: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ref(self) -> str:
        return f"{self.plugin}__{self.tool}"


class Provider(Protocol):
    spec: PluginSpec

    def wants(self, message: str) -> list[str]:
        """Tools to run for this message ([] = not about this plugin)."""

    async def run(
        self, secret: dict, tool: str, message: str, client: httpx.AsyncClient
    ) -> PluginResult: ...


# ── Understanding a message ──────────────────────────────────────────────────

_MINE = re.compile(r"\b(my|mine|i have|i've|i got|did i)\b", re.I)


def is_mine(message: str) -> bool:
    return bool(_MINE.search(message))


def has_command(message: str, plugin_id: str) -> bool:
    """`/github ...` anywhere in the message, as its own word."""
    return bool(re.search(rf"(?:^|\s)/{re.escape(plugin_id)}\b", message, re.I))


def strip_command(message: str, plugin_id: str) -> str:
    return re.sub(rf"(?:^|\s)/{re.escape(plugin_id)}\b", " ", message, flags=re.I).strip()


def any_of(pattern: str, message: str) -> bool:
    return bool(re.search(pattern, message, re.I))


def clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
