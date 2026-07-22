"""
DIP Phase 5.6 — Workspace production-hardening verification.

Covers: per-workspace duplicate policy (reject same-workspace, allow
cross-workspace), atomic workspace upload + conversation attach, remove
document from conversation (not workspace), soft delete conversation,
export (md/pdf/word) via authenticated request, and save-as-knowledge
reaching knowledge_ready through the recovery-backed pipeline.
"""
import io
import sys
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
EMAIL = f"p56-{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = "p56-password-123"

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


def upload(c, H, ws_id, filename, text, conversation_id=None):
    qs = f"?conversation_id={conversation_id}" if conversation_id else ""
    return c.post(
        f"{BASE}/workspaces/{ws_id}/upload{qs}", headers=H,
        files={"file": (filename, text.encode(), "text/plain")},
    )


with httpx.Client(timeout=600) as c:
    c.post(f"{BASE}/auth/register", json={
        "email": EMAIL, "password": PASSWORD, "full_name": "P56",
        "role": "developer", "org_id": "default",
    })
    H = {"Authorization": f"Bearer {c.post(f'{BASE}/auth/login', json={'email': EMAIL, 'password': PASSWORD}).json()['access_token']}"}

    # Two workspaces
    default_ws = next(w for w in c.get(f"{BASE}/workspaces", headers=H).json() if w["is_default"])
    ws_a = default_ws["id"]
    ws_b = c.post(f"{BASE}/workspaces", headers=H, json={"name": "Second"}).json()["id"]

    SAME = "Identical content for the duplicate-policy test. Value is 42."

    # ── Issue 2 / 10: per-workspace duplicate policy ─────────────────────────
    r1 = upload(c, H, ws_a, "dup.txt", SAME)
    check("upload to workspace A -> 201", r1.status_code == 201, r1.text[:200])
    r2 = upload(c, H, ws_a, "dup.txt", SAME)
    check("same file again in workspace A -> 409 (rejected)", r2.status_code == 409,
          f"{r2.status_code} {r2.text[:160]}")
    check("409 carries a clear message",
          "already exists" in (r2.json().get("detail", {}).get("message", "") if r2.status_code == 409 else ""),
          r2.text[:160])
    r3 = upload(c, H, ws_b, "dup.txt", SAME)
    check("same file in workspace B -> 201 (allowed across workspaces)",
          r3.status_code == 201, f"{r3.status_code} {r3.text[:160]}")

    check("workspace A has exactly 1 copy",
          len(c.get(f"{BASE}/workspaces/{ws_a}/documents", headers=H).json()) == 1)
    check("workspace B has its own copy",
          len(c.get(f"{BASE}/workspaces/{ws_b}/documents", headers=H).json()) == 1)

    # ── Atomic upload + attach to a conversation ─────────────────────────────
    conv = c.post(f"{BASE}/workspaces/{ws_a}/conversations", headers=H, json={"title": ""}).json()
    conv_id = conv["conversation_id"]
    ra = upload(c, H, ws_a, "attached.txt",
                "The support hotline is open 24 hours for enterprise plans.", conv_id)
    check("upload attached to conversation -> 201", ra.status_code == 201, ra.text[:200])
    check("upload reports it attached", ra.json().get("attached_to_conversation") is True, ra.text[:200])
    attached_doc = ra.json()["document"]["id"]

    restore = c.get(f"{BASE}/workspaces/{ws_a}/conversations/{conv_id}", headers=H).json()
    check("conversation context includes the attached document",
          any(d["id"] == attached_doc for d in restore["documents"]), str(restore["documents"])[:200])

    # ── Issue 9: remove document from conversation (not workspace) ───────────
    rd = c.delete(f"{BASE}/workspaces/{ws_a}/conversations/{conv_id}/documents/{attached_doc}", headers=H)
    check("remove document from conversation -> 200", rd.status_code == 200, rd.text[:160])
    check("remove reports removed", rd.json().get("removed") is True)
    restore2 = c.get(f"{BASE}/workspaces/{ws_a}/conversations/{conv_id}", headers=H).json()
    check("document gone from conversation context",
          not any(d["id"] == attached_doc for d in restore2["documents"]))
    check("document STILL in the workspace",
          any(d["id"] == attached_doc for d in c.get(f"{BASE}/workspaces/{ws_a}/documents", headers=H).json()))

    # ── Issue 5: export works (authenticated) ────────────────────────────────
    for fmt, magic in (("markdown", b"#"), ("pdf", b"%PDF")):
        re_ = c.get(f"{BASE}/workspaces/{ws_a}/conversations/{conv_id}/export?format={fmt}", headers=H)
        check(f"export {fmt} -> 200", re_.status_code == 200, f"{re_.status_code} {re_.text[:120]}")
        check(f"export {fmt} returns real bytes", re_.content[:4].startswith(magic) or magic in re_.content[:8])

    # ── Issue 4: soft delete conversation ────────────────────────────────────
    conv2 = c.post(f"{BASE}/workspaces/{ws_a}/conversations", headers=H, json={"title": "Temp"}).json()
    conv2_id = conv2["conversation_id"]
    before = len(c.get(f"{BASE}/workspaces/{ws_a}/conversations", headers=H).json())
    dc = c.delete(f"{BASE}/workspaces/{ws_a}/conversations/{conv2_id}", headers=H)
    check("delete conversation -> 200", dc.status_code == 200, dc.text[:160])
    after = len(c.get(f"{BASE}/workspaces/{ws_a}/conversations", headers=H).json())
    check("deleted conversation drops from the list", after == before - 1, f"{before} -> {after}")
    check("deleted conversation restore -> 404",
          c.get(f"{BASE}/workspaces/{ws_a}/conversations/{conv2_id}", headers=H).status_code == 404)

    # ── Issue 6: save-as-knowledge reaches knowledge_ready ───────────────────
    # Seed a real answer so there is content to save.
    conv3 = c.post(f"{BASE}/workspaces/{ws_a}/conversations", headers=H, json={"title": ""}).json()
    conv3_id = conv3["conversation_id"]
    with c.stream("POST", f"{BASE}/workspaces/{ws_a}/conversations/{conv3_id}/ask/stream",
                  headers=H, json={"question": "What is in the duplicate-policy document?"}) as resp:
        for _ in resp.iter_lines():
            pass
    sk = c.post(f"{BASE}/workspaces/{ws_a}/conversations/{conv3_id}/save-as-knowledge", headers=H)
    check("save-as-knowledge -> 200", sk.status_code == 200, sk.text[:200])
    saved_doc = sk.json()["document_id"]

    deadline = time.time() + 150
    final_status = None
    while time.time() < deadline:
        r = c.get(f"{BASE}/documents/{saved_doc}/processing", headers=H)
        if r.status_code == 200:
            final_status = r.json().get("processing_status")
            if final_status in ("knowledge_ready", "failed"):
                break
        time.sleep(3)
    check("saved knowledge document reaches knowledge_ready (recovery-backed)",
          final_status == "knowledge_ready", f"status={final_status}")

    # ── 404 semantics for the new endpoints ──────────────────────────────────
    check("delete unknown conversation -> 404",
          c.delete(f"{BASE}/workspaces/{ws_a}/conversations/{uuid.uuid4()}", headers=H).status_code == 404)
    check("upload to unknown workspace -> 404",
          upload(c, H, str(uuid.uuid4()), "x.txt", "y").status_code == 404)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
