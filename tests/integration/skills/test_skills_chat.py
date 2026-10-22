"""Skills on every chat path: /chat/stream, /chat/message, /chat/stream/vision,
the document follow-up path, and the workspace gateway."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.db.models import MessageCapability
from app.skills.prompt import SKILLS_HEADER
from app.skills.service import seed_builtin_skills


def parse_sse(text: str) -> list[dict[str, Any]]:
    """Content events only: the leading `meta` envelope that every chat stream
    opens with (conversation + user message ids) is not part of the answer."""
    events = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    return [e for e in events if e.get("type") != "meta"]


@pytest.fixture(autouse=True)
def no_documents(monkeypatch) -> None:
    async def _none(db, conversation_id):  # noqa: ANN001
        return False

    monkeypatch.setattr("app.api.v1.chat.router._ensure_document_context", _none)


@pytest.fixture(autouse=True)
def brain_off(monkeypatch) -> None:
    """The orchestrator path, whatever COGNITIVE_BRAIN_ENABLED is in .env."""
    monkeypatch.setattr("app.cognitive_integration.cognitive_brain_enabled", lambda: False)


async def stream(
    client: AsyncClient, headers: dict, message: str, mode: str = "auto"
) -> list[dict]:
    resp = await client.post(
        "/api/v1/chat/stream", json={"message": message, "agent_mode": mode}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return parse_sse(resp.text)


# ── /chat/stream ─────────────────────────────────────────────────────────────


async def test_stream_without_skills_is_unchanged(sk_client: AsyncClient, auth, fake_llm) -> None:
    events = await stream(sk_client, auth("dev"), "How does authentication work?")
    assert [e["type"] for e in events] == ["token", "token", "token", "done"]
    assert "skills" not in events[-1]
    assert SKILLS_HEADER not in fake_llm.calls[0]["system_prompt"]


async def test_stream_explicit_skill(sk_client: AsyncClient, sk_session, auth, fake_llm) -> None:
    await seed_builtin_skills(sk_session)
    events = await stream(sk_client, auth("dev"), "/review-agent check def f(): return 1", "code")

    assert events[0] == {
        "type": "capabilities",
        "skills": [{"slug": "review-agent", "name": "Review Agent"}],
    }
    assert events[1]["type"] == "token"
    done = events[-1]
    assert done["type"] == "done" and done["skills"] == [
        {"slug": "review-agent", "name": "Review Agent"}
    ]

    call = fake_llm.calls[0]
    assert SKILLS_HEADER in call["system_prompt"]
    assert "### Skill: Review Agent (/review-agent)" in call["system_prompt"]
    assert "/review-agent" not in call["prompt"]  # token stripped from what the model sees
    assert "check def f(): return 1" in call["prompt"]

    rows = (await sk_session.execute(select(MessageCapability))).scalars().all()
    assert [(r.message_id, r.kind, r.ref, r.label) for r in rows] == [
        (done["message_id"], "skill", "review-agent", "Review Agent")
    ]

    # Reload: history carries the capability on the assistant message
    msgs = (
        await sk_client.get(
            f"/api/v1/chat/conversations/{done['conversation_id']}/messages", headers=auth("dev")
        )
    ).json()
    assistant = next(m for m in msgs if m["role"] == "assistant")
    user = next(m for m in msgs if m["role"] == "user")
    assert assistant["capabilities"] == [
        {"kind": "skill", "ref": "review-agent", "label": "Review Agent"}
    ]
    assert user["capabilities"] == []
    assert user["content"] == "/review-agent check def f(): return 1"  # stored as typed


async def test_stream_auto_selected_skill(
    sk_client: AsyncClient, sk_session, auth, fake_llm
) -> None:
    await seed_builtin_skills(sk_session)
    events = await stream(
        sk_client, auth("dev"), "Please code review this pull request diff", "code"
    )
    assert events[0]["type"] == "capabilities"
    assert events[0]["skills"][0]["slug"] == "review-agent"


async def test_stream_flag_off_ignores_skills(
    sk_client: AsyncClient, sk_session, auth, fake_llm, monkeypatch
) -> None:
    await seed_builtin_skills(sk_session)
    monkeypatch.setattr(get_settings(), "enable_skills", False)
    events = await stream(sk_client, auth("dev"), "/review-agent check this")
    assert [e["type"] for e in events] == ["token", "token", "token", "done"]
    assert "skills" not in events[-1]
    assert SKILLS_HEADER not in fake_llm.calls[0]["system_prompt"]
    assert "/review-agent check this" in fake_llm.calls[0]["prompt"]  # not stripped


async def test_selection_failure_never_breaks_chat(
    sk_client: AsyncClient, sk_session, auth, fake_llm, monkeypatch
) -> None:
    await seed_builtin_skills(sk_session)

    async def boom(*a, **k):
        raise RuntimeError("db exploded")

    monkeypatch.setattr("app.skills.service.SkillService.select", boom)
    events = await stream(sk_client, auth("dev"), "/review-agent check this")
    assert events[-1]["type"] == "done" and "skills" not in events[-1]


# ── /chat/stream through the Cognitive OS ────────────────────────────────────


@pytest.fixture
def brain(monkeypatch) -> dict[str, Any]:
    """Brain on, with deliberation and the streaming client faked."""
    from app.cognitive_integration import Deliberation

    seen: dict[str, Any] = {"escalate": False}

    async def deliberate(message, **kw):  # noqa: ANN001
        seen["deliberated"] = message
        held = seen["escalate"]
        return Deliberation(
            authorized=not held, escalated=held, decision="hold" if held else "answer",
            intent="q", confidence=0.9, system_prompt="BRAIN RULES",
            user_prompt=message, hold_message="Held for review." if held else None,
        )

    class FakeClient:
        async def chat_stream(self, prompt, **kw):  # noqa: ANN001
            seen["system_prompt"] = kw["system_prompt"]
            for chunk in ["BRAIN ", "ANSWER"]:
                yield chunk

    async def no_web(*a, **k):  # noqa: ANN002, ANN003
        return None

    monkeypatch.setattr("app.cognitive_integration.cognitive_brain_enabled", lambda: True)
    monkeypatch.setattr("app.cognitive_integration.service.deliberate_turn", deliberate)
    monkeypatch.setattr("app.ollama_client.get_ollama_client", lambda: FakeClient())
    monkeypatch.setattr("app.api.v1.chat.router._web_events", no_web)
    return seen


async def test_brain_stream_uses_skills(
    sk_client: AsyncClient, sk_session, auth, brain
) -> None:
    await seed_builtin_skills(sk_session)
    events = await stream(sk_client, auth("dev"), "/review-agent check def f(): return 1")

    assert events[0] == {
        "type": "capabilities",
        "skills": [{"slug": "review-agent", "name": "Review Agent"}],
    }
    done = events[-1]
    assert done["type"] == "done" and done["brain"] is True
    assert done["skills"] == [{"slug": "review-agent", "name": "Review Agent"}]
    assert brain["deliberated"] == "check def f(): return 1"  # token stripped
    system = brain["system_prompt"]
    assert system.startswith("BRAIN RULES")  # the brain's rules stay above skills
    assert "### Skill: Review Agent (/review-agent)" in system

    rows = (await sk_session.execute(select(MessageCapability))).scalars().all()
    assert [(r.message_id, r.ref) for r in rows] == [(done["message_id"], "review-agent")]


async def test_brain_held_turn_reports_no_skills(
    sk_client: AsyncClient, sk_session, auth, brain
) -> None:
    await seed_builtin_skills(sk_session)
    brain["escalate"] = True
    events = await stream(sk_client, auth("dev"), "/review-agent check this")

    assert "capabilities" not in [e["type"] for e in events]
    assert events[-1]["escalated"] is True and "skills" not in events[-1]
    assert (await sk_session.execute(select(MessageCapability))).scalars().all() == []


async def test_skills_picked_in_the_composer_are_used_for_that_message(
    sk_client: AsyncClient, sk_session, auth, fake_llm
) -> None:
    await seed_builtin_skills(sk_session)
    resp = await sk_client.post(
        "/api/v1/chat/stream",
        json={"message": "How does authentication work?", "agent_mode": "auto", "skills": ["atlas-docs"]},
        headers=auth("dev"),
    )
    events = parse_sse(resp.text)
    assert events[0] == {"type": "capabilities", "skills": [{"slug": "atlas-docs", "name": "Atlas Docs"}]}
    assert events[-1]["skills"] == [{"slug": "atlas-docs", "name": "Atlas Docs"}]
    assert "### Skill: Atlas Docs (/atlas-docs)" in fake_llm.calls[0]["system_prompt"]
    assert "How does authentication work?" in fake_llm.calls[0]["prompt"]       # the message is untouched


async def test_a_picked_skill_that_is_switched_off_still_works_and_others_do_not_sneak_in(
    sk_client: AsyncClient, sk_session, auth, fake_llm
) -> None:
    await seed_builtin_skills(sk_session)
    listing = (await sk_client.get("/api/v1/skills", headers=auth("dev"))).json()
    docs_id = next(s["id"] for s in listing["system"] if s["slug"] == "atlas-docs")
    await sk_client.post(f"/api/v1/skills/{docs_id}/disable", headers=auth("dev"))
    resp = await sk_client.post(
        "/api/v1/chat/stream",
        json={"message": "Please do a code review of this pull request diff", "agent_mode": "code",
              "skills": ["atlas-docs"]},
        headers=auth("dev"),
    )
    system = fake_llm.calls[0]["system_prompt"]
    assert "### Skill: Atlas Docs" in system and "Review Agent" not in system   # review-agent would auto-match
    assert parse_sse(resp.text)[-1]["type"] == "done"


async def test_too_many_picked_skills_are_refused(sk_client: AsyncClient, auth) -> None:
    resp = await sk_client.post(
        "/api/v1/chat/stream",
        json={"message": "hi", "skills": ["a", "b", "c", "d", "e", "f"]},
        headers=auth("dev"),
    )
    assert resp.status_code == 422


# ── /chat/message ────────────────────────────────────────────────────────────


async def test_message_endpoint_reports_skills(
    sk_client: AsyncClient, sk_session, auth, fake_llm
) -> None:
    await seed_builtin_skills(sk_session)
    resp = await sk_client.post(
        "/api/v1/chat/message",
        json={"message": "@atlas-docs how do workspaces work?"},
        headers=auth("dev"),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["skills"] == [{"slug": "atlas-docs", "name": "Atlas Docs"}]

    plain = (
        await sk_client.post(
            "/api/v1/chat/message",
            json={"message": "What is 2 + 2?"},
            headers=auth("dev"),
        )
    ).json()
    assert plain["skills"] == []


# ── /chat/stream/vision (text branch) ────────────────────────────────────────


async def test_vision_text_branch_uses_skills(
    sk_client: AsyncClient, sk_session, auth, fake_llm
) -> None:
    await seed_builtin_skills(sk_session)
    resp = await sk_client.post(
        "/api/v1/chat/stream/vision",
        data={"message": "/review-agent look at this", "agent_mode": "code"},
        headers=auth("dev"),
    )
    events = parse_sse(resp.text)
    assert events[0]["type"] == "capabilities"
    assert events[-1]["skills"] == [{"slug": "review-agent", "name": "Review Agent"}]
    assert SKILLS_HEADER in fake_llm.calls[0]["system_prompt"]


# ── Document follow-up path ──────────────────────────────────────────────────


async def test_document_path_uses_skills(
    sk_client: AsyncClient, sk_session, auth, monkeypatch
) -> None:
    await seed_builtin_skills(sk_session)
    captured: dict[str, Any] = {}

    class FakeDocs:
        async def chat_stream(self, **kwargs: Any):
            captured.update(kwargs)
            yield "doc answer"

    async def has_docs(db, conversation_id):  # noqa: ANN001
        return True

    port = MagicMock()
    port.get_session = AsyncMock(return_value=[])
    from app.intelligence.engine import ConversationIntelligenceEngine

    engine = ConversationIntelligenceEngine(memory_port=port)
    monkeypatch.setattr("app.api.v1.chat.router._ensure_document_context", has_docs)
    monkeypatch.setattr("app.api.v1.chat.router.get_document_service", lambda: FakeDocs())
    monkeypatch.setattr("app.intelligence.engine.get_engine", lambda: engine)

    events = await stream(sk_client, auth("dev"), "/review-agent summarise the attached file")
    assert events[0]["type"] == "capabilities"
    assert events[-1]["skills"][0]["slug"] == "review-agent"
    assert SKILLS_HEADER in captured["system_prompt"]
    assert captured["message"] == "summarise the attached file"


# ── Workspace gateway ────────────────────────────────────────────────────────


def _gateway(prompt_seen: list):
    """A ConversationGateway with every collaborator faked except ask_stream."""
    from app.document_platform.conversation.gateway import ConversationGateway, TurnResult
    from app.document_platform.conversation.prompts import StructuredPrompt
    from app.document_platform.conversation.streaming import StreamingEngine

    gw = object.__new__(ConversationGateway)
    gw._db = AsyncMock()
    gw._repo = MagicMock()
    gw._repo.create_turn = AsyncMock(return_value=SimpleNamespace(id="t1", correlation_id="corr"))
    gw._streaming = StreamingEngine()
    gw._publish = AsyncMock()
    gw._persist = AsyncMock()

    async def prepare(ctx, collector):  # noqa: ANN001
        prompt_seen.append(("question", ctx.question))
        yield "prepared", (StructuredPrompt(system="GROUNDED RULES", user="Q", strategy="g"), None)

    gw._prepare_events = prepare

    # The gateway generates and validates the whole answer before streaming it,
    # so the prompt is captured at that seam rather than at a provider stream.
    async def answer_and_validate(ctx, prompt, bundle, collector):  # noqa: ANN001
        prompt_seen.append(("system", prompt.system))
        return TurnResult(
            turn_id="t1",
            conversation_id="c1",
            correlation_id="corr",
            status="completed",
            intent="q",
            answer="answer",
            grounded=True,
            grounding_score=0.9,
            refusal_reason=None,
        )

    gw._reasoning = MagicMock()
    gw._reasoning.provider.model_name = "m"
    gw._answer_and_validate = answer_and_validate
    return gw


def _frames(raw: list[str]) -> list[tuple[str, dict]]:
    out = []
    for frame in raw:
        lines = dict(line.split(": ", 1) for line in frame.strip().split("\n") if ": " in line)
        out.append((lines.get("event", ""), json.loads(lines.get("data", "{}"))))
    return out


async def test_workspace_gateway_without_skills_unchanged() -> None:
    seen: list = []
    conv = SimpleNamespace(id="c1", user_id="u1", org_id="o1")
    frames = _frames([f async for f in _gateway(seen).ask_stream(conv, "What is X?", None)])
    names = [n for n, _ in frames]
    assert "capabilities" not in names
    assert ("system", "GROUNDED RULES") in seen and ("question", "What is X?") in seen
    assert "skills" not in frames[-1][1]


async def test_workspace_gateway_injects_skills(monkeypatch) -> None:
    from app.skills.router import ActiveSkill, SkillSelection

    recorded: list = []

    async def fake_record(db, refs, **kw):  # noqa: ANN001
        recorded.append((refs, kw))

    monkeypatch.setattr("app.skills.chat.record_skill_usage", fake_record)
    seen: list = []
    conv = SimpleNamespace(id="c1", user_id="u1", org_id="o1")
    sel = SkillSelection(
        message="What is X?",
        skills=[ActiveSkill("s1", "review-agent", "Review Agent", "Be terse.", 2.0)],
    )
    frames = _frames(
        [
            f
            async for f in _gateway(seen).ask_stream(
                conv, "/review-agent What is X?", None, skills=sel
            )
        ]
    )
    names = [n for n, _ in frames]
    assert names.index("capabilities") < names.index("token")
    system = dict(seen)["system"]
    assert system.startswith("GROUNDED RULES") and "### Skill: Review Agent" in system
    assert dict(seen)["question"] == "What is X?"
    assert frames[-1][1]["skills"] == [{"slug": "review-agent", "name": "Review Agent"}]
    assert recorded == [([{"slug": "review-agent", "name": "Review Agent"}], {"turn_id": "t1"})]
