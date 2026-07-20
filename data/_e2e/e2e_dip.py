"""
Document Intelligence Platform Phase 1 — end-to-end test against :8000.

Covers every success criterion: upload (valid + rejected + duplicate),
metadata, listing with pagination/search/filter, signed-URL download with
content verification, soft delete, and post-delete invisibility.
"""
import json
import sys
import uuid

import httpx

# 127.0.0.1 explicitly — on Windows, "localhost" resolves to ::1 first, where
# the Docker-published api container answers instead of the local dev server.
BASE = "http://127.0.0.1:8000/api/v1"
EMAIL = f"dip-{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = "dip-password-123"

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


with httpx.Client(timeout=120) as c:
    # ── Auth ──────────────────────────────────────────────────────────────────
    r = c.post(f"{BASE}/auth/register", json={
        "email": EMAIL, "password": PASSWORD, "full_name": "DIP E2E",
        "role": "developer", "org_id": "default",
    })
    if r.status_code not in (200, 201):
        sys.exit(f"REGISTER_FAILED {r.status_code} {r.text[:200]}")
    r = c.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    H = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # ── Upload: valid text file ───────────────────────────────────────────────
    content_a = f"DIP e2e document A — {uuid.uuid4().hex}\nline two\n".encode()
    r = c.post(f"{BASE}/documents/upload", headers=H,
               files={"file": ("report notes.txt", content_a, "text/plain")},
               data={"tags": json.dumps(["e2e", "phase1"])})
    check("upload txt → 201", r.status_code == 201, f"{r.status_code} {r.text[:200]}")
    doc_a = r.json()["document"]
    check("upload response has uuid id", len(doc_a["id"]) == 36)
    check("status completed", doc_a["upload_status"] == "completed")
    check("tags round-trip", doc_a["tags"] == ["e2e", "phase1"], str(doc_a["tags"]))
    check("no storage internals leaked",
          "storage_key" not in doc_a and "storage_bucket" not in doc_a and "s3" not in json.dumps(doc_a).lower())

    # ── Upload: valid PDF (magic bytes) ──────────────────────────────────────
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n" + uuid.uuid4().hex.encode()
    r = c.post(f"{BASE}/documents/upload", headers=H,
               files={"file": ("spec.pdf", pdf_bytes, "application/pdf")})
    check("upload pdf → 201", r.status_code == 201, f"{r.status_code} {r.text[:200]}")
    doc_b = r.json()["document"]

    # ── Validation rejections ────────────────────────────────────────────────
    r = c.post(f"{BASE}/documents/upload", headers=H,
               files={"file": ("malware.exe", b"MZbinary", "application/octet-stream")})
    check("reject .exe → 422", r.status_code == 422, str(r.status_code))
    check("stable error code", r.json()["detail"]["code"] == "unsupported_type", r.text[:150])

    r = c.post(f"{BASE}/documents/upload", headers=H,
               files={"file": ("empty.txt", b"", "text/plain")})
    check("reject empty file → 422", r.status_code == 422 and r.json()["detail"]["code"] == "empty_file",
          f"{r.status_code} {r.text[:150]}")

    r = c.post(f"{BASE}/documents/upload", headers=H,
               files={"file": ("fake.pdf", b"this is not a pdf at all", "application/pdf")})
    check("reject fake pdf (magic bytes) → 422",
          r.status_code == 422 and r.json()["detail"]["code"] == "content_mismatch",
          f"{r.status_code} {r.text[:150]}")

    # ── Duplicate detection (checksum) ───────────────────────────────────────
    r = c.post(f"{BASE}/documents/upload", headers=H,
               files={"file": ("copy of report.txt", content_a, "text/plain")})
    check("duplicate → 409 + existing id",
          r.status_code == 409 and r.json()["detail"]["existing_id"] == doc_a["id"],
          f"{r.status_code} {r.text[:200]}")

    r = c.post(f"{BASE}/documents/upload?allow_duplicate=true", headers=H,
               files={"file": ("copy of report.txt", content_a, "text/plain")})
    check("allow_duplicate → 201 + duplicate_of",
          r.status_code == 201 and r.json()["duplicate_of"] == doc_a["id"],
          f"{r.status_code} {r.text[:200]}")
    doc_dup = r.json()["document"]

    # ── Listing, pagination, search, filter ──────────────────────────────────
    r = c.get(f"{BASE}/documents", headers=H)
    body = r.json()
    check("list → 200, total=3", r.status_code == 200 and body["total"] == 3,
          f"{r.status_code} total={body.get('total')}")

    r = c.get(f"{BASE}/documents?limit=2&offset=0", headers=H)
    check("pagination limit=2", len(r.json()["items"]) == 2 and r.json()["total"] == 3)

    r = c.get(f"{BASE}/documents?q=report", headers=H)
    check("search by filename 'report' → 2", r.json()["total"] == 2, str(r.json()["total"]))

    r = c.get(f"{BASE}/documents?extension=pdf", headers=H)
    check("filter extension=pdf → 1", r.json()["total"] == 1 and r.json()["items"][0]["id"] == doc_b["id"])

    # ── Get metadata ─────────────────────────────────────────────────────────
    r = c.get(f"{BASE}/documents/{doc_a['id']}", headers=H)
    check("get by id → 200 + checksum", r.status_code == 200 and len(r.json()["checksum_sha256"]) == 64)

    r = c.get(f"{BASE}/documents/{uuid.uuid4()}", headers=H)
    check("get unknown id → 404", r.status_code == 404)

    # ── Download ─────────────────────────────────────────────────────────────
    r = c.get(f"{BASE}/documents/{doc_a['id']}/download", headers=H)
    check("download → 200", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
    ct = r.headers.get("content-type", "")
    if ct.startswith("application/json"):
        # Signed-URL mode (S3): fetch the URL without auth and verify content
        link = r.json()
        check("signed url present + ttl", bool(link.get("url")) and link["expires_in_seconds"] > 0)
        r2 = httpx.get(link["url"], timeout=60)
        check("signed url fetch → 200 + exact bytes",
              r2.status_code == 200 and r2.content == content_a,
              f"{r2.status_code} len={len(r2.content)}")
    else:
        # Proxy mode (local backend)
        check("proxy download exact bytes", r.content == content_a)

    # ── Soft delete ──────────────────────────────────────────────────────────
    r = c.delete(f"{BASE}/documents/{doc_dup['id']}", headers=H)
    check("delete → 200", r.status_code == 200 and r.json()["deleted"] is True)

    r = c.get(f"{BASE}/documents/{doc_dup['id']}", headers=H)
    check("deleted doc → 404", r.status_code == 404)

    r = c.get(f"{BASE}/documents", headers=H)
    check("list excludes deleted (total=2)", r.json()["total"] == 2, str(r.json()["total"]))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
