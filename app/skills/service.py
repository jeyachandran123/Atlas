"""
Skill business logic: visibility, ownership, install state, built-in seeding.

Rules:
  - system skills are read-only and enabled for everyone unless a user
    turns one off (a user_skill_settings row with enabled=false)
  - personal skills belong to their creator (an org admin may also edit/delete)
  - org skills are created/edited/deleted by org admins; members install them
  - "installed" = the user has a user_skill_settings row
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Skill, User, UserSkillSetting
from app.skills.package import SKILL_FILENAME, SkillPackage, build_package
from app.skills.parser import (
    ParsedSkill,
    checksum,
    instructions_of,
    parse_skill_md,
    render_skill_md,
)
from app.skills.repository import SkillRepository
from app.skills.router import SkillCandidate, SkillRouter, SkillSelection

BUILTIN_DIR = Path(__file__).parent / "builtin"
MAX_ACTIVE_LIMIT = 5


class SkillError(Exception):
    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SkillNotFoundError(SkillError):
    status_code = 404


class SkillForbiddenError(SkillError):
    status_code = 403


class SkillConflictError(SkillError):
    status_code = 409


@dataclass
class SkillPreferences:
    auto_select: bool
    max_active: int  # effective value
    max_active_override: int | None


def _json_list(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def _is_admin_of(user: User, org_id: str | None) -> bool:
    return user.role == "admin" and org_id is not None and user.org_id == org_id


def can_edit(user: User, skill: Skill) -> bool:
    if skill.scope == "system":
        return False
    if skill.scope == "personal":
        return skill.owner_user_id == user.id or _is_admin_of(user, skill.org_id)
    return _is_admin_of(user, skill.org_id)


def apply_package(skill: Skill, pkg: SkillPackage, repo: SkillRepository) -> None:
    p = pkg.skill
    skill.slug = p.name
    skill.display_name = p.display_name
    skill.description = p.description
    skill.icon = p.icon
    skill.version = p.version
    skill.body = p.raw
    skill.triggers_json = json.dumps(p.triggers)
    skill.modes_json = json.dumps(p.modes)
    skill.checksum = checksum(p.raw, pkg.files)
    repo.replace_files(skill, pkg.files)


def skill_view(skill: Skill, setting: UserSkillSetting | None, user: User) -> dict[str, Any]:
    system = skill.scope == "system"
    return {
        "id": skill.id,
        "slug": skill.slug,
        "name": skill.display_name,
        "display_name": skill.display_name,
        "description": skill.description,
        "icon": skill.icon,
        "version": skill.version,
        "scope": skill.scope,
        "source": skill.source,
        "source_ref": skill.source_ref,
        "triggers": _json_list(skill.triggers_json),
        "modes": _json_list(skill.modes_json),
        "installed": system or setting is not None,
        "enabled": (setting.enabled if setting else system),
        "pinned": bool(setting.pinned) if setting else False,
        "editable": can_edit(user, skill),
        "created_at": skill.created_at.isoformat() if skill.created_at else None,
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
    }


class SkillService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = SkillRepository(db)

    # ── Reads ────────────────────────────────────────────────────────────────

    async def list_for_user(
        self, user: User, scope: str | None = None, q: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        skills = await self.repo.list_visible(user.id, user.org_id, q)
        if scope:
            skills = [s for s in skills if s.scope == scope]
        settings = await self.repo.settings_for(user.id, [s.id for s in skills])
        out: dict[str, list[dict[str, Any]]] = {"installed": [], "system": [], "available": []}
        for s in skills:
            view = skill_view(s, settings.get(s.id), user)
            if s.scope == "system":
                out["system"].append(view)
            elif view["installed"]:
                out["installed"].append(view)
            else:
                out["available"].append(view)
        return out

    async def get_for_user(self, user: User, skill_id: str) -> Skill:
        skill = await self.repo.get_visible(skill_id, user.id, user.org_id)
        if skill is None:
            raise SkillNotFoundError("Skill not found")
        return skill

    async def detail(self, user: User, skill_id: str) -> dict[str, Any]:
        skill = await self.get_for_user(user, skill_id)
        setting = (await self.repo.settings_for(user.id, [skill.id])).get(skill.id)
        view = skill_view(skill, setting, user)
        view["body"] = skill.body
        view["instructions"] = instructions_of(skill.body)
        view["checksum"] = skill.checksum
        view["files"] = [
            {"path": f.path, "size": f.size, "content": f.content} for f in skill.files
        ]
        return view

    # ── Writes ───────────────────────────────────────────────────────────────

    async def create(
        self,
        user: User,
        pkg: SkillPackage,
        *,
        scope: str = "personal",
        source: str = "editor",
        source_ref: str | None = None,
    ) -> Skill:
        if scope not in ("personal", "org"):
            raise SkillError("scope must be 'personal' or 'org'")
        if scope == "org" and user.role != "admin":
            raise SkillForbiddenError("Only admins can create organization skills")
        owner = user.id if scope == "personal" else None
        if await self.repo.slug_taken(scope, pkg.skill.name, user.org_id, owner):
            raise SkillConflictError(f"A skill named '{pkg.skill.name}' already exists")
        skill = Skill(
            scope=scope,
            org_id=user.org_id,
            owner_user_id=owner,
            source=source,
            source_ref=source_ref[:1000] if source_ref else None,
            files=[],
        )
        apply_package(skill, pkg, self.repo)
        self.db.add(skill)
        await self.db.flush()
        await self.repo.upsert_setting(user.id, skill.id, enabled=True)  # creator installs it
        await self.db.commit()
        await self.db.refresh(skill)
        return skill

    async def update(self, user: User, skill_id: str, changes: dict[str, Any]) -> Skill:
        """`changes` holds either `skill_md` (full text) or editor fields
        (name, display_name, description, icon, version, triggers, modes,
        instructions) plus optional `files` (replaces all extra files)."""
        skill = await self.get_for_user(user, skill_id)
        if not can_edit(user, skill):
            raise SkillForbiddenError(
                "System skills are read-only"
                if skill.scope == "system"
                else "You can't edit this skill"
            )
        if changes.get("skill_md"):
            skill_md = str(changes["skill_md"])
        else:
            cur: ParsedSkill = parse_skill_md(skill.body)
            skill_md = render_skill_md(
                name=changes.get("name") or cur.name,
                description=changes.get("description") or cur.description,
                instructions=changes.get("instructions") or cur.instructions,
                display_name=changes.get("display_name") or cur.display_name,
                icon=changes.get("icon") or cur.icon,
                version=changes.get("version") or cur.version,
                triggers=cur.triggers if changes.get("triggers") is None else changes["triggers"],
                modes=cur.modes if changes.get("modes") is None else changes["modes"],
                extra=cur.extra,
            )
        files = changes.get("files")
        if files is None:
            files = {f.path: f.content for f in skill.files}
        pkg = build_package(skill_md, files)
        if pkg.skill.name != skill.slug and await self.repo.slug_taken(
            skill.scope, pkg.skill.name, skill.org_id, skill.owner_user_id, exclude_id=skill.id
        ):
            raise SkillConflictError(f"A skill named '{pkg.skill.name}' already exists")
        apply_package(skill, pkg, self.repo)
        await self.db.commit()
        await self.db.refresh(skill)
        return skill

    async def set_enabled(self, user: User, skill_id: str, enabled: bool) -> dict[str, Any]:
        skill = await self.get_for_user(user, skill_id)
        setting = await self.repo.upsert_setting(user.id, skill.id, enabled)
        await self.db.commit()
        return skill_view(skill, setting, user)

    async def delete(self, user: User, skill_id: str) -> str:
        """Returns 'deleted' (skill removed for everyone) or 'uninstalled'
        (only this user's install row removed — org skill, non-admin)."""
        skill = await self.get_for_user(user, skill_id)
        if skill.scope == "system":
            raise SkillForbiddenError("System skills can't be removed; disable them instead")
        if skill.scope == "org" and not _is_admin_of(user, skill.org_id):
            await self.repo.delete_setting(user.id, skill.id)
            await self.db.commit()
            return "uninstalled"
        if not can_edit(user, skill):
            raise SkillForbiddenError("You can't remove this skill")
        await self.db.delete(skill)
        await self.db.commit()
        return "deleted"

    # ── Preferences ──────────────────────────────────────────────────────────

    async def preferences(self, user_id: str) -> SkillPreferences:
        row = await self.repo.preferences(user_id)
        default_max = get_settings().skill_max_active
        override = row.max_active if row else None
        return SkillPreferences(
            auto_select=row.auto_select if row else True,
            max_active=default_max if override is None else override,
            max_active_override=override,
        )

    async def save_preferences(
        self, user_id: str, auto_select: bool, max_active: int | None
    ) -> SkillPreferences:
        if max_active is not None and not 0 <= max_active <= MAX_ACTIVE_LIMIT:
            raise SkillError(f"max_active must be between 0 and {MAX_ACTIVE_LIMIT}")
        await self.repo.save_preferences(user_id, auto_select, max_active)
        await self.db.commit()
        return await self.preferences(user_id)

    # ── Selection ────────────────────────────────────────────────────────────

    async def candidates(self, user_id: str, org_id: str) -> list[SkillCandidate]:
        """Skills a turn may use: system skills plus installed ones."""
        skills = await self.repo.list_visible(user_id, org_id)
        settings = await self.repo.settings_for(user_id, [s.id for s in skills])
        out: list[SkillCandidate] = []
        for s in skills:
            setting = settings.get(s.id)
            if s.scope != "system" and setting is None:
                continue  # visible org skill the user hasn't installed
            out.append(
                SkillCandidate(
                    id=s.id,
                    slug=s.slug,
                    display_name=s.display_name,
                    description=s.description,
                    instructions=instructions_of(s.body),
                    triggers=tuple(_json_list(s.triggers_json)),
                    modes=tuple(_json_list(s.modes_json)),
                    enabled=setting.enabled if setting else True,
                )
            )
        return out

    async def select(
        self,
        user_id: str,
        org_id: str,
        message: str,
        agent_mode: str = "auto",
        history: list[dict] | None = None,
        router: SkillRouter | None = None,
    ) -> SkillSelection:
        candidates = await self.candidates(user_id, org_id)
        if not candidates:
            return SkillSelection(message=message)
        prefs = await self.preferences(user_id)
        return (router or SkillRouter()).choose(
            candidates,
            message,
            agent_mode,
            history,
            auto_select=prefs.auto_select,
            max_active=prefs.max_active,
        )

    async def preview(self, user: User, message: str, agent_mode: str = "auto") -> dict[str, Any]:
        router = SkillRouter()
        candidates = await self.candidates(user.id, user.org_id)
        prefs = await self.preferences(user.id)
        selection = router.choose(
            candidates,
            message,
            agent_mode,
            auto_select=prefs.auto_select,
            max_active=prefs.max_active,
        )
        selected = {s.slug for s in selection.skills}
        scored = sorted(
            ((router.score(c, selection.message, agent_mode), c) for c in candidates),
            key=lambda sc: (-sc[0], sc[1].slug),
        )
        scores = [
            {
                "slug": c.slug,
                "name": c.display_name,
                "score": score,
                "enabled": c.enabled,
                "selected": c.slug in selected,
            }
            for score, c in scored
        ]
        return {
            "message": selection.message,
            "threshold": router.threshold,
            "skills": [
                {
                    "slug": s.slug,
                    "name": s.name,
                    "score": None if s.explicit else s.score,
                    "explicit": s.explicit,
                    "truncated": s.truncated,
                }
                for s in selection.skills
            ],
            "candidates": scores,
        }


# ── Built-in seeding ─────────────────────────────────────────────────────────


def load_builtin_packages(directory: Path = BUILTIN_DIR) -> list[SkillPackage]:
    packages: list[SkillPackage] = []
    for folder in sorted(p for p in directory.iterdir() if p.is_dir()):
        skill_md = folder / SKILL_FILENAME
        if not skill_md.is_file():
            continue
        files = {
            f.relative_to(folder).as_posix(): f.read_text(encoding="utf-8")
            for f in folder.rglob("*")
            if f.is_file() and f.name != SKILL_FILENAME and "__pycache__" not in f.parts
        }
        pkg = build_package(skill_md.read_text(encoding="utf-8"), files)
        if pkg.skill.name != folder.name:
            raise ValueError(
                f"Built-in skill folder '{folder.name}' must match name '{pkg.skill.name}'"
            )
        packages.append(pkg)
    return packages


async def seed_builtin_skills(db: AsyncSession, directory: Path = BUILTIN_DIR) -> dict[str, int]:
    """Idempotent: create missing, update changed (by checksum), remove
    built-ins no longer shipped. Never touches org/personal skills."""
    repo = SkillRepository(db)
    shipped = load_builtin_packages(directory)
    existing = {s.slug: s for s in await repo.system_skills()}
    counts = {"created": 0, "updated": 0, "removed": 0, "unchanged": 0}
    for pkg in shipped:
        cs = checksum(pkg.skill.raw, pkg.files)
        skill = existing.pop(pkg.skill.name, None)
        if skill is None:
            skill = Skill(scope="system", source="builtin", files=[])
            apply_package(skill, pkg, repo)
            db.add(skill)
            counts["created"] += 1
        elif skill.checksum != cs:
            apply_package(skill, pkg, repo)
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
    for stale in existing.values():
        if stale.source == "builtin":
            await db.delete(stale)
            counts["removed"] += 1
    await db.commit()
    logger.info(f"Built-in skills seeded: {counts}")
    return counts
