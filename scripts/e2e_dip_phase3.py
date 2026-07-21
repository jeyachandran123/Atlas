"""
DIP Phase 3 — Semantic Intelligence Layer verification.

Covers: automatic embedding trigger, per-chunk embedding records, semantic
manifest, embedding validation (real dimension/checksum), semantic health,
correlation-id propagation from document processing into the embedding
job, capability registry entries, manual re-embed trigger, and reprocess
safety (the FK-ordering hazard found and fixed during this phase).
"""
import sys
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
EMAIL = f"p3-{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = "p3-password-123"

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


def wait_processing_ready(c: httpx.Client, H: dict, doc_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        r = c.get(f"{BASE}/documents/{doc_id}/processing", headers=H)
        last = r.json()
        if last.get("processing_status") in ("knowledge_ready", "failed"):
            return last
        time.sleep(1.0)
    return last


def wait_semantic_ready(c: httpx.Client, H: dict, doc_id: str, timeout: float = 60.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = c.get(f"{BASE}/documents/{doc_id}/semantic", headers=H)
        if r.status_code == 200:
            return r
        last = r
        time.sleep(1.0)
    return last


with httpx.Client(timeout=120) as c:
    r = c.post(f"{BASE}/auth/register", json={
        "email": EMAIL, "password": PASSWORD, "full_name": "P3 E2E",
        "role": "developer", "org_id": "default",
    })
    if r.status_code not in (200, 201):
        sys.exit(f"REGISTER_FAILED {r.status_code} {r.text[:200]}")
    r = c.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    H = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # ── Upload + automatic embedding trigger (Objective 2) ───────────────────
    r = c.post(f"{BASE}/documents/upload", headers=H, files={
        "file": ("semantic.txt", b"Semantic layer verification document.\n\nSecond paragraph for a second chunk boundary test with enough content to matter.\n", "text/plain")
    })
    check("upload -> 201", r.status_code == 201, r.text[:200])
    doc_id = r.json()["document"]["id"]

    proc_state = wait_processing_ready(c, H, doc_id)
    check("processing reaches knowledge_ready", proc_state.get("processing_status") == "knowledge_ready",
          str(proc_state.get("processing_status")))
    processing_correlation_id = proc_state.get("correlation_id")

    sem_resp = wait_semantic_ready(c, H, doc_id)
    check("semantic manifest appears automatically (no manual trigger)", sem_resp is not None and sem_resp.status_code == 200,
          str(sem_resp.status_code if sem_resp else "timeout"))
    manifest = sem_resp.json()

    # ── Objective 6/8/13: registry + versioning fields ────────────────────────
    check("vector_store_provider == chroma", manifest.get("vector_store_provider") == "chroma")
    check("provider_name == ollama", manifest.get("provider_name") == "ollama")
    check("model_name == nomic-embed-text", manifest.get("model_name") == "nomic-embed-text", str(manifest.get("model_name")))
    check("dimension == 768 (real Ollama output)", manifest.get("dimension") == 768, str(manifest.get("dimension")))
    check("embedding_version populated", manifest.get("embedding_version") == "1.0.0")
    check("status == indexed", manifest.get("status") == "indexed", str(manifest.get("status")))
    check("similarity_strategy == cosine", manifest.get("similarity_strategy") == "cosine")
    check("embedding_count >= 1", manifest.get("embedding_count", 0) >= 1)

    # ── Objective 4: correlation id inherited from the document, not fresh ───
    check("semantic correlation_id matches the document's processing correlation_id",
          manifest.get("correlation_id") == processing_correlation_id,
          f"{manifest.get('correlation_id')} vs {processing_correlation_id}")

    # ── Objective 6: per-chunk embedding records ──────────────────────────────
    r = c.get(f"{BASE}/documents/{doc_id}/embeddings", headers=H)
    check("embeddings list -> 200", r.status_code == 200, r.text[:200])
    emb_body = r.json()
    check("embeddings total matches manifest embedding_count",
          emb_body["total"] == manifest["embedding_count"],
          f"{emb_body['total']} vs {manifest['embedding_count']}")
    if emb_body["items"]:
        rec = emb_body["items"][0]
        check("embedding record has real dimension", rec["dimension"] == 768, str(rec["dimension"]))
        check("embedding record status == verified", rec["status"] == "verified", str(rec["status"]))
        check("embedding record has a vector checksum (not the raw vector)",
              len(rec.get("vector_checksum", "")) == 64, str(rec.get("vector_checksum")))
        check("embedding record carries real latency", isinstance(rec.get("latency_ms"), int) and rec["latency_ms"] >= 0)

    # ── Objective 14: semantic health ─────────────────────────────────────────
    r = c.get(f"{BASE}/documents/{doc_id}/semantic-health", headers=H)
    check("semantic-health -> 200", r.status_code == 200, r.text[:200])
    health = r.json()
    check("semantic health == healthy for a clean run", health.get("status") == "healthy", str(health))

    # ── Objective 15: capability registry reflects the active providers ──────
    r = c.get(f"{BASE}/platform/capabilities", headers=H)
    check("platform capabilities -> 200", r.status_code == 200)
    caps = r.json()["items"]
    check("ollama registered as embedding_provider",
          any(x["name"] == "ollama" and x["category"] == "embedding_provider" for x in caps), str(caps))
    check("chroma registered as vector_store",
          any(x["name"] == "chroma" and x["category"] == "vector_store" for x in caps), str(caps))
    check("dip_semantic_index registered as semantic_index",
          any(x["name"] == "dip_semantic_index" and x["category"] == "semantic_index" for x in caps), str(caps))

    # ── Manual re-embed trigger (Objective 2's manual-retry support) ─────────
    r = c.post(f"{BASE}/documents/{doc_id}/embed", headers=H)
    check("manual /embed trigger -> 200", r.status_code == 200, r.text[:200])
    manual_job_id = r.json()["job_id"]
    check("manual embed returns a fresh job id", manual_job_id != "", str(r.json()))

    sem_resp2 = wait_semantic_ready(c, H, doc_id)
    check("re-embed completes and semantic manifest still resolves",
          sem_resp2 is not None and sem_resp2.status_code == 200)

    # ── Reprocess safety — the exact FK-ordering hazard found this phase ─────
    r = c.post(f"{BASE}/documents/{doc_id}/process", headers=H)
    check("reprocess after embeddings exist -> 200", r.status_code == 200, r.text[:200])
    proc_state2 = wait_processing_ready(c, H, doc_id)
    check("reprocess with pre-existing embeddings reaches knowledge_ready (no FK violation)",
          proc_state2.get("processing_status") == "knowledge_ready",
          f"status={proc_state2.get('processing_status')} error={proc_state2.get('error')}")

    sem_resp3 = wait_semantic_ready(c, H, doc_id)
    check("new embedding generated automatically after reprocess",
          sem_resp3 is not None and sem_resp3.status_code == 200)
    if sem_resp3 and sem_resp3.status_code == 200:
        new_manifest = sem_resp3.json()
        check("reprocess produced a NEW knowledge_id (fresh KnowledgeObject)",
              new_manifest["knowledge_id"] != manifest["knowledge_id"],
              f"{new_manifest['knowledge_id']} == {manifest['knowledge_id']}")

    # ── Ownership / 404 semantics ──────────────────────────────────────────────
    r = c.get(f"{BASE}/documents/{uuid.uuid4()}/semantic", headers=H)
    check("unknown doc semantic -> 404", r.status_code == 404)
    r = c.get(f"{BASE}/documents/{uuid.uuid4()}/embeddings", headers=H)
    check("unknown doc embeddings -> 404", r.status_code == 404)
    r = c.get(f"{BASE}/documents/{uuid.uuid4()}/semantic-health", headers=H)
    check("unknown doc semantic-health -> 404", r.status_code == 404)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
