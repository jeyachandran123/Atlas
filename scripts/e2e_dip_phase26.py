"""
DIP Phase 2.6 — Knowledge Platform Foundation Hardening verification.

Covers: lifecycle model, manifest, correlation-id propagation, health
evaluation, lineage, and the platform capability registry. Feature flags
and document identity are exercised in-process (pure code, no HTTP needed)
since they're intentionally not exposed as API endpoints.
"""
import sys
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
EMAIL = f"p26-{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = "p26-password-123"

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


def wait_ready(c: httpx.Client, H: dict, doc_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        r = c.get(f"{BASE}/documents/{doc_id}/processing", headers=H)
        last = r.json()
        if last.get("processing_status") in ("knowledge_ready", "failed"):
            return last
        time.sleep(1.0)
    return last


# ── In-process checks: feature flags + document identity (no API surface) ──
print("— in-process: feature flags —")
sys.path.insert(0, ".")
from app.platform.feature_flags import FeatureFlagService, StaticFlagProvider, FlagContext, FlagScope  # noqa: E402

provider = StaticFlagProvider()
svc = FeatureFlagService(provider)
check("unknown flag defaults False", svc.is_enabled("nonexistent_flag") is False)
check("vision_ai_enabled defaults True", svc.is_enabled("vision_ai_enabled") is True)
check("ocr_enabled defaults False", svc.is_enabled("ocr_enabled") is False)

provider.set_override("ocr_enabled", FlagScope.TENANT, "org-x", True)
ctx_match = FlagContext(tenant_id="org-x")
ctx_other = FlagContext(tenant_id="org-y")
check("tenant override applies for matching tenant", svc.is_enabled("ocr_enabled", ctx_match) is True)
check("tenant override does not leak to other tenants", svc.is_enabled("ocr_enabled", ctx_other) is False)

provider.set_override("ocr_enabled", FlagScope.USER, "user-1", False)
ctx_user = FlagContext(tenant_id="org-x", user_id="user-1")
check("user scope outranks tenant scope", svc.is_enabled("ocr_enabled", ctx_user) is False)

print("— in-process: document identity —")
from app.document_platform.identity import DocumentIdentityBuilder  # noqa: E402
from app.document_platform.processing.models import DocumentNode, NodeType  # noqa: E402

builder = DocumentIdentityBuilder()
bid = builder.binary_identity("abc123", 42)
check("binary identity exposes sha256 + size", bid.sha256 == "abc123" and bid.size_bytes == 42)
check("binary_hash aliases sha256", bid.binary_hash == bid.sha256)

tree_a = DocumentNode(type=NodeType.DOCUMENT)
tree_a.add(DocumentNode(type=NodeType.PARAGRAPH, text="hello world"))
tree_b = DocumentNode(type=NodeType.DOCUMENT)
tree_b.add(DocumentNode(type=NodeType.PARAGRAPH, text="completely different text"))
cid_a = builder.content_identity(tree_a, "en")
cid_b = builder.content_identity(tree_b, "en")
check("structure_signature is deterministic for identical shape",
      cid_a.structure_signature == cid_b.structure_signature,
      f"{cid_a.structure_signature} vs {cid_b.structure_signature}")
check("semantic_fingerprint honestly None (no AI implemented)", cid_a.semantic_fingerprint is None)
check("content_signature honestly None (no AI implemented)", cid_a.content_signature is None)
check("language_signature reflects detected language", cid_a.language_signature == "en")

tree_c = DocumentNode(type=NodeType.DOCUMENT)
tree_c.add(DocumentNode(type=NodeType.PARAGRAPH, text="x"))
tree_c.add(DocumentNode(type=NodeType.PARAGRAPH, text="y"))
cid_c = builder.content_identity(tree_c, "en")
check("structure_signature differs for different shape", cid_c.structure_signature != cid_a.structure_signature)

print("— in-process: lifecycle transition rules —")
from app.document_platform.knowledge.lifecycle import (  # noqa: E402
    KnowledgeLifecycle, validate_transition, InvalidLifecycleTransition, is_terminal,
)

try:
    validate_transition(KnowledgeLifecycle.DRAFT, KnowledgeLifecycle.PROCESSING)
    check("DRAFT -> PROCESSING allowed", True)
except InvalidLifecycleTransition:
    check("DRAFT -> PROCESSING allowed", False)

try:
    validate_transition(KnowledgeLifecycle.DRAFT, KnowledgeLifecycle.ARCHIVED)
    check("DRAFT -> ARCHIVED rejected", False, "should have raised")
except InvalidLifecycleTransition:
    check("DRAFT -> ARCHIVED rejected", True)

check("DELETED is terminal", is_terminal(KnowledgeLifecycle.DELETED))
check("ACTIVE is not terminal", not is_terminal(KnowledgeLifecycle.ACTIVE))

# ── HTTP: manifest, health, lineage, capabilities, correlation ─────────────
print("— HTTP: manifest / health / lineage / capabilities —")
with httpx.Client(timeout=120) as c:
    r = c.post(f"{BASE}/auth/register", json={
        "email": EMAIL, "password": PASSWORD, "full_name": "P26 E2E",
        "role": "developer", "org_id": "default",
    })
    if r.status_code not in (200, 201):
        sys.exit(f"REGISTER_FAILED {r.status_code} {r.text[:200]}")
    r = c.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    H = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = c.post(f"{BASE}/documents/upload", headers=H, files={
        "file": ("p26.txt", b"Phase 2.6 verification document.\n\nSecond paragraph here.\n", "text/plain")
    })
    check("upload -> 201", r.status_code == 201, r.text[:200])
    doc_id = r.json()["document"]["id"]

    state = wait_ready(c, H, doc_id)
    check("reaches knowledge_ready", state.get("processing_status") == "knowledge_ready",
          f"status={state.get('processing_status')} error={state.get('error')}")
    processing_correlation_id = state.get("correlation_id")
    check("processing state exposes correlation_id", bool(processing_correlation_id))

    # ── Manifest (Objective 3) ──────────────────────────────────────────────
    r = c.get(f"{BASE}/documents/{doc_id}/manifest", headers=H)
    check("manifest -> 200", r.status_code == 200, r.text[:200])
    manifest = r.json()
    check("lifecycle_state == active", manifest.get("lifecycle_state") == "active", str(manifest.get("lifecycle_state")))
    check("parser_name populated", manifest.get("parser_name") == "text", str(manifest.get("parser_name")))
    check("parser_version populated", manifest.get("parser_version") == "1.0.0")
    check("chunk_version populated", manifest.get("chunk_version") == "1.0.0")
    check("embedding_version placeholder present", manifest.get("embedding_version") == "1.0.0")
    check("knowledge_version starts at 1", manifest.get("knowledge_version") == 1)
    check("validation_status == passed", manifest.get("validation_status") == "passed")
    check("capabilities snapshot present", bool(manifest.get("capabilities")), str(manifest.get("capabilities")))
    check("retry_count == 0 for clean run", manifest.get("retry_count") == 0)
    check("visibility defaults to org", manifest.get("visibility") == "org")
    check("content_identity present", manifest.get("content_identity") is not None)
    ci = manifest.get("content_identity") or {}
    check("content_identity.structure_signature computed", bool(ci.get("structure_signature")))
    check("content_identity.semantic_fingerprint honestly None", ci.get("semantic_fingerprint") is None)

    # ── Objective 4: correlation id matches across processing + manifest ────
    check("correlation_id matches between /processing and /manifest",
          manifest.get("correlation_id") == processing_correlation_id,
          f"{manifest.get('correlation_id')} vs {processing_correlation_id}")

    # ── Health (Objective 9) ─────────────────────────────────────────────────
    r = c.get(f"{BASE}/documents/{doc_id}/health", headers=H)
    check("health -> 200", r.status_code == 200, r.text[:200])
    health = r.json()
    check("health status is healthy for a clean run", health.get("status") == "healthy", str(health))

    # ── Lineage (Objective 8) ────────────────────────────────────────────────
    r = c.get(f"{BASE}/documents/{doc_id}/lineage", headers=H)
    check("lineage -> 200", r.status_code == 200, r.text[:200])
    lineage = r.json()
    chain = lineage.get("chain", [])
    check("lineage chain has at least one edge", len(chain) >= 1, str(chain))
    if chain:
        first = chain[0]
        check("lineage edge: knowledge_object -> document",
              first.get("node_type") == "knowledge_object" and first.get("parent_type") == "document",
              str(first))

    # ── Platform Capability Registry (Objective 5) ───────────────────────────
    r = c.get(f"{BASE}/platform/capabilities", headers=H)
    check("platform capabilities -> 200", r.status_code == 200, r.text[:200])
    caps = r.json()["items"]
    parser_names = {c_["name"] for c_ in caps if c_["category"] == "document_parser"}
    check("all 10 parsers registered", parser_names == {
        "pdf", "word", "excel", "csv", "powerpoint", "json", "xml", "text", "markdown", "image",
    }, str(parser_names))
    check("chunk_builder capability registered",
          any(c_["category"] == "chunk_builder" for c_ in caps))
    check("storage_provider capability registered",
          any(c_["category"] == "storage_provider" for c_ in caps))

    # ── Reprocess still works cleanly with the new manifest/lineage wiring ──
    r = c.post(f"{BASE}/documents/{doc_id}/process", headers=H)
    check("reprocess -> 200", r.status_code == 200, r.text[:200])
    state2 = wait_ready(c, H, doc_id)
    check("reprocess reaches knowledge_ready", state2.get("processing_status") == "knowledge_ready")
    r = c.get(f"{BASE}/documents/{doc_id}/manifest", headers=H)
    check("manifest still resolves after reprocess", r.status_code == 200, r.text[:200])
    check("correlation_id preserved across reprocess (Objective 4)",
          r.json().get("correlation_id") == processing_correlation_id,
          f"{r.json().get('correlation_id')} vs {processing_correlation_id}")

    # ── Ownership / 404 semantics on new endpoints ───────────────────────────
    r = c.get(f"{BASE}/documents/{uuid.uuid4()}/manifest", headers=H)
    check("unknown doc manifest -> 404", r.status_code == 404)
    r = c.get(f"{BASE}/documents/{uuid.uuid4()}/health", headers=H)
    check("unknown doc health -> 404", r.status_code == 404)
    r = c.get(f"{BASE}/documents/{uuid.uuid4()}/lineage", headers=H)
    check("unknown doc lineage -> 404", r.status_code == 404)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
