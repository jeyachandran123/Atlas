"""Plugins API and their use in chat. GitHub and Google are replaced by a mock
transport, so these tests read what Atlas sends and returns, not the real services."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.config import get_settings
from app.db.models import MessageCapability, PluginConnection
from app.plugins import google

TOKEN = "github_pat_1234567890abcdefghij"


@pytest.fixture(autouse=True)
def brain_off(monkeypatch) -> None:
    monkeypatch.setattr("app.cognitive_integration.cognitive_brain_enabled", lambda: False)


@pytest.fixture(autouse=True)
def no_documents(monkeypatch) -> None:
    async def _none(db, conversation_id):  # noqa: ANN001
        return False

    monkeypatch.setattr("app.api.v1.chat.router._ensure_document_context", _none)


@pytest.fixture
def upstream(monkeypatch) -> dict[str, Any]:
    """GitHub + Google as a mock transport. `seen` records every request made."""
    seen: dict[str, Any] = {"requests": [], "github_ok": True}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["requests"].append(request)
        host, path = request.url.host, request.url.path
        if host == "api.github.com":
            if not seen["github_ok"]:
                return httpx.Response(401, json={"message": "Bad credentials"})
            if path == "/user":
                return httpx.Response(200, json={"login": "octocat"})
            if path == "/search/issues":
                return httpx.Response(200, json={"total_count": 1, "items": [{
                    "repository_url": "https://api.github.com/repos/acme/web", "number": 42,
                    "title": "Fix the login redirect", "updated_at": "2026-10-18T10:00:00Z",
                    "html_url": "https://github.com/acme/web/pull/42"}]})
            if path == "/user/repos":
                return httpx.Response(200, json=[{"full_name": "acme/web", "description": "Web app",
                                                  "pushed_at": "2026-10-19T00:00:00Z"}])
        if host == "oauth2.googleapis.com" and path == "/token":
            form = parse_qs(request.content.decode())
            if form.get("grant_type") == ["authorization_code"]:
                return httpx.Response(200, json={"access_token": "ya29.a", "refresh_token": "1//refresh",
                                                 "expires_in": 3600})
            return httpx.Response(200, json={"access_token": "ya29.b", "expires_in": 3600})
        if host == "openidconnect.googleapis.com":
            return httpx.Response(200, json={"email": "me@example.com"})
        if host == "oauth2.googleapis.com" and path == "/revoke":
            return httpx.Response(200)
        if host == "gmail.googleapis.com":
            if path.endswith("/messages"):
                return httpx.Response(200, json={"messages": [{"id": "m1"}]})
            return httpx.Response(200, json={
                "labelIds": ["UNREAD"], "snippet": "Your invoice is attached",
                "payload": {"headers": [{"name": "From", "value": "Billing <b@acme.com>"},
                                        {"name": "Subject", "value": "Invoice 17"},
                                        {"name": "Date", "value": "Mon, 19 Oct 2026"}]}})
        return httpx.Response(404, json={})

    monkeypatch.setattr(
        "app.plugins.service._client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    google._cache.clear()
    return seen


@pytest.fixture
def google_configured(monkeypatch) -> None:
    cfg = get_settings()
    monkeypatch.setattr(cfg, "google_oauth_client_id", "client-id.apps.googleusercontent.com")
    monkeypatch.setattr(cfg, "google_oauth_client_secret", SecretStr("client-secret"))


async def connect_github(client: AsyncClient, headers) -> dict:
    resp = await client.post("/api/v1/plugins/github/connect", json={"token": TOKEN}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── List / connect ───────────────────────────────────────────────────────────


async def test_lists_every_plugin_disconnected(sk_client: AsyncClient, auth) -> None:
    body = (await sk_client.get("/api/v1/plugins", headers=auth("dev"))).json()["plugins"]
    assert [p["id"] for p in body] == ["github", "gmail", "drive"]
    assert all(not p["connected"] and not p["enabled"] for p in body)
    assert body[0]["available"] is True
    assert body[1]["available"] is False and "GOOGLE_OAUTH_CLIENT_ID" in body[1]["unavailable_reason"]


async def test_github_connects_with_a_token_that_is_stored_encrypted_and_never_returned(
    sk_client: AsyncClient, sk_session, auth, upstream
) -> None:
    view = await connect_github(sk_client, auth("dev"))
    assert view["connected"] and view["enabled"] and view["account"] == "octocat"
    assert TOKEN not in json.dumps(view)

    row = (await sk_session.execute(select(PluginConnection))).scalars().one()
    assert TOKEN not in row.secret_encrypted
    listed = (await sk_client.get("/api/v1/plugins", headers=auth("dev"))).text
    assert TOKEN not in listed and row.secret_encrypted not in listed

    sent = [r for r in upstream["requests"] if r.url.path == "/user"][0]
    assert sent.headers["authorization"] == f"Bearer {TOKEN}"


async def test_a_rejected_token_is_not_stored(sk_client: AsyncClient, sk_session, auth, upstream) -> None:
    upstream["github_ok"] = False
    resp = await sk_client.post("/api/v1/plugins/github/connect", json={"token": TOKEN}, headers=auth("dev"))
    assert resp.status_code == 400 and "rejected" in resp.json()["detail"]
    assert (await sk_session.execute(select(PluginConnection))).scalars().all() == []


async def test_connections_are_private_to_each_user(sk_client: AsyncClient, auth, upstream) -> None:
    await connect_github(sk_client, auth("dev"))
    other = (await sk_client.get("/api/v1/plugins", headers=auth("dev2"))).json()["plugins"]
    assert not other[0]["connected"]


async def test_disable_enable_and_disconnect(sk_client: AsyncClient, sk_session, auth, upstream) -> None:
    await connect_github(sk_client, auth("dev"))
    off = (await sk_client.post("/api/v1/plugins/github/disable", headers=auth("dev"))).json()
    assert off["connected"] and not off["enabled"]
    on = (await sk_client.post("/api/v1/plugins/github/enable", headers=auth("dev"))).json()
    assert on["enabled"]
    assert (await sk_client.delete("/api/v1/plugins/github", headers=auth("dev"))).status_code == 204
    assert (await sk_session.execute(select(PluginConnection))).scalars().all() == []
    assert (await sk_client.post("/api/v1/plugins/github/enable", headers=auth("dev"))).status_code == 404


async def test_test_button_runs_the_plugin_once(sk_client: AsyncClient, auth, upstream) -> None:
    await connect_github(sk_client, auth("dev"))
    out = (await sk_client.post("/api/v1/plugins/github/test", headers=auth("dev"))).json()
    assert out["ok"] and out["lines"] and "acme/web" in out["lines"][0]


async def test_everything_404s_when_plugins_are_off(sk_client: AsyncClient, auth, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "enable_plugins", False)
    assert (await sk_client.get("/api/v1/plugins", headers=auth("dev"))).status_code == 404


# ── Google sign-in ───────────────────────────────────────────────────────────


async def test_google_sign_in_needs_the_server_to_be_configured(sk_client: AsyncClient, auth) -> None:
    resp = await sk_client.get("/api/v1/plugins/gmail/oauth/start", headers=auth("dev"))
    assert resp.status_code == 400 and "GOOGLE_OAUTH_CLIENT_ID" in resp.json()["detail"]


async def test_google_flow_connects_gmail_with_a_read_only_scope(
    sk_client: AsyncClient, sk_session, auth, upstream, google_configured
) -> None:
    url = (await sk_client.get("/api/v1/plugins/gmail/oauth/start", headers=auth("dev"))).json()["url"]
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["client-id.apps.googleusercontent.com"]
    assert "gmail.readonly" in q["scope"][0] and "drive" not in q["scope"][0]
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]

    cb = await sk_client.get(
        "/api/v1/plugins/oauth/google/callback", params={"code": "abc", "state": q["state"][0]},
        follow_redirects=False,
    )
    assert cb.status_code in (302, 307) and "connected=gmail" in cb.headers["location"]
    row = (await sk_session.execute(select(PluginConnection))).scalars().one()
    assert row.plugin == "gmail" and row.account == "me@example.com"
    assert "1//refresh" not in row.secret_encrypted


async def test_a_forged_or_cancelled_google_callback_connects_nothing(
    sk_client: AsyncClient, sk_session, upstream, google_configured
) -> None:
    for params in ({"code": "abc", "state": "forged"}, {"error": "access_denied", "state": "x"}):
        cb = await sk_client.get("/api/v1/plugins/oauth/google/callback", params=params, follow_redirects=False)
        assert cb.status_code in (302, 307) and "error=" in cb.headers["location"]
    assert (await sk_session.execute(select(PluginConnection))).scalars().all() == []


# ── In chat ──────────────────────────────────────────────────────────────────


def _sse(text: str) -> list[dict]:
    events = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    return [e for e in events if e.get("type") != "meta"]


async def ask(client: AsyncClient, headers, message: str) -> list[dict]:
    resp = await client.post("/api/v1/chat/stream", json={"message": message, "agent_mode": "auto"}, headers=headers)
    assert resp.status_code == 200, resp.text
    return _sse(resp.text)


async def test_chat_answers_from_connected_data_and_reports_it(
    sk_client: AsyncClient, sk_session, auth, upstream, fake_llm
) -> None:
    await connect_github(sk_client, auth("dev"))
    events = await ask(sk_client, auth("dev"), "What are my open pull requests?")

    system = fake_llm.calls[0]["system_prompt"]
    assert "DATA FROM THE USER'S CONNECTED ACCOUNTS" in system
    assert "acme/web#42 Fix the login redirect" in system
    done = events[-1]
    assert done["type"] == "done" and done["plugins"] == [{"slug": "github", "name": "GitHub"}]

    rows = (await sk_session.execute(select(MessageCapability))).scalars().all()
    assert [(r.kind, r.ref, r.label) for r in rows] == [("plugin_tool", "plugin:github", "GitHub")]


async def test_chat_does_not_call_a_plugin_for_an_unrelated_message(
    sk_client: AsyncClient, auth, upstream, fake_llm
) -> None:
    await connect_github(sk_client, auth("dev"))
    before = len(upstream["requests"])
    events = await ask(sk_client, auth("dev"), "What is a pull request?")
    assert len(upstream["requests"]) == before                 # no upstream call at all
    assert "plugins" not in events[-1]
    assert "DATA FROM THE USER'S CONNECTED ACCOUNTS" not in fake_llm.calls[0]["system_prompt"]


async def test_a_paused_plugin_is_not_used(sk_client: AsyncClient, auth, upstream, fake_llm) -> None:
    await connect_github(sk_client, auth("dev"))
    await sk_client.post("/api/v1/plugins/github/disable", headers=auth("dev"))
    before = len(upstream["requests"])
    await ask(sk_client, auth("dev"), "What are my open pull requests?")
    assert len(upstream["requests"]) == before


async def test_a_broken_connection_is_explained_not_hidden(
    sk_client: AsyncClient, auth, upstream, fake_llm
) -> None:
    await connect_github(sk_client, auth("dev"))
    upstream["github_ok"] = False                               # the token was revoked since
    events = await ask(sk_client, auth("dev"), "What are my open pull requests?")
    assert events[-1]["type"] == "done" and "plugins" not in events[-1]
    system = fake_llm.calls[0]["system_prompt"]
    assert "Could not be read: GitHub rejected the token" in system


async def test_gmail_in_chat_uses_the_search_the_user_described(
    sk_client: AsyncClient, auth, upstream, fake_llm, google_configured
) -> None:
    url = (await sk_client.get("/api/v1/plugins/gmail/oauth/start", headers=auth("dev"))).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    await sk_client.get("/api/v1/plugins/oauth/google/callback", params={"code": "abc", "state": state})

    await ask(sk_client, auth("dev"), "Any unread emails?")
    listing = [r for r in upstream["requests"] if r.url.host == "gmail.googleapis.com" and r.url.path.endswith("/messages")][0]
    assert listing.url.params["q"] == "is:unread in:inbox"
    assert listing.headers["authorization"] == "Bearer ya29.b"      # a fresh access token, via the refresh token
    assert "Invoice 17" in fake_llm.calls[0]["system_prompt"] and "[unread]" in fake_llm.calls[0]["system_prompt"]


# ── Chat through the Cognitive OS ────────────────────────────────────────────


async def test_the_brain_path_uses_plugins_too(
    sk_client: AsyncClient, auth, upstream, monkeypatch
) -> None:
    from app.cognitive_integration import Deliberation

    seen: dict[str, Any] = {}

    async def deliberate(message, **kw):  # noqa: ANN001
        return Deliberation(authorized=True, escalated=False, decision="answer", intent="q",
                            confidence=0.9, system_prompt="BRAIN RULES", user_prompt=message,
                            hold_message=None)

    class FakeClient:
        async def chat_stream(self, prompt, **kw):  # noqa: ANN001
            seen["system_prompt"] = kw["system_prompt"]
            yield "ok"

    async def no_web(*a, **k):  # noqa: ANN002, ANN003
        return None

    await connect_github(sk_client, auth("dev"))
    monkeypatch.setattr("app.cognitive_integration.cognitive_brain_enabled", lambda: True)
    monkeypatch.setattr("app.cognitive_integration.service.deliberate_turn", deliberate)
    monkeypatch.setattr("app.ollama_client.get_ollama_client", lambda: FakeClient())
    monkeypatch.setattr("app.api.v1.chat.router._web_events", no_web)

    events = await ask(sk_client, auth("dev"), "list my repos")
    assert events[0] == {"type": "capabilities", "plugins": [{"slug": "github", "name": "GitHub"}]}
    assert seen["system_prompt"].startswith("BRAIN RULES")      # the brain's rules stay first
    assert "acme/web" in seen["system_prompt"]
    assert events[-1]["plugins"] == [{"slug": "github", "name": "GitHub"}]
