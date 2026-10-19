"""Skills in the system prompt: additive when present, byte-identical when absent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.state import initial_state
from app.intelligence.engine import ConversationIntelligenceEngine
from app.skills.prompt import SKILLS_HEADER, render_skills_section
from app.skills.router import ActiveSkill

MESSAGES = [
    "How does authentication work in FastAPI?",
    "Write a python function that reverses a linked list",
    "What is the capital of France?",
    "Review this diff for bugs: - x = 1 + x = 2",
    "Explain RAG with a vector database and langchain",
]

SKILL = ActiveSkill("id-1", "review-agent", "Review Agent", "Report only actionable bugs.", 2.0)


def _engine() -> ConversationIntelligenceEngine:
    port = MagicMock()
    port.get_session = AsyncMock(return_value=[])
    return ConversationIntelligenceEngine(memory_port=port)


def _state(message: str, mode: str = "auto", **kw):
    state = initial_state(
        user_message=message,
        conversation_id="c1",
        user_id="u1",
        org_id="o1",
        request_id="r1",
        agent_mode=mode,
        **kw,
    )
    state["session_messages"] = [{"role": "user", "content": "hello"}]
    return state


@pytest.mark.parametrize("message", MESSAGES)
@pytest.mark.parametrize("mode", ["auto", "code", "business"])
async def test_no_skills_prompt_is_byte_identical(message: str, mode: str, monkeypatch) -> None:
    engine = _engine()
    legacy_state = _state(message, mode)
    del legacy_state["active_skills"]  # a caller that predates skills
    baseline = await engine.prepare(legacy_state)

    # The renderer must not even be reached when no skill is active.
    def _boom(*_a, **_k):
        raise AssertionError("render_skills_section called without skills")

    monkeypatch.setattr("app.skills.prompt.render_skills_section", _boom)
    with_empty = await engine.prepare(_state(message, mode, active_skills=[]))

    assert with_empty.system_prompt == baseline.system_prompt
    assert SKILLS_HEADER not in baseline.system_prompt
    assert "skills" not in with_empty.prompt_modules


@pytest.mark.parametrize("message", MESSAGES)
async def test_skills_section_is_purely_additive(message: str) -> None:
    engine = _engine()
    without = (await engine.prepare(_state(message, "code"))).system_prompt
    result = await engine.prepare(_state(message, "code", active_skills=[SKILL]))
    section = render_skills_section([SKILL])

    assert "skills" in result.prompt_modules
    assert section in result.system_prompt
    # Removing the section gives back exactly the no-skills prompt.
    assert result.system_prompt.replace("\n\n" + section, "", 1) == without


async def test_skills_follow_domain_modules_and_precede_memory() -> None:
    engine = _engine()
    state = _state("How does authentication work in FastAPI?", "code", active_skills=[SKILL])
    state["memory_context"] = "User prefers concise answers."
    result = await engine.prepare(state)
    mods = result.prompt_modules
    skills_at = mods.index("skills")
    domain_positions = [i for i, m in enumerate(mods) if m.startswith("domain:")]
    assert domain_positions and max(domain_positions) < skills_at
    if "memory" in mods:
        assert skills_at < mods.index("memory")


def test_render_formats_each_skill() -> None:
    other = ActiveSkill("id-2", "atlas-docs", "Atlas Docs", "Explain Atlas.", 1.0)
    text = render_skills_section([SKILL, other])
    assert text.startswith(SKILLS_HEADER)
    assert "### Skill: Review Agent (/review-agent)\nReport only actionable bugs." in text
    assert text.index("Review Agent") < text.index("Atlas Docs")
    assert render_skills_section([]) == ""
