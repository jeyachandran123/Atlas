"""
Plugins API — Customize → Plugins.

  GET    /plugins                       every plugin and this user's connection to it
  POST   /plugins/github/connect        {token}     connect GitHub with an access token
  GET    /plugins/{plugin}/oauth/start  -> {url}    begin Google sign-in (gmail | drive)
  GET    /plugins/oauth/google/callback              Google returns here, then -> the app
  POST   /plugins/{plugin}/enable|disable
  POST   /plugins/{plugin}/test         run the plugin once to show it works
  DELETE /plugins/{plugin}              disconnect and forget the credential

Every route 404s while ENABLE_PLUGINS is off. Credentials are never returned.

(No `from __future__ import annotations`: FastAPI must resolve real annotation objects.)
"""

from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.db.models import User
from app.plugins import google
from app.plugins.base import PluginError
from app.plugins.service import PluginNotFound, PluginService
from app.rate_limit import limiter

CurrentUserDep = Annotated[User, Depends(get_current_user)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


async def require_plugins_enabled() -> None:
    if not get_settings().enable_plugins:
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(
    prefix="/plugins", tags=["Plugins"], dependencies=[Depends(require_plugins_enabled)]
)


class GitHubConnectIn(BaseModel):
    token: str = Field(..., min_length=8, max_length=500)


def _http(e: Exception) -> HTTPException:
    if isinstance(e, PluginNotFound):
        return HTTPException(404, detail=str(e))
    return HTTPException(400, detail=str(e))


@router.get("")
async def list_plugins(current_user: CurrentUserDep, db: DbDep) -> dict[str, list[dict[str, Any]]]:
    return {"plugins": await PluginService(db).list(current_user.id)}


@router.post("/github/connect")
@limiter.limit("10/minute")
async def connect_github(
    request: Request, body: GitHubConnectIn, current_user: CurrentUserDep, db: DbDep
) -> dict[str, Any]:
    try:
        return await PluginService(db).connect_github(current_user.id, body.token)
    except PluginError as e:
        raise _http(e) from e


@router.get("/oauth/google/callback", include_in_schema=False)
async def google_callback(
    db: DbDep, code: str = "", state: str = "", error: str = ""
) -> RedirectResponse:
    """Google sends the browser here. There is no bearer token on this request, so the
    signed `state` (issued by /oauth/start, ten minutes) is what identifies the user."""
    back = get_settings().frontend_url.rstrip("/") + "/plugins"
    try:
        if error or not code:
            raise PluginError("Google sign-in was cancelled.")
        user_id, plugin = google.read_state(state)
        await PluginService(db).connect_google(user_id, plugin, code)
    except PluginError as e:
        return RedirectResponse(f"{back}?{urlencode({'error': str(e)})}")
    return RedirectResponse(f"{back}?{urlencode({'connected': plugin})}")


@router.get("/{plugin}/oauth/start")
async def oauth_start(plugin: str, current_user: CurrentUserDep) -> dict[str, str]:
    if plugin not in google.SCOPES:
        raise HTTPException(404, detail="This plugin doesn't use Google sign-in")
    try:
        return {"url": google.auth_url(current_user.id, plugin)}
    except PluginError as e:
        raise _http(e) from e


@router.post("/{plugin}/enable")
async def enable_plugin(plugin: str, current_user: CurrentUserDep, db: DbDep) -> dict[str, Any]:
    try:
        return await PluginService(db).set_enabled(current_user.id, plugin, True)
    except PluginError as e:
        raise _http(e) from e


@router.post("/{plugin}/disable")
async def disable_plugin(plugin: str, current_user: CurrentUserDep, db: DbDep) -> dict[str, Any]:
    try:
        return await PluginService(db).set_enabled(current_user.id, plugin, False)
    except PluginError as e:
        raise _http(e) from e


@router.post("/{plugin}/test")
@limiter.limit("20/minute")
async def test_plugin(
    request: Request, plugin: str, current_user: CurrentUserDep, db: DbDep
) -> dict[str, Any]:
    try:
        return await PluginService(db).test(current_user.id, plugin)
    except PluginError as e:
        raise _http(e) from e


@router.delete("/{plugin}", status_code=204)
async def disconnect_plugin(plugin: str, current_user: CurrentUserDep, db: DbDep) -> None:
    try:
        await PluginService(db).disconnect(current_user.id, plugin)
    except PluginError as e:
        raise _http(e) from e
