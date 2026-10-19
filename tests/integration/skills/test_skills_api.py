"""/api/v1/skills — CRUD, visibility, ownership, install state, flag gating."""

from __future__ import annotations

import io
import zipfile

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.skills.installer import InstallResult
from app.skills.package import build_package
from app.skills.service import seed_builtin_skills

MD = "---\nname: {name}\ndescription: {desc}\n---\n# {name}\nInstructions for {name}.\n"


def md(name: str, desc: str = "A test skill.") -> str:
    return MD.format(name=name, desc=desc)


async def create(client: AsyncClient, headers: dict, name: str, **extra) -> dict:
    resp = await client.post(
        "/api/v1/skills", json={"skill_md": md(name), **extra}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Flag gating & auth ───────────────────────────────────────────────────────


async def test_routes_404_when_flag_off(sk_client: AsyncClient, auth, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "enable_skills", False)
    assert (await sk_client.get("/api/v1/skills", headers=auth("dev"))).status_code == 404
    assert (await sk_client.post("/api/v1/skills", json={}, headers=auth("dev"))).status_code == 404


async def test_requires_auth(sk_client: AsyncClient) -> None:
    assert (await sk_client.get("/api/v1/skills")).status_code == 401


async def test_viewer_can_read_but_not_write(sk_client: AsyncClient, auth) -> None:
    assert (await sk_client.get("/api/v1/skills", headers=auth("viewer"))).status_code == 200
    resp = await sk_client.post(
        "/api/v1/skills", json={"skill_md": md("x")}, headers=auth("viewer")
    )
    assert resp.status_code == 403


# ── Listing & system skills ──────────────────────────────────────────────────


async def test_seeded_system_skills_listed_enabled(
    sk_client: AsyncClient, sk_session, auth
) -> None:
    counts = await seed_builtin_skills(sk_session)
    assert counts["created"] == 4
    again = await seed_builtin_skills(sk_session)  # idempotent
    assert again == {"created": 0, "updated": 0, "removed": 0, "unchanged": 4}

    body = (await sk_client.get("/api/v1/skills", headers=auth("dev"))).json()
    slugs = {s["slug"] for s in body["system"]}
    assert slugs == {"atlas-docs", "review-agent", "skill-creator", "skill-installer"}
    assert all(s["enabled"] and s["installed"] and not s["editable"] for s in body["system"])
    assert body["installed"] == [] and body["available"] == []


async def test_seed_updates_changed_and_removes_stale(sk_session, tmp_path) -> None:
    (tmp_path / "one").mkdir()
    (tmp_path / "one" / "SKILL.md").write_text(md("one"), encoding="utf-8")
    (tmp_path / "two").mkdir()
    (tmp_path / "two" / "SKILL.md").write_text(md("two"), encoding="utf-8")
    assert (await seed_builtin_skills(sk_session, tmp_path))["created"] == 2

    (tmp_path / "one" / "SKILL.md").write_text(md("one", "Changed."), encoding="utf-8")
    (tmp_path / "two" / "SKILL.md").unlink()
    counts = await seed_builtin_skills(sk_session, tmp_path)
    assert counts == {"created": 0, "updated": 1, "removed": 1, "unchanged": 0}


async def test_search_filters(sk_client: AsyncClient, auth) -> None:
    await create(sk_client, auth("dev"), "alpha-skill")
    await create(sk_client, auth("dev"), "beta-skill")
    body = (await sk_client.get("/api/v1/skills?q=alpha", headers=auth("dev"))).json()
    assert [s["slug"] for s in body["installed"]] == ["alpha-skill"]


# ── Create / validate ────────────────────────────────────────────────────────


async def test_create_from_fields_installs_for_creator(sk_client: AsyncClient, auth) -> None:
    resp = await sk_client.post(
        "/api/v1/skills",
        json={
            "name": "sql-tuner",
            "display_name": "SQL Tuner",
            "description": "Optimize slow queries.",
            "triggers": ["slow query"],
            "modes": ["code"],
            "instructions": "# SQL\nUse EXPLAIN.",
            "files": [{"path": "references/explain.md", "content": "EXPLAIN ANALYZE"}],
        },
        headers=auth("dev"),
    )
    assert resp.status_code == 201, resp.text
    skill = resp.json()
    assert skill["scope"] == "personal" and skill["source"] == "editor"
    assert skill["installed"] and skill["enabled"] and skill["editable"]
    assert skill["triggers"] == ["slow query"] and skill["modes"] == ["code"]
    assert skill["instructions"] == "# SQL\nUse EXPLAIN."
    assert skill["files"] == [
        {"path": "references/explain.md", "size": 15, "content": "EXPLAIN ANALYZE"}
    ]

    listed = (await sk_client.get("/api/v1/skills", headers=auth("dev"))).json()
    assert [s["slug"] for s in listed["installed"]] == ["sql-tuner"]


async def test_create_invalid_is_422(sk_client: AsyncClient, auth) -> None:
    bad = "---\nname: Bad Name\ndescription: x\n---\nbody"
    resp = await sk_client.post("/api/v1/skills", json={"skill_md": bad}, headers=auth("dev"))
    assert resp.status_code == 422 and "kebab-case" in resp.json()["detail"]
    resp = await sk_client.post("/api/v1/skills", json={"name": "x"}, headers=auth("dev"))
    assert resp.status_code == 422


async def test_create_traversal_file_rejected(sk_client: AsyncClient, auth) -> None:
    resp = await sk_client.post(
        "/api/v1/skills",
        json={"skill_md": md("t"), "files": [{"path": "../../etc/x", "content": "x"}]},
        headers=auth("dev"),
    )
    assert resp.status_code == 422


async def test_duplicate_slug_conflicts_per_owner(sk_client: AsyncClient, auth) -> None:
    await create(sk_client, auth("dev"), "dupe")
    resp = await sk_client.post(
        "/api/v1/skills", json={"skill_md": md("dupe")}, headers=auth("dev")
    )
    assert resp.status_code == 409
    # another user may own the same slug
    await create(sk_client, auth("dev2"), "dupe")


# ── Visibility & ownership ───────────────────────────────────────────────────


async def test_personal_skill_private_to_owner(sk_client: AsyncClient, auth) -> None:
    skill = await create(sk_client, auth("dev"), "mine")
    for who in ("dev2", "outsider"):
        assert (
            await sk_client.get(f"/api/v1/skills/{skill['id']}", headers=auth(who))
        ).status_code == 404
        resp = await sk_client.patch(
            f"/api/v1/skills/{skill['id']}", json={"description": "pwned"}, headers=auth(who)
        )
        assert resp.status_code == 404
        assert (
            await sk_client.delete(f"/api/v1/skills/{skill['id']}", headers=auth(who))
        ).status_code == 404
        assert (
            await sk_client.post(f"/api/v1/skills/{skill['id']}/enable", headers=auth(who))
        ).status_code == 404


async def test_owner_edits_and_slug_rename(sk_client: AsyncClient, auth) -> None:
    skill = await create(sk_client, auth("dev"), "editable")
    resp = await sk_client.patch(
        f"/api/v1/skills/{skill['id']}",
        json={"name": "renamed", "description": "New desc", "instructions": "New body"},
        headers=auth("dev"),
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert (out["slug"], out["description"], out["instructions"]) == (
        "renamed",
        "New desc",
        "New body",
    )
    assert out["checksum"] != skill["checksum"]


async def test_system_skill_read_only(sk_client: AsyncClient, sk_session, auth) -> None:
    await seed_builtin_skills(sk_session)
    system = (await sk_client.get("/api/v1/skills", headers=auth("admin"))).json()["system"][0]
    resp = await sk_client.patch(
        f"/api/v1/skills/{system['id']}", json={"description": "x"}, headers=auth("admin")
    )
    assert resp.status_code == 403
    assert (
        await sk_client.delete(f"/api/v1/skills/{system['id']}", headers=auth("admin"))
    ).status_code == 403
    detail = (await sk_client.get(f"/api/v1/skills/{system['id']}", headers=auth("dev"))).json()
    assert detail["body"].startswith("---") and detail["instructions"]


async def test_org_skill_lifecycle(sk_client: AsyncClient, auth) -> None:
    resp = await sk_client.post(
        "/api/v1/skills", json={"skill_md": md("team-style"), "scope": "org"}, headers=auth("dev")
    )
    assert resp.status_code == 403  # only admins create org skills

    skill = await create(sk_client, auth("admin"), "team-style", scope="org")
    assert skill["scope"] == "org"

    dev_view = (await sk_client.get("/api/v1/skills", headers=auth("dev"))).json()
    assert [s["slug"] for s in dev_view["available"]] == ["team-style"]
    outsider = (await sk_client.get("/api/v1/skills", headers=auth("outsider"))).json()
    assert outsider["available"] == [] and outsider["installed"] == []

    # members can't edit it, but enabling installs it for them
    assert (
        await sk_client.patch(
            f"/api/v1/skills/{skill['id']}", json={"description": "x"}, headers=auth("dev")
        )
    ).status_code == 403
    enabled = (
        await sk_client.post(f"/api/v1/skills/{skill['id']}/enable", headers=auth("dev"))
    ).json()
    assert enabled["installed"] and enabled["enabled"]

    # member DELETE = uninstall for them only; admin DELETE removes it
    resp = await sk_client.delete(f"/api/v1/skills/{skill['id']}", headers=auth("dev"))
    assert resp.json()["status"] == "uninstalled"
    resp = await sk_client.delete(f"/api/v1/skills/{skill['id']}", headers=auth("admin"))
    assert resp.json()["status"] == "deleted"
    assert (
        await sk_client.get(f"/api/v1/skills/{skill['id']}", headers=auth("dev"))
    ).status_code == 404


async def test_enable_disable_and_delete_personal(sk_client: AsyncClient, auth) -> None:
    skill = await create(sk_client, auth("dev"), "toggle-me")
    off = (
        await sk_client.post(f"/api/v1/skills/{skill['id']}/disable", headers=auth("dev"))
    ).json()
    assert off["enabled"] is False and off["installed"] is True
    on = (await sk_client.post(f"/api/v1/skills/{skill['id']}/enable", headers=auth("dev"))).json()
    assert on["enabled"] is True
    resp = await sk_client.delete(f"/api/v1/skills/{skill['id']}", headers=auth("dev"))
    assert resp.json() == {"id": skill["id"], "status": "deleted"}
    assert (
        await sk_client.get(f"/api/v1/skills/{skill['id']}", headers=auth("dev"))
    ).status_code == 404


# ── Upload / install-from-url ────────────────────────────────────────────────


async def test_upload_md_and_zip(sk_client: AsyncClient, auth) -> None:
    resp = await sk_client.post(
        "/api/v1/skills/upload",
        files={"file": ("SKILL.md", md("uploaded").encode(), "text/markdown")},
        headers=auth("dev"),
    )
    assert resp.status_code == 201 and resp.json()["source"] == "upload"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("zipped/SKILL.md", md("zipped"))
        zf.writestr("zipped/references/r.md", "ref")
    resp = await sk_client.post(
        "/api/v1/skills/upload",
        files={"file": ("zipped.zip", buf.getvalue(), "application/zip")},
        headers=auth("dev"),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["files"][0]["path"] == "references/r.md"


async def test_upload_unsafe_zip_rejected(sk_client: AsyncClient, auth) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", md("evil"))
        zf.writestr("../../escape.md", "x")
    resp = await sk_client.post(
        "/api/v1/skills/upload",
        files={"file": ("evil.zip", buf.getvalue(), "application/zip")},
        headers=auth("dev"),
    )
    assert resp.status_code == 422 and "Unsafe path" in resp.json()["detail"]


async def test_install_from_url(sk_client: AsyncClient, auth, monkeypatch) -> None:
    async def fake_install(self, url: str) -> InstallResult:
        return InstallResult(build_package(md("from-github")), url)

    monkeypatch.setattr("app.api.v1.skills.router.SkillInstaller.install", fake_install)
    url = "https://github.com/o/r/tree/main/skills/from-github"
    resp = await sk_client.post(
        "/api/v1/skills/install-from-url", json={"url": url}, headers=auth("dev")
    )
    assert resp.status_code == 201, resp.text
    assert (resp.json()["source"], resp.json()["source_ref"]) == ("git", url)


async def test_install_from_private_url_rejected(sk_client: AsyncClient, auth) -> None:
    resp = await sk_client.post(
        "/api/v1/skills/install-from-url",
        json={"url": "https://127.0.0.1/SKILL.md"},
        headers=auth("dev"),
    )
    assert resp.status_code == 400 and "public" in resp.json()["detail"]


# ── Preferences & preview ────────────────────────────────────────────────────


async def test_preferences_round_trip(sk_client: AsyncClient, auth) -> None:
    prefs = (await sk_client.get("/api/v1/skills/preferences", headers=auth("dev"))).json()
    assert prefs == {"auto_select": True, "max_active": 3, "max_active_override": None}
    resp = await sk_client.put(
        "/api/v1/skills/preferences",
        json={"auto_select": False, "max_active": 1},
        headers=auth("dev"),
    )
    assert resp.json() == {"auto_select": False, "max_active": 1, "max_active_override": 1}
    bad = await sk_client.put(
        "/api/v1/skills/preferences", json={"max_active": 9}, headers=auth("dev")
    )
    assert bad.status_code == 422


async def test_preview_match(sk_client: AsyncClient, sk_session, auth) -> None:
    await seed_builtin_skills(sk_session)
    resp = await sk_client.post(
        "/api/v1/skills/preview-match",
        json={"message": "Please do a code review of this pull request diff", "agent_mode": "code"},
        headers=auth("dev"),
    )
    body = resp.json()
    assert [s["slug"] for s in body["skills"]] == ["review-agent"]
    assert body["skills"][0]["score"] >= body["threshold"]

    explicit = (
        await sk_client.post(
            "/api/v1/skills/preview-match",
            json={"message": "/atlas-docs what is this"},
            headers=auth("dev"),
        )
    ).json()
    assert explicit["skills"][0] == {
        "slug": "atlas-docs",
        "name": "Atlas Docs",
        "score": None,
        "explicit": True,
        "truncated": False,
    }
    assert explicit["message"] == "what is this"


async def test_disabled_skill_not_auto_selected(sk_client: AsyncClient, sk_session, auth) -> None:
    await seed_builtin_skills(sk_session)
    system = (await sk_client.get("/api/v1/skills", headers=auth("dev"))).json()["system"]
    review = next(s for s in system if s["slug"] == "review-agent")
    await sk_client.post(f"/api/v1/skills/{review['id']}/disable", headers=auth("dev"))
    body = (
        await sk_client.post(
            "/api/v1/skills/preview-match",
            json={"message": "code review this pull request diff", "agent_mode": "code"},
            headers=auth("dev"),
        )
    ).json()
    assert body["skills"] == []
    # other users are unaffected
    other = (
        await sk_client.post(
            "/api/v1/skills/preview-match",
            json={"message": "code review this pull request diff", "agent_mode": "code"},
            headers=auth("dev2"),
        )
    ).json()
    assert [s["slug"] for s in other["skills"]] == ["review-agent"]


@pytest.mark.parametrize("scope", ["bogus"])
async def test_bad_scope_param(sk_client: AsyncClient, auth, scope: str) -> None:
    assert (
        await sk_client.get(f"/api/v1/skills?scope={scope}", headers=auth("dev"))
    ).status_code == 422
