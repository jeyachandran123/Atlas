"""Data access for skills. Every user-facing query is scoped by visibility:
system skills, the user's org skills, and the user's own personal skills."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Select, and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    MessageCapability,
    Skill,
    SkillFile,
    UserSkillPreference,
    UserSkillSetting,
)


def _visible(user_id: str, org_id: str) -> Select[tuple[Skill]]:
    return select(Skill).where(
        or_(
            Skill.scope == "system",
            and_(Skill.scope == "org", Skill.org_id == org_id),
            and_(Skill.scope == "personal", Skill.owner_user_id == user_id),
        )
    )


class SkillRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Skills ───────────────────────────────────────────────────────────────

    async def list_visible(self, user_id: str, org_id: str, q: str | None = None) -> list[Skill]:
        stmt = _visible(user_id, org_id)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Skill.slug).like(like),
                    func.lower(Skill.display_name).like(like),
                    func.lower(Skill.description).like(like),
                )
            )
        result = await self.db.execute(stmt.order_by(Skill.display_name))
        return list(result.scalars().all())

    async def get_visible(self, skill_id: str, user_id: str, org_id: str) -> Skill | None:
        result = await self.db.execute(_visible(user_id, org_id).where(Skill.id == skill_id))
        return result.scalar_one_or_none()

    async def slug_taken(
        self,
        scope: str,
        slug: str,
        org_id: str | None,
        owner_user_id: str | None,
        exclude_id: str | None = None,
    ) -> bool:
        stmt = select(Skill.id).where(Skill.scope == scope, Skill.slug == slug)
        if scope == "org":
            stmt = stmt.where(Skill.org_id == org_id)
        elif scope == "personal":
            stmt = stmt.where(Skill.owner_user_id == owner_user_id)
        if exclude_id:
            stmt = stmt.where(Skill.id != exclude_id)
        return (await self.db.execute(stmt.limit(1))).first() is not None

    async def system_skills(self) -> list[Skill]:
        result = await self.db.execute(select(Skill).where(Skill.scope == "system"))
        return list(result.scalars().all())

    def replace_files(self, skill: Skill, files: dict[str, str]) -> None:
        skill.files.clear()
        for path in sorted(files):
            content = files[path]
            skill.files.append(
                SkillFile(path=path, content=content, size=len(content.encode("utf-8")))
            )

    # ── Per-user settings ────────────────────────────────────────────────────

    async def settings_for(
        self, user_id: str, skill_ids: Sequence[str] | None = None
    ) -> dict[str, UserSkillSetting]:
        stmt = select(UserSkillSetting).where(UserSkillSetting.user_id == user_id)
        if skill_ids is not None:
            if not skill_ids:
                return {}
            stmt = stmt.where(UserSkillSetting.skill_id.in_(list(skill_ids)))
        result = await self.db.execute(stmt)
        return {s.skill_id: s for s in result.scalars().all()}

    async def upsert_setting(self, user_id: str, skill_id: str, enabled: bool) -> UserSkillSetting:
        existing = (await self.settings_for(user_id, [skill_id])).get(skill_id)
        if existing:
            existing.enabled = enabled
            return existing
        row = UserSkillSetting(user_id=user_id, skill_id=skill_id, enabled=enabled)
        self.db.add(row)
        return row

    async def delete_setting(self, user_id: str, skill_id: str) -> None:
        await self.db.execute(
            delete(UserSkillSetting).where(
                UserSkillSetting.user_id == user_id, UserSkillSetting.skill_id == skill_id
            )
        )

    # ── Preferences ──────────────────────────────────────────────────────────

    async def preferences(self, user_id: str) -> UserSkillPreference | None:
        return await self.db.get(UserSkillPreference, user_id)

    async def save_preferences(
        self, user_id: str, auto_select: bool, max_active: int | None
    ) -> UserSkillPreference:
        row = await self.preferences(user_id)
        if row is None:
            row = UserSkillPreference(user_id=user_id)
            self.db.add(row)
        row.auto_select = auto_select
        row.max_active = max_active
        return row

    # ── Capability usage ─────────────────────────────────────────────────────

    def add_capabilities(
        self,
        refs: Sequence[dict[str, str]],
        kind: str,
        message_id: str | None = None,
        turn_id: str | None = None,
    ) -> None:
        for ref in refs:
            self.db.add(
                MessageCapability(
                    message_id=message_id,
                    turn_id=turn_id,
                    kind=kind,
                    ref=str(ref.get("slug") or ref.get("ref") or "")[:200],
                    label=str(ref.get("name") or ref.get("label") or "")[:200],
                )
            )

    async def capabilities_for_messages(
        self, message_ids: Sequence[str]
    ) -> dict[str, list[MessageCapability]]:
        if not message_ids:
            return {}
        result = await self.db.execute(
            select(MessageCapability)
            .where(MessageCapability.message_id.in_(list(message_ids)))
            .order_by(MessageCapability.created_at)
        )
        out: dict[str, list[MessageCapability]] = {}
        for row in result.scalars().all():
            out.setdefault(str(row.message_id), []).append(row)
        return out
