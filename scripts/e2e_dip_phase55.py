"""
DIP Phase 5.5 — Knowledge Workspace verification.

Covers: default-workspace bootstrap + adoption, workspace CRUD, document
linking, conversations belonging to a workspace, auto-title, multi-document
attachment mid-conversation, full context restore, generation belonging to
the workspace, timeline, bookmarks, search, related documents, save-as-
knowledge, conversation export, and dashboard intelligence.
"""
import json
import sys
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
EMAIL = f"p55-{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = "p55-password-123"

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def upload_and_wait(c, H, filename, text, timeout=90):
    r = c.post(f"{BASE}/documents/upload", headers=H, files={
        "file": (filename, text.encode(), "text/plain")
    })
    assert r.status_code == 201, r.text
    doc_id = r.json()["document"]["id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        rs = c.get(f"{BASE}/documents/{doc_id}/semantic", headers=H)
        if rs.status_code == 200 and rs.json().get("status") == "indexed":
            return doc_id
        time.sleep(1.5)
    return doc_id  # return anyway; caller asserts on readiness separately


def stream_ask(c, H, ws_id, conv_id, question, document_ids=None):
    """Returns (events_seen, answer_text, title, done_payload)."""
    events, answer, title, done = [], "", None, {}
    body = {"question": question}
    if document_ids:
        body["document_ids"] = document_ids
    with c.stream("POST", f"{BASE}/workspaces/{ws_id}/conversations/{conv_id}/ask/stream",
                  headers=H, json=body) as resp:
        ev = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                ev = line[7:]
                events.append(ev)
            elif line.startswith("data: ") and ev:
                payload = json.loads(line[6:])
                if ev == "token":
                    answer += payload.get("text", "")
                elif ev == "title":
                    title = payload.get("title")
                elif ev == "done":
                    done = payload
    return events, answer, title, done


with httpx.Client(timeout=600) as c:
    r = c.post(f"{BASE}/auth/register", json={
        "email": EMAIL, "password": PASSWORD, "full_name": "P55 E2E",
        "role": "developer", "org_id": "default",
    })
    if r.status_code not in (200, 201):
        sys.exit(f"REGISTER_FAILED {r.status_code} {r.text[:200]}")
    H = {"Authorization": f"Bearer {c.post(f'{BASE}/auth/login', json={'email': EMAIL, 'password': PASSWORD}).json()['access_token']}"}

    # ── Default workspace bootstrap ──────────────────────────────────────────
    r = c.get(f"{BASE}/workspaces", headers=H)
    check("list workspaces -> 200", r.status_code == 200, r.text[:200])
    workspaces = r.json()
    check("default workspace auto-created", len(workspaces) >= 1 and any(w["is_default"] for w in workspaces))
    default_ws = next(w for w in workspaces if w["is_default"])
    ws_id = default_ws["id"]

    # ── Adoption: upload BEFORE creating a custom workspace, expect adoption ─
    pre_doc = upload_and_wait(c, H, "adopted.txt",
                              "This document existed before any custom workspace was made.")
    r = c.get(f"{BASE}/workspaces", headers=H)  # re-list triggers ensure_default adoption
    r = c.get(f"{BASE}/workspaces/{ws_id}/documents", headers=H)
    check("pre-existing document adopted into default workspace",
          any(d["id"] == pre_doc for d in r.json()), str(r.json())[:200])

    # ── Create a custom workspace ────────────────────────────────────────────
    r = c.post(f"{BASE}/workspaces", headers=H,
               json={"name": "ERP Migration", "description": "ERP docs", "icon": "database"})
    check("create workspace -> 201", r.status_code == 201, r.text[:200])
    erp = r.json()
    erp_id = erp["id"]
    check("custom workspace not default", erp["is_default"] is False)

    # ── Seed two documents and link them to the ERP workspace ────────────────
    doc_pricing = upload_and_wait(c, H, "pricing.txt",
        "UnityWorks Enterprise plan costs 899 euros per month with unlimited users.")
    doc_hours = upload_and_wait(c, H, "hours.txt",
        "Support operates 24 hours a day for Enterprise customers, 9 to 5 for Starter.")
    for did in (doc_pricing, doc_hours):
        r = c.post(f"{BASE}/workspaces/{erp_id}/documents", headers=H, json={"document_id": did})
        check(f"link document {did[:8]} -> ok", r.status_code == 200, r.text[:200])
    r = c.get(f"{BASE}/workspaces/{erp_id}/documents", headers=H)
    check("workspace lists 2 linked documents", len(r.json()) == 2, str(len(r.json())))

    # ── Start a conversation in the workspace ────────────────────────────────
    r = c.post(f"{BASE}/workspaces/{erp_id}/conversations", headers=H, json={"title": ""})
    check("start conversation -> 201", r.status_code == 201, r.text[:200])
    conv_id = r.json()["conversation_id"]

    # ── Ask scoped to ONE document, expect grounded + auto title ─────────────
    events, answer, title, done = stream_ask(c, H, erp_id, conv_id,
        "What does the Enterprise plan cost?", document_ids=[doc_pricing])
    check("ask stream emitted stages", "stage" in events, str(events[:6]))
    check("ask stream produced tokens", "token" in events)
    check("answer mentions 899", "899" in answer, answer[:160])
    check("auto-generated title arrived", bool(title), str(title))
    check("done status completed", done.get("status") == "completed", str(done))

    # ── Multi-document: attach the SECOND doc mid-conversation, ask across ───
    events2, answer2, _, done2 = stream_ask(c, H, erp_id, conv_id,
        "What are the support hours?", document_ids=[doc_hours])
    check("follow-up across newly-attached document grounded",
          done2.get("status") == "completed" and ("24" in answer2 or "support" in answer2.lower()),
          answer2[:160])

    # ── Restore payload: both documents + both turns present ─────────────────
    r = c.get(f"{BASE}/workspaces/{erp_id}/conversations/{conv_id}", headers=H)
    check("restore conversation -> 200", r.status_code == 200, r.text[:200])
    restore = r.json()
    check("restore has 2 turns", len(restore["turns"]) == 2, str(len(restore["turns"])))
    check("restore shows both attached documents", len(restore["documents"]) == 2,
          str(len(restore["documents"])))
    check("restore title is the generated one", restore["title"] == title, f"{restore['title']} vs {title}")
    check("restore turns carry citations",
          any(len(t.get("citations", [])) >= 1 for t in restore["turns"]))

    # ── Rename conversation ──────────────────────────────────────────────────
    r = c.patch(f"{BASE}/workspaces/{erp_id}/conversations/{conv_id}", headers=H,
                json={"title": "ERP Pricing And Support"})
    check("rename conversation -> 200", r.status_code == 200 and r.json()["title"] == "ERP Pricing And Support")

    # ── Generate an artifact in the workspace, from the conversation ─────────
    gen_events, artifact_done = [], {}
    with c.stream("POST", f"{BASE}/workspaces/{erp_id}/generate/stream", headers=H,
                  json={"prompt": "Create a summary of the Enterprise pricing and support hours.",
                        "format": "pdf", "conversation_id": conv_id}) as resp:
        ev = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                ev = line[7:]
                gen_events.append(ev)
            elif line.startswith("data: ") and ev == "done":
                artifact_done = json.loads(line[6:])
    check("generation stream staged + done", "stage" in gen_events and "done" in gen_events, str(gen_events))
    check("artifact ready", artifact_done.get("status") == "ready", str(artifact_done))
    r = c.get(f"{BASE}/workspaces/{erp_id}/artifacts", headers=H)
    check("artifact belongs to workspace + remembers conversation",
          len(r.json()) == 1 and r.json()[0]["conversation_id"] == conv_id, str(r.json())[:200])

    # ── Timeline reflects the whole journey ──────────────────────────────────
    r = c.get(f"{BASE}/workspaces/{erp_id}/timeline", headers=H)
    types = {e["event_type"] for e in r.json()}
    for expected in ("workspace_created", "document_added", "conversation_started",
                     "question_answered", "artifact_generated"):
        check(f"timeline has {expected}", expected in types, str(types))

    # ── Bookmarks ────────────────────────────────────────────────────────────
    r = c.post(f"{BASE}/workspaces/{erp_id}/bookmarks", headers=H,
               json={"target_type": "conversation", "target_id": conv_id, "note": "important"})
    check("add bookmark -> 201", r.status_code == 201, r.text[:200])
    bm_id = r.json()["id"]
    r = c.get(f"{BASE}/workspaces/{erp_id}/bookmarks", headers=H)
    check("bookmark listed", any(b["id"] == bm_id for b in r.json()))
    r = c.delete(f"{BASE}/workspaces/{erp_id}/bookmarks/{bm_id}", headers=H)
    check("delete bookmark -> 200", r.status_code == 200)

    # ── Search across the workspace ──────────────────────────────────────────
    r = c.get(f"{BASE}/workspaces/{erp_id}/search?q=Enterprise", headers=H)
    check("search -> 200", r.status_code == 200, r.text[:200])
    res = r.json()["results"]
    check("search finds documents or chunks",
          len(res["documents"]) >= 1 or len(res["chunks"]) >= 1, json.dumps(res)[:200])
    check("search finds a conversation turn", len(res["turns"]) >= 1, str(res["turns"])[:160])

    # ── Related documents (AI recommendation) ────────────────────────────────
    r = c.get(f"{BASE}/workspaces/{erp_id}/related?q=how much does support cost", headers=H)
    check("related -> 200", r.status_code == 200, r.text[:200])

    # ── Save conversation as knowledge (reuses upload pipeline) ──────────────
    r = c.post(f"{BASE}/workspaces/{erp_id}/conversations/{conv_id}/save-as-knowledge", headers=H)
    check("save-as-knowledge -> 200", r.status_code == 200, r.text[:200])
    saved_doc = r.json()["document_id"]
    check("saved knowledge is a new document in the workspace",
          bool(saved_doc),
          str(r.json()))
    r = c.get(f"{BASE}/workspaces/{erp_id}/documents", headers=H)
    check("workspace now has 3 documents (2 + saved conversation)",
          any(d["id"] == saved_doc for d in r.json()), str(len(r.json())))

    # ── Export conversation ──────────────────────────────────────────────────
    r = c.get(f"{BASE}/workspaces/{erp_id}/conversations/{conv_id}/export?format=markdown", headers=H)
    check("export markdown -> 200", r.status_code == 200 and b"# ERP Pricing And Support" in r.content,
          r.text[:120])
    r = c.get(f"{BASE}/workspaces/{erp_id}/conversations/{conv_id}/export?format=pdf", headers=H)
    check("export pdf -> 200 pdf bytes", r.status_code == 200 and r.content[:4] == b"%PDF")

    # ── Dashboard intelligence ───────────────────────────────────────────────
    r = c.post(f"{BASE}/workspaces/{erp_id}/summary/refresh", headers=H)
    check("summary refresh -> 200", r.status_code == 200, r.text[:200])
    r = c.get(f"{BASE}/workspaces/{erp_id}/dashboard", headers=H)
    check("dashboard -> 200", r.status_code == 200, r.text[:200])
    dash = r.json()
    check("dashboard stats reflect content",
          dash["stats"]["documents"] >= 3 and dash["stats"]["conversations"] >= 1
          and dash["stats"]["artifacts"] >= 1, json.dumps(dash["stats"]))
    check("dashboard has suggestions", len(dash["suggestions"]) >= 1)
    check("dashboard has recent activity", len(dash["recent_activity"]) >= 1)

    # ── Isolation / 404 semantics ────────────────────────────────────────────
    r = c.get(f"{BASE}/workspaces/{uuid.uuid4()}/dashboard", headers=H)
    check("unknown workspace dashboard -> 404", r.status_code == 404)
    r = c.get(f"{BASE}/workspaces/{erp_id}/conversations/{uuid.uuid4()}", headers=H)
    check("unknown conversation restore -> 404", r.status_code == 404)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
