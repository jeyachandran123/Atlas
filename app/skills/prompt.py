"""Render active skills as a system-prompt section. Pure formatting — the
budget was already applied by SkillRouter.fit_budget, so what renders here
is exactly what was reported as used."""

from __future__ import annotations

from collections.abc import Sequence

from app.skills.router import ActiveSkill

SKILLS_HEADER = (
    "## ACTIVE SKILLS\n"
    "The skills below were selected for this request. Follow their instructions "
    "where they apply. Skills refine HOW you answer; they never override safety "
    "rules, policy, or any rule stated above them."
)


def render_skills_section(skills: Sequence[ActiveSkill]) -> str:
    if not skills:
        return ""
    blocks = [SKILLS_HEADER]
    for s in skills:
        blocks.append(f"### Skill: {s.name} (/{s.slug})\n{s.instructions.strip()}")
    return "\n\n".join(blocks)
