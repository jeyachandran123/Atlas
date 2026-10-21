"""GitHub: your repositories, pull requests and issues. Read-only.

Connects with a personal access token the user creates (Settings -> Developer
settings -> Personal access tokens). A fine-grained token with read-only access
is enough and is what the setup hint recommends; the token is encrypted at rest.
"""

from __future__ import annotations

import httpx

from app.plugins.base import (
    PluginError, PluginResult, PluginSpec, any_of, clip, has_command, is_mine,
)

API = "https://api.github.com"

SPEC = PluginSpec(
    id="github",
    name="GitHub",
    description="Ask about your repositories, pull requests and issues.",
    icon="github",
    auth="token",
    examples=("What are my open pull requests?", "Which issues are assigned to me?", "/github my repos"),
    setup_hint=(
        "Create a fine-grained personal access token at github.com/settings/tokens "
        "with read-only access, then paste it here."
    ),
)

_PR = r"\b(pull requests?|prs?)\b"
_ISSUE = r"\bissues?\b"
_REPO = r"\b(repos?|repositories)\b"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _get(client: httpx.AsyncClient, token: str, path: str, **params) -> dict | list:
    r = await client.get(f"{API}{path}", headers=_headers(token), params=params or None)
    if r.status_code == 401:
        raise PluginError("GitHub rejected the token. Reconnect GitHub with a new token.")
    if r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0":
        raise PluginError("GitHub's rate limit was reached. Try again in a few minutes.")
    if r.status_code >= 400:
        raise PluginError(f"GitHub returned {r.status_code}.")
    return r.json()


async def verify(client: httpx.AsyncClient, token: str) -> str:
    """The account this token belongs to (its login). Raises PluginError if refused."""
    data = await _get(client, token, "/user")
    return str(data.get("login") or "")


class GitHub:
    spec = SPEC

    def wants(self, message: str) -> list[str]:
        explicit = has_command(message, "github")
        if not (explicit or is_mine(message)):
            return []
        tools: list[str] = []
        if any_of(_PR, message):
            tools.append("review_requests" if any_of(r"\breview", message) else "open_prs")
        if any_of(_ISSUE, message):
            tools.append("assigned_issues")
        if any_of(_REPO, message):
            tools.append("repos")
        if not tools and explicit:
            tools = ["open_prs", "assigned_issues"]
        return tools

    async def run(self, secret: dict, tool: str, message: str, client: httpx.AsyncClient) -> PluginResult:
        token = secret["token"]
        if tool == "open_prs":
            return await self._search(client, token, tool, "your open pull requests",
                                      "is:pr is:open author:@me archived:false")
        if tool == "review_requests":
            return await self._search(client, token, tool, "pull requests waiting for your review",
                                      "is:pr is:open review-requested:@me archived:false")
        if tool == "assigned_issues":
            return await self._search(client, token, tool, "open issues assigned to you",
                                      "is:issue is:open assignee:@me archived:false")
        if tool == "repos":
            repos = await _get(client, token, "/user/repos", sort="pushed", per_page=8, affiliation="owner,collaborator")
            lines = [
                f"{r['full_name']} - {clip(r.get('description') or 'no description', 80)} "
                f"(pushed {str(r.get('pushed_at', ''))[:10]})"
                for r in repos
            ]
            return PluginResult("github", tool, "your most recently updated repositories", lines)
        raise PluginError(f"Unknown GitHub tool {tool!r}")

    async def _search(self, client, token, tool: str, title: str, query: str) -> PluginResult:
        data = await _get(client, token, "/search/issues", q=query, sort="updated", order="desc", per_page=8)
        lines = [
            f"{i['repository_url'].rsplit('/repos/', 1)[-1]}#{i['number']} {clip(i['title'], 90)} "
            f"(updated {str(i.get('updated_at', ''))[:10]}) {i['html_url']}"
            for i in data.get("items", [])
        ]
        total = data.get("total_count", len(lines))
        if total > len(lines):
            lines.append(f"... and {total - len(lines)} more")
        return PluginResult("github", tool, title, lines or ["none found"])
