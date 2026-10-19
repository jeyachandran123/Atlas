"""Request/response models for /api/v1/skills."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SkillFileIn(BaseModel):
    path: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., max_length=2 * 1024 * 1024)


class SkillCreateIn(BaseModel):
    """Either `skill_md` (a complete SKILL.md) or the editor fields."""

    skill_md: str | None = Field(default=None, max_length=50 * 1024)
    name: str | None = Field(default=None, max_length=64)
    display_name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=1024)
    icon: str | None = Field(default=None, max_length=40)
    version: str | None = Field(default=None, max_length=32)
    triggers: list[str] | None = None
    modes: list[str] | None = None
    instructions: str | None = Field(default=None, max_length=50 * 1024)
    files: list[SkillFileIn] | None = None
    scope: Literal["personal", "org"] = "personal"


class SkillUpdateIn(BaseModel):
    skill_md: str | None = Field(default=None, max_length=50 * 1024)
    name: str | None = Field(default=None, max_length=64)
    display_name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=1024)
    icon: str | None = Field(default=None, max_length=40)
    version: str | None = Field(default=None, max_length=32)
    triggers: list[str] | None = None
    modes: list[str] | None = None
    instructions: str | None = Field(default=None, max_length=50 * 1024)
    files: list[SkillFileIn] | None = None


class InstallFromUrlIn(BaseModel):
    url: str = Field(..., min_length=8, max_length=2000)
    scope: Literal["personal", "org"] = "personal"


class PreviewMatchIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=100000)
    agent_mode: str = Field(default="auto")


class SkillPreferencesIn(BaseModel):
    auto_select: bool = True
    max_active: int | None = Field(default=None, ge=0, le=5)


class SkillPreferencesOut(BaseModel):
    auto_select: bool
    max_active: int
    max_active_override: int | None = None
