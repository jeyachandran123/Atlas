"""Google Drive: find your files and, when asked, read one document. Read-only.

Uses the drive.readonly scope. Listing and searching return file names, types,
owners and modified dates. Reading is limited to a single Google Doc or plain-text
file the search narrowed to one match, and is cut to a few thousand characters.
"""

from __future__ import annotations

import re

import httpx

from app.plugins import google
from app.plugins.base import (
    PluginError, PluginResult, PluginSpec, any_of, clip, has_command, is_mine, strip_command,
)

API = "https://www.googleapis.com/drive/v3"
READ_LIMIT = 4000   # characters of a document given to the model

SPEC = PluginSpec(
    id="drive",
    name="Google Drive",
    description="Find your files and ask about a document's contents (read-only).",
    icon="hard-drive",
    auth="oauth",
    examples=("What are my latest Drive files?", "Summarise my document called Project Plan", "/drive budget"),
    setup_hint="Sign in with Google and allow read-only access to your Drive.",
)

_TYPES = {
    "application/vnd.google-apps.document": "Google Doc",
    "application/vnd.google-apps.spreadsheet": "Google Sheet",
    "application/vnd.google-apps.presentation": "Google Slides",
    "application/vnd.google-apps.folder": "folder",
    "application/pdf": "PDF",
}
_NAMED = re.compile(
    r"""(?:named|called|titled|name)\s+["“']?([^"”'?!.]+?)["”']?\s*(?:$|[?!.]|\s+(?:in|on|from)\s)""", re.I
)
_QUOTED = re.compile(r"""["“]([^"”]{2,80})["”]""")
_READ = r"\b(read|summari[sz]e|summary|open|what('s| is| does)?\s+(in|say)|contents? of|tell me about)\b"
_DOC_WORDS = r"\b(documents?|docs?|spreadsheets?|sheets|presentations?|slides|files?|pdfs?)\b"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def search_term(message: str) -> str:
    """The file name the user means: a quoted phrase, or what follows 'named/called'."""
    msg = strip_command(message, "drive")
    m = _QUOTED.search(msg) or _NAMED.search(msg)
    if m:
        return m.group(1).strip()
    if has_command(message, "drive"):
        # "/drive budget": whatever follows the command is the name.
        return re.sub(_DOC_WORDS, "", msg, flags=re.I).strip(" ?!.")
    return ""


class Drive:
    spec = SPEC

    def wants(self, message: str) -> list[str]:
        explicit = has_command(message, "drive")
        names_drive = any_of(r"\b(google drive|my drive|gdrive|in drive)\b|\bdrive\b", message)
        owns_docs = is_mine(message) and any_of(_DOC_WORDS, message) and any_of(r"\b(google|drive)\b", message)
        if not (explicit or names_drive or owns_docs):
            return []
        # A question about the car "drive" or a disk drive is not about Google Drive.
        if not explicit and any_of(r"\b(hard|disk|usb|flash|test|drive-through|drive thru)\b", message):
            return []
        return ["read" if any_of(_READ, message) and search_term(message) else "search"]

    async def run(self, secret: dict, tool: str, message: str, client: httpx.AsyncClient) -> PluginResult:
        token = await google.access_token(client, secret["refresh_token"])
        headers = {"Authorization": f"Bearer {token}"}
        term = search_term(message)
        q = "trashed = false"
        if term:
            q += f" and name contains '{_escape(term)}'"

        r = await client.get(
            f"{API}/files",
            headers=headers,
            params={
                "q": q,
                "pageSize": 8,
                "orderBy": "modifiedTime desc",
                "fields": "files(id,name,mimeType,modifiedTime,webViewLink,owners(displayName))",
            },
        )
        if r.status_code in (401, 403):
            raise PluginError("Drive refused access. Reconnect Google Drive.")
        if r.status_code >= 400:
            raise PluginError(f"Drive returned {r.status_code}.")
        files = r.json().get("files", [])

        def describe(f: dict) -> str:
            kind = _TYPES.get(f.get("mimeType", ""), "file")
            owner = (f.get("owners") or [{}])[0].get("displayName", "")
            return (
                f"{clip(f['name'], 80)} ({kind}, modified {str(f.get('modifiedTime', ''))[:10]}"
                f"{', owner ' + owner if owner else ''}) {f.get('webViewLink', '')}"
            )

        label = f"files matching '{term}'" if term else "your most recently modified files"
        lines = [describe(f) for f in files] or ["no matching files"]

        # Reading: only when the search found exactly one file, so the model is
        # never handed an arbitrary document because it ranked first.
        if tool == "read" and len(files) == 1:
            text = await self._content(client, headers, files[0])
            if text:
                lines.append(f"CONTENT of '{files[0]['name']}' (first {READ_LIMIT} characters):\n{text}")
        elif tool == "read" and len(files) > 1:
            lines.append("Several files match; ask the user which one they mean.")
        return PluginResult("drive", tool, label, lines)

    async def _content(self, client: httpx.AsyncClient, headers: dict, f: dict) -> str:
        mime = f.get("mimeType", "")
        if mime == "application/vnd.google-apps.document":
            r = await client.get(
                f"{API}/files/{f['id']}/export", headers=headers, params={"mimeType": "text/plain"}
            )
        elif mime.startswith("text/") or mime in ("application/json", "text/csv"):
            r = await client.get(f"{API}/files/{f['id']}", headers=headers, params={"alt": "media"})
        else:
            return ""   # sheets, slides, PDFs, binaries: listed, not read
        if r.status_code >= 400:
            return ""
        return r.text[:READ_LIMIT].strip()
