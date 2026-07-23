"""
DIP Phase 5.7 — Workspace hardening: PDF export robustness + complete
document deletion (no orphans).
"""
import sys
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
EMAIL = f"p57-{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = "p57-password-123"

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


with httpx.Client(timeout=600) as c:
    c.post(f"{BASE}/auth/register", json={
        "email": EMAIL, "password": PASSWORD, "full_name": "P57",
        "role": "developer", "org_id": "default"})
    H = {"Authorization": f"Bearer {c.post(f'{BASE}/auth/login', json={'email': EMAIL, 'password': PASSWORD}).json()['access_token']}"}
    ws = next(w for w in c.get(f"{BASE}/workspaces", headers=H).json() if w["is_default"])["id"]

    # Upload a document and wait for it to be fully indexed.
    up = c.post(f"{BASE}/workspaces/{ws}/upload", headers=H, files={
        "file": ("delete_me.txt",
                 b"The enterprise plan costs 899 euros. Support is 24 hours a day.", "text/plain")})
    doc_id = up.json()["document"]["id"]
    deadline = time.time() + 120
    indexed = False
    while time.time() < deadline:
        r = c.get(f"{BASE}/documents/{doc_id}/semantic", headers=H)
        if r.status_code == 200 and r.json().get("status") == "indexed":
            indexed = True
            break
        time.sleep(2)
    check("uploaded document indexed", indexed)

    # ── Conversation with markdown/HTML answer → PDF export must not crash ───
    conv = c.post(f"{BASE}/workspaces/{ws}/conversations", headers=H, json={"title": ""}).json()["conversation_id"]
    # Ask something that yields a normal grounded answer.
    with c.stream("POST", f"{BASE}/workspaces/{ws}/conversations/{conv}/ask/stream", headers=H,
                  json={"question": "What does the enterprise plan cost and what are support hours?"}) as resp:
        for _ in resp.iter_lines():
            pass

    for fmt, magic in (("markdown", b"#"), ("pdf", b"%PDF"), ("word", b"PK")):
        r = c.get(f"{BASE}/workspaces/{ws}/conversations/{conv}/export?format={fmt}", headers=H)
        check(f"export {fmt} -> 200", r.status_code == 200, f"{r.status_code} {r.text[:100]}")
        check(f"export {fmt} valid bytes", r.content[:4].startswith(magic) or magic in r.content[:8],
              str(r.content[:8]))

    # Also directly exercise the sanitizer path with a hostile-content title.
    conv2 = c.post(f"{BASE}/workspaces/{ws}/conversations", headers=H,
                   json={"title": "Compare <A> & <B> with code a<b"}).json()["conversation_id"]
    with c.stream("POST", f"{BASE}/workspaces/{ws}/conversations/{conv2}/ask/stream", headers=H,
                  json={"question": "Summarize the document"}) as resp:
        for _ in resp.iter_lines():
            pass
    r = c.get(f"{BASE}/workspaces/{ws}/conversations/{conv2}/export?format=pdf", headers=H)
    check("PDF export with hostile title/content -> 200", r.status_code == 200 and r.content[:4] == b"%PDF",
          f"{r.status_code} {r.content[:8]}")

    # ── Bookmark the document, then delete it → complete purge ───────────────
    c.post(f"{BASE}/workspaces/{ws}/bookmarks", headers=H,
           json={"target_type": "document", "target_id": doc_id, "note": "keep"})
    check("bookmark created for document",
          any(b["target_id"] == doc_id for b in c.get(f"{BASE}/workspaces/{ws}/bookmarks", headers=H).json()))

    # Attach to a conversation so there's a conversation reference to purge.
    c.post(f"{BASE}/workspaces/{ws}/conversations/{conv}/documents", headers=H,
           json={"document_id": doc_id})

    knowledge = c.get(f"{BASE}/documents/{doc_id}/knowledge", headers=H)
    check("knowledge object exists before delete", knowledge.status_code == 200)

    dele = c.delete(f"{BASE}/workspaces/{ws}/documents/{doc_id}", headers=H)
    check("delete document -> 200", dele.status_code == 200, dele.text[:160])
    check("delete removed vectors", dele.json().get("vectors_removed", 0) >= 1, str(dele.json()))
    check("delete removed the bookmark", dele.json().get("bookmarks_removed", 0) >= 1, str(dele.json()))

    # ── Verify NO orphans remain ─────────────────────────────────────────────
    check("document gone from workspace list",
          not any(d["id"] == doc_id for d in c.get(f"{BASE}/workspaces/{ws}/documents", headers=H).json()))
    check("document gone from conversation context",
          not any(d["id"] == doc_id for d in
                  c.get(f"{BASE}/workspaces/{ws}/conversations/{conv}", headers=H).json()["documents"]))
    check("bookmark gone",
          not any(b["target_id"] == doc_id for b in c.get(f"{BASE}/workspaces/{ws}/bookmarks", headers=H).json()))
    check("knowledge object gone (404)",
          c.get(f"{BASE}/documents/{doc_id}/knowledge", headers=H).status_code == 404)
    check("semantic manifest gone (409/404)",
          c.get(f"{BASE}/documents/{doc_id}/semantic", headers=H).status_code in (404, 409))
    check("embeddings gone",
          c.get(f"{BASE}/documents/{doc_id}/embeddings", headers=H).json().get("total", 0) == 0
          if c.get(f"{BASE}/documents/{doc_id}/embeddings", headers=H).status_code == 200 else True)

    # ── Re-upload the SAME file after delete is allowed (link was purged) ────
    re_up = c.post(f"{BASE}/workspaces/{ws}/upload", headers=H, files={
        "file": ("delete_me.txt",
                 b"The enterprise plan costs 899 euros. Support is 24 hours a day.", "text/plain")})
    check("re-upload same file after delete -> 201 (not a false duplicate)",
          re_up.status_code == 201, f"{re_up.status_code} {re_up.text[:120]}")

    # ── Search no longer returns the deleted document ────────────────────────
    sr = c.get(f"{BASE}/workspaces/{ws}/search?q=enterprise", headers=H).json()["results"]
    check("deleted document not in search results",
          not any(d["id"] == doc_id for d in sr["documents"]))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
