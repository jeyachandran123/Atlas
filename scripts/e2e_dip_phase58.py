"""
DIP Phase 5.8 — Workspace polish: unicode-safe PDF export + conversation
retrieval modes (all | selected) that change scope without touching history.
"""
import sys
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
EMAIL = f"p58-{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = "p58-password-123"

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


def ask(c, H, ws, conv, q, mode_docs=None):
    ans = ""
    grounded = None
    body = {"question": q}
    with c.stream("POST", f"{BASE}/workspaces/{ws}/conversations/{conv}/ask/stream",
                  headers=H, json=body) as r:
        ev = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: ") and ev:
                import json
                d = json.loads(line[6:])
                if ev == "token":
                    ans += d.get("text", "")
                elif ev == "citations":
                    grounded = d.get("grounded")
    return ans, grounded


with httpx.Client(timeout=600) as c:
    c.post(f"{BASE}/auth/register", json={
        "email": EMAIL, "password": PASSWORD, "full_name": "P58",
        "role": "developer", "org_id": "default"})
    H = {"Authorization": f"Bearer {c.post(f'{BASE}/auth/login', json={'email': EMAIL, 'password': PASSWORD}).json()['access_token']}"}
    ws = next(w for w in c.get(f"{BASE}/workspaces", headers=H).json() if w["is_default"])["id"]

    def upload(name, text):
        d = c.post(f"{BASE}/workspaces/{ws}/upload", headers=H, files={"file": (name, text.encode(), "text/plain")}).json()["document"]["id"]
        deadline = time.time() + 120
        while time.time() < deadline:
            if c.get(f"{BASE}/documents/{d}/semantic", headers=H).status_code == 200:
                return d
            time.sleep(2)
        return d

    doc_pricing = upload("pricing.txt", "The Enterprise plan costs exactly 899 euros per month.")
    doc_hours = upload("hours.txt", "Support is available 24 hours a day, seven days a week.")
    check("two documents indexed", True)

    # ── Retrieval mode: default is 'all' ─────────────────────────────────────
    conv = c.post(f"{BASE}/workspaces/{ws}/conversations", headers=H, json={"title": ""}).json()["conversation_id"]
    restore = c.get(f"{BASE}/workspaces/{ws}/conversations/{conv}", headers=H).json()
    check("new conversation defaults to mode=all", restore["retrieval_mode"] == "all", str(restore.get("retrieval_mode")))

    # In 'all' mode, a question about hours is answerable (all docs in scope)
    ans, grounded = ask(c, H, ws, conv, "How many hours a day is support available?")
    check("all mode: support-hours question grounded", grounded is True and "24" in ans, ans[:120])

    # ── Switch to 'selected' with NO documents → honest refusal ─────────────
    r = c.patch(f"{BASE}/workspaces/{ws}/conversations/{conv}/mode", headers=H, json={"mode": "selected"})
    check("switch to selected -> 200", r.status_code == 200 and r.json()["retrieval_mode"] == "selected", r.text[:120])
    ans2, grounded2 = ask(c, H, ws, conv, "How much does the Enterprise plan cost?")
    check("selected mode with no docs → not grounded (scope empty)", grounded2 is not True, f"grounded={grounded2}")

    # ── Attach ONLY the pricing doc → pricing answerable, hours not ─────────
    c.post(f"{BASE}/workspaces/{ws}/conversations/{conv}/documents", headers=H, json={"document_id": doc_pricing})
    restore2 = c.get(f"{BASE}/workspaces/{ws}/conversations/{conv}", headers=H).json()
    check("selected scope shows the attached doc", len(restore2["documents"]) == 1)
    ans3, grounded3 = ask(c, H, ws, conv, "What is the Enterprise plan price?")
    check("selected mode: pricing question grounded (899)", grounded3 is True and "899" in ans3, ans3[:120])

    # History preserved across mode changes
    restore3 = c.get(f"{BASE}/workspaces/{ws}/conversations/{conv}", headers=H).json()
    check("history preserved across mode switches", len(restore3["turns"]) == 3, str(len(restore3["turns"])))

    # ── Detach → scope empty again ───────────────────────────────────────────
    c.request("DELETE", f"{BASE}/workspaces/{ws}/conversations/{conv}/documents/{doc_pricing}", headers=H)
    restore4 = c.get(f"{BASE}/workspaces/{ws}/conversations/{conv}", headers=H).json()
    check("detach removes doc from conversation scope", len(restore4["documents"]) == 0)
    check("detach did not delete the document from workspace",
          any(d["id"] == doc_pricing for d in c.get(f"{BASE}/workspaces/{ws}/documents", headers=H).json()))

    # ── Switch back to all ───────────────────────────────────────────────────
    c.patch(f"{BASE}/workspaces/{ws}/conversations/{conv}/mode", headers=H, json={"mode": "all"})
    ans5, grounded5 = ask(c, H, ws, conv, "What are the support hours?")
    check("back to all mode: hours answerable again", grounded5 is True and "24" in ans5, ans5[:120])

    # ── Unicode-safe PDF export (the 500 root cause) ─────────────────────────
    c.patch(f"{BASE}/workspaces/{ws}/conversations/{conv}", headers=H, json={"title": "日本語 分析 🎉 Отчёт"})
    for fmt, magic in (("pdf", b"%PDF"), ("word", b"PK"), ("markdown", b"#")):
        r = c.get(f"{BASE}/workspaces/{ws}/conversations/{conv}/export?format={fmt}", headers=H)
        check(f"export {fmt} with CJK/emoji title -> 200", r.status_code == 200 and magic in r.content[:8],
              f"{r.status_code} {r.content[:8]}")
        cd = r.headers.get("content-disposition", "")
        check(f"export {fmt} Content-Disposition is RFC 6266 (filename*)", "filename*=UTF-8''" in cd, cd)

    # ── Mode validation ──────────────────────────────────────────────────────
    r = c.patch(f"{BASE}/workspaces/{ws}/conversations/{conv}/mode", headers=H, json={"mode": "bogus"})
    check("invalid mode -> 422", r.status_code == 422)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
