"""Google OAuth for the Gmail and Drive plugins.

One OAuth client (GOOGLE_OAUTH_CLIENT_ID / _SECRET) serves both; each plugin asks
for its own read-only scope, so connecting Drive never grants Gmail. Only the
refresh token is stored (encrypted); access tokens live a few minutes in memory.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt

from app.config import get_settings
from app.plugins.base import PluginError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

SCOPES: dict[str, str] = {
    "gmail": "https://www.googleapis.com/auth/gmail.readonly",
    "drive": "https://www.googleapis.com/auth/drive.readonly",
}

_STATE_TTL = timedelta(minutes=10)
_cache: dict[str, tuple[str, float]] = {}   # refresh token -> (access token, expires at)


def configured() -> bool:
    cfg = get_settings()
    return bool(cfg.google_oauth_client_id and cfg.google_oauth_client_secret.get_secret_value())


def redirect_uri() -> str:
    return f"{get_settings().backend_public_url.rstrip('/')}/api/v1/plugins/oauth/google/callback"


def make_state(user_id: str, plugin: str) -> str:
    """A short-lived signed value that ties the Google callback to this user and plugin."""
    cfg = get_settings()
    payload = {
        "sub": user_id,
        "plugin": plugin,
        "typ": "plugin_oauth",
        "exp": datetime.now(timezone.utc) + _STATE_TTL,
    }
    return jwt.encode(payload, cfg.secret_key.get_secret_value(), algorithm="HS256")


def read_state(state: str) -> tuple[str, str]:
    """(user_id, plugin) from a state we issued; PluginError if forged or expired."""
    try:
        data = jwt.decode(state, get_settings().secret_key.get_secret_value(), algorithms=["HS256"])
    except JWTError as e:
        raise PluginError("The sign-in link expired. Start the connection again.") from e
    if data.get("typ") != "plugin_oauth" or data.get("plugin") not in SCOPES:
        raise PluginError("Invalid sign-in state.")
    return str(data["sub"]), str(data["plugin"])


def auth_url(user_id: str, plugin: str) -> str:
    if not configured():
        raise PluginError(
            "Google sign-in isn't set up on this server. Set GOOGLE_OAUTH_CLIENT_ID and "
            "GOOGLE_OAUTH_CLIENT_SECRET."
        )
    params = {
        "client_id": get_settings().google_oauth_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": f"openid email {SCOPES[plugin]}",
        "access_type": "offline",     # we need a refresh token
        "prompt": "consent",          # ...and Google only issues one on a consent screen
        "state": make_state(user_id, plugin),
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(client: httpx.AsyncClient, code: str) -> dict:
    cfg = get_settings()
    r = await client.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": cfg.google_oauth_client_id,
            "client_secret": cfg.google_oauth_client_secret.get_secret_value(),
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        },
    )
    if r.status_code >= 400:
        raise PluginError("Google didn't accept the sign-in. Try connecting again.")
    data = r.json()
    if not data.get("refresh_token"):
        raise PluginError(
            "Google didn't return a long-lived token. Remove Atlas at "
            "myaccount.google.com/permissions and connect again."
        )
    return data


async def email_of(client: httpx.AsyncClient, access_token: str) -> str:
    r = await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
    return str(r.json().get("email", "")) if r.status_code == 200 else ""


async def access_token(client: httpx.AsyncClient, refresh_token: str) -> str:
    cached = _cache.get(refresh_token)
    if cached and cached[1] > time.monotonic() + 30:
        return cached[0]
    cfg = get_settings()
    r = await client.post(
        TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": cfg.google_oauth_client_id,
            "client_secret": cfg.google_oauth_client_secret.get_secret_value(),
            "grant_type": "refresh_token",
        },
    )
    if r.status_code >= 400:
        _cache.pop(refresh_token, None)
        raise PluginError("Google access was revoked or expired. Reconnect the plugin.")
    data = r.json()
    _cache[refresh_token] = (data["access_token"], time.monotonic() + int(data.get("expires_in", 3000)))
    return data["access_token"]


async def revoke(client: httpx.AsyncClient, refresh_token: str) -> None:
    """Best effort: tell Google the grant is gone. Failing must not block disconnecting."""
    _cache.pop(refresh_token, None)
    try:
        await client.post(REVOKE_URL, data={"token": refresh_token})
    except httpx.HTTPError:
        pass
