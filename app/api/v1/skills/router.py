"""
Skills API — Customize → Skills.

  GET    /skills?scope=&q=            installed + system + available
  GET    /skills/preferences          per-user default behaviour
  PUT    /skills/preferences
  GET    /skills/curated              curated install list
  POST   /skills/preview-match        which skills a message would select
  POST   /skills                      create (editor / Skill Creator)
  POST   /skills/upload               .zip package or single .md
  POST   /skills/install-from-url     GitHub tree/blob URL or raw https URL
  GET    /skills/{id}                 detail with body + files
  PATCH  /skills/{id}                 edit (owner/admin; system is read-only)
  POST   /skills/{id}/enable|disable  per-user toggle (enable also installs)
  DELETE /skills/{id}                 uninstall / remove

Every route 404s while ENABLE_SKILLS is off.

(No `from __future__ import annotations`: slowapi's decorator wraps the
endpoint, and FastAPI must resolve real annotation objects, not strings.)
"""

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_developer
from app.config import get_settings
from app.database import get_db
from app.db.models import User
from app.rate_limit import limiter
from app.shared.ssrf import FetchError, UnsafeURLError
from app.skills.installer import SkillInstaller
from app.skills.package import MAX_PACKAGE_BYTES, build_package, extract_upload
from app.skills.parser import SkillValidationError, render_skill_md
from app.skills.schemas import (
    InstallFromUrlIn,
    PreviewMatchIn,
    SkillCreateIn,
    SkillPreferencesIn,
    SkillPreferencesOut,
    SkillUpdateIn,
)
from app.skills.service import SkillError, SkillService

CURATED_FILE = Path(__file__).resolve().parents[3] / "skills" / "curated.json"

CurrentUserDep = Annotated[User, Depends(get_current_user)]
DeveloperDep = Annotated[User, Depends(require_developer)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


async def require_skills_enabled() -> None:
    if not get_settings().enable_skills:
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(
    prefix="/skills", tags=["Skills"], dependencies=[Depends(require_skills_enabled)]
)


def _http(e: Exception) -> HTTPException:
    if isinstance(e, SkillError):
        return HTTPException(e.status_code, detail=e.message)
    if isinstance(e, SkillValidationError):
        return HTTPException(422, detail=str(e))
    if isinstance(e, UnsafeURLError):
        return HTTPException(400, detail=str(e))
    if isinstance(e, FetchError):
        return HTTPException(502, detail=str(e))
    raise e


async def _detail(service: SkillService, user: User, skill_id: str) -> dict[str, Any]:
    return await service.detail(user, skill_id)


# ── Collection ───────────────────────────────────────────────────────────────


@router.get("")
async def list_skills(
    current_user: CurrentUserDep,
    db: DbDep,
    scope: str | None = None,
    q: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if scope and scope not in ("system", "org", "personal"):
        raise HTTPException(422, detail="scope must be system, org or personal")
    return await SkillService(db).list_for_user(current_user, scope, (q or "").strip() or None)


@router.get("/preferences", response_model=SkillPreferencesOut)
async def get_preferences(
    current_user: CurrentUserDep,
    db: DbDep,
) -> SkillPreferencesOut:
    prefs = await SkillService(db).preferences(current_user.id)
    return SkillPreferencesOut(**prefs.__dict__)


@router.put("/preferences", response_model=SkillPreferencesOut)
async def put_preferences(
    body: SkillPreferencesIn,
    current_user: CurrentUserDep,
    db: DbDep,
) -> SkillPreferencesOut:
    try:
        prefs = await SkillService(db).save_preferences(
            current_user.id, body.auto_select, body.max_active
        )
    except SkillError as e:
        raise _http(e) from e
    return SkillPreferencesOut(**prefs.__dict__)


@router.get("/curated")
async def curated_skills(
    current_user: CurrentUserDep,
) -> dict[str, list[dict[str, Any]]]:
    try:
        items = json.loads(CURATED_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        items = []
    return {"skills": items if isinstance(items, list) else []}


@router.post("/preview-match")
async def preview_match(
    body: PreviewMatchIn,
    current_user: CurrentUserDep,
    db: DbDep,
) -> dict[str, Any]:
    return await SkillService(db).preview(current_user, body.message, body.agent_mode)


@router.post("", status_code=201)
async def create_skill(
    body: SkillCreateIn,
    current_user: DeveloperDep,
    db: DbDep,
) -> dict[str, Any]:
    service = SkillService(db)
    try:
        if body.skill_md:
            skill_md = body.skill_md
        else:
            if not (body.name and body.description and body.instructions):
                raise SkillValidationError("Provide skill_md, or name + description + instructions")
            skill_md = render_skill_md(
                name=body.name,
                description=body.description,
                instructions=body.instructions,
                display_name=body.display_name,
                icon=body.icon,
                version=body.version,
                triggers=body.triggers,
                modes=body.modes,
            )
        files = {f.path: f.content for f in body.files or []}
        pkg = build_package(skill_md, files)
        skill = await service.create(current_user, pkg, scope=body.scope, source="editor")
    except (SkillError, SkillValidationError) as e:
        raise _http(e) from e
    return await _detail(service, current_user, skill.id)


@router.post("/upload", status_code=201)
@limiter.limit("20/minute")
async def upload_skill(
    request: Request,
    file: Annotated[UploadFile, File()],
    current_user: DeveloperDep,
    db: DbDep,
    scope: Annotated[str, Form()] = "personal",
) -> dict[str, Any]:
    service = SkillService(db)
    data = await file.read(MAX_PACKAGE_BYTES + 1)
    try:
        if len(data) > MAX_PACKAGE_BYTES:
            raise SkillValidationError("Skill package must be at most 2 MB")
        pkg = extract_upload(file.filename or "", data)
        skill = await service.create(
            current_user, pkg, scope=scope, source="upload", source_ref=file.filename
        )
    except (SkillError, SkillValidationError) as e:
        raise _http(e) from e
    return await _detail(service, current_user, skill.id)


@router.post("/install-from-url", status_code=201)
@limiter.limit("10/minute")
async def install_from_url(
    request: Request,
    body: InstallFromUrlIn,
    current_user: DeveloperDep,
    db: DbDep,
) -> dict[str, Any]:
    service = SkillService(db)
    try:
        result = await SkillInstaller().install(body.url)
        skill = await service.create(
            current_user,
            result.package,
            scope=body.scope,
            source="git",
            source_ref=result.source_ref,
        )
    except (SkillError, SkillValidationError, UnsafeURLError, FetchError) as e:
        raise _http(e) from e
    return await _detail(service, current_user, skill.id)


# ── Item ─────────────────────────────────────────────────────────────────────


@router.get("/{skill_id}")
async def get_skill(
    skill_id: str,
    current_user: CurrentUserDep,
    db: DbDep,
) -> dict[str, Any]:
    try:
        return await _detail(SkillService(db), current_user, skill_id)
    except SkillError as e:
        raise _http(e) from e


@router.patch("/{skill_id}")
async def update_skill(
    skill_id: str,
    body: SkillUpdateIn,
    current_user: DeveloperDep,
    db: DbDep,
) -> dict[str, Any]:
    service = SkillService(db)
    changes = body.model_dump(exclude_unset=True)
    if body.files is not None:
        changes["files"] = {f.path: f.content for f in body.files}
    try:
        await service.update(current_user, skill_id, changes)
    except (SkillError, SkillValidationError) as e:
        raise _http(e) from e
    return await _detail(service, current_user, skill_id)


@router.post("/{skill_id}/enable")
async def enable_skill(
    skill_id: str,
    current_user: DeveloperDep,
    db: DbDep,
) -> dict[str, Any]:
    try:
        return await SkillService(db).set_enabled(current_user, skill_id, True)
    except SkillError as e:
        raise _http(e) from e


@router.post("/{skill_id}/disable")
async def disable_skill(
    skill_id: str,
    current_user: DeveloperDep,
    db: DbDep,
) -> dict[str, Any]:
    try:
        return await SkillService(db).set_enabled(current_user, skill_id, False)
    except SkillError as e:
        raise _http(e) from e


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: str,
    current_user: DeveloperDep,
    db: DbDep,
) -> dict[str, Any]:
    try:
        outcome = await SkillService(db).delete(current_user, skill_id)
    except SkillError as e:
        raise _http(e) from e
    return {"id": skill_id, "status": outcome}
