"""Gmail: search and read the headers + snippet of your messages. Read-only.

Uses the gmail.readonly scope. Only From / Subject / Date and Gmail's own short
snippet are fetched, never attachments and never the full body.
"""

from __future__ import annotations

import asyncio
import re

import httpx

from app.plugins import google
from app.plugins.base import (
    PluginError, PluginResult, PluginSpec, any_of, clip, has_command, is_mine, strip_command,
)

API = "https://gmail.googleapis.com/gmail/v1/users/me"

SPEC = PluginSpec(
    id="gmail",
    name="Gmail",
    description="Ask about your recent, unread or searched emails (read-only).",
    icon="mail",
    auth="oauth",
    examples=("Any unread emails?", "What did Priya email me this week?", "/gmail invoices"),
    setup_hint="Sign in with Google and allow read-only access to your mail.",
)

_WORD = r"\b(e-?mails?|mails?|inbox|gmail)\b"
_STOP = r"(?:about|regarding|today|yesterday|this|last|in|on|with|that|and|since|after|before)"
_SENDER = re.compile(rf"\bfrom\s+([^\s,?.!]+(?:\s+(?!{_STOP}\b)[^\s,?.!]+){{0,2}})", re.I)
_TOPIC = re.compile(r"\b(?:about|regarding)\s+(.+?)(?:[?.!]|$)", re.I)
_TIMEWORDS = re.compile(r"\b(today|yesterday|(this|past|last) week)\b", re.I)
_WRITING = r"\b(write|draft|compose|send|reply|respond)\b"


def build_query(message: str) -> str:
    """A Gmail search from the way people ask: 'unread', 'from X', 'about Y', 'today'."""
    msg = strip_command(message, "gmail")
    parts: list[str] = []
    if any_of(r"\bunread\b", msg):
        parts.append("is:unread")
    sender = _SENDER.search(msg)
    if sender:
        parts.append('from:"' + sender.group(1).strip() + '"')
    topic = _TOPIC.search(msg)
    if topic:
        # "about invoices today": the time word is its own filter, not part of the topic.
        words = _TIMEWORDS.sub("", topic.group(1).replace('"', "")).strip()
        if words:
            parts.append('"' + words + '"')
    if any_of(r"\byesterday\b", msg):
        parts.append("newer_than:2d")
    elif any_of(r"\btoday\b", msg):
        parts.append("newer_than:1d")
    elif any_of(r"\b(this|past|last) week\b", msg):
        parts.append("newer_than:7d")
    # "/gmail invoices": the words themselves are the search.
    if not parts and has_command(message, "gmail") and msg:
        parts.append(msg.replace('"', ""))
    if not parts or parts == ["is:unread"]:
        parts.append("in:inbox")
    return " ".join(parts)


class Gmail:
    spec = SPEC

    def wants(self, message: str) -> list[str]:
        if has_command(message, "gmail"):
            return ["search"]
        if not any_of(_WORD, message) and not any_of(r"\bunread\b", message):
            return []
        # "emails" alone is too common a word ("how do emails work?"): it needs a
        # claim on the user's own mail.
        claims_inbox = any_of(r"\b(inbox|gmail|unread)\b", message)
        # Writing or sending mail is not reading it ("write an email to my boss").
        if any_of(_WRITING, message) and not claims_inbox:
            return []
        if (
            claims_inbox
            or is_mine(message)
            or _SENDER.search(message)
            or any_of(r"\b(latest|recent|new)\b", message)
        ):
            return ["search"]
        return []

    async def run(self, secret: dict, tool: str, message: str, client: httpx.AsyncClient) -> PluginResult:
        token = await google.access_token(client, secret["refresh_token"])
        headers = {"Authorization": f"Bearer {token}"}
        query = build_query(message)

        r = await client.get(f"{API}/messages", headers=headers, params={"q": query, "maxResults": 6})
        if r.status_code in (401, 403):
            raise PluginError("Gmail refused access. Reconnect Gmail.")
        if r.status_code >= 400:
            raise PluginError(f"Gmail returned {r.status_code}.")
        ids = [m["id"] for m in r.json().get("messages", [])]

        async def one(mid: str) -> str:
            m = await client.get(
                f"{API}/messages/{mid}",
                headers=headers,
                params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
            )
            if m.status_code >= 400:
                return ""
            data = m.json()
            h = {x["name"].lower(): x["value"] for x in data.get("payload", {}).get("headers", [])}
            unread = " [unread]" if "UNREAD" in data.get("labelIds", []) else ""
            return (
                f"From {clip(h.get('from', '?'), 60)} | {clip(h.get('subject', '(no subject)'), 90)} "
                f"| {clip(h.get('date', ''), 31)}{unread} | {clip(data.get('snippet', ''), 160)}"
            )

        lines = [ln for ln in await asyncio.gather(*(one(i) for i in ids)) if ln]
        return PluginResult("gmail", tool, f"emails matching: {query}", lines or ["no matching emails"])
