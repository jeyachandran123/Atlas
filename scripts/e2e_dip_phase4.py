"""
DIP Phase 4 — Conversational Knowledge Intelligence verification.

Covers: grounded Q&A with citations, intent classification, graceful
refusal for unsupported requests, honest refusal when no knowledge matches,
conversation memory (follow-up), SSE streaming, per-turn events and
metrics, and ownership/404 semantics.
"""
import json
import sys
import time
import uuid

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
EMAIL = f"p4-{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = "p4-password-123"

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


DOC_TEXT = (
    "UnityWorks Platform Service Agreement.\n\n"
    "The standard warranty period for all UnityWorks hardware products is 36 months "
    "from the date of purchase.\n\n"
    "Support tickets are answered within 4 business hours for premium customers "
    "and within 2 business days for standard customers.\n\n"
    "The annual subscription fee for the Enterprise tier is 4800 euros, "
    "billed yearly in advance.\n"
)

with httpx.Client(timeout=300) as c:
    r = c.post(f"{BASE}/auth/register", json={
        "email": EMAIL, "password": PASSWORD, "full_name": "P4 E2E",
        "role": "developer", "org_id": "default",
    })
    if r.status_code not in (200, 201):
        sys.exit(f"REGISTER_FAILED {r.status_code} {r.text[:200]}")
    r = c.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    H = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # ── Seed knowledge: upload + wait for semantic readiness ─────────────────
    r = c.post(f"{BASE}/documents/upload", headers=H, files={
        "file": ("agreement.txt", DOC_TEXT.encode(), "text/plain")
    })
    check("upload -> 201", r.status_code == 201, r.text[:200])
    doc_id = r.json()["document"]["id"]

    deadline = time.time() + 90
    sem_ready = False
    while time.time() < deadline:
        rs = c.get(f"{BASE}/documents/{doc_id}/semantic", headers=H)
        if rs.status_code == 200 and rs.json().get("status") == "indexed":
            sem_ready = True
            break
        time.sleep(1.5)
    check("document embedded and semantically indexed", sem_ready)

    # ── Conversation lifecycle ───────────────────────────────────────────────
    r = c.post(f"{BASE}/conversations", headers=H, json={"title": "P4 test"})
    check("create conversation -> 201", r.status_code == 201, r.text[:200])
    conv = r.json()
    conv_id = conv["id"]
    check("conversation has correlation_id", len(conv.get("correlation_id", "")) == 36)

    r = c.get(f"{BASE}/conversations", headers=H)
    check("list conversations includes it",
          r.status_code == 200 and any(x["id"] == conv_id for x in r.json()))

    # ── Grounded Q&A with citations ──────────────────────────────────────────
    r = c.post(f"{BASE}/conversations/{conv_id}/ask", headers=H,
               json={"question": "What is the warranty period for hardware products?"})
    check("ask -> 200", r.status_code == 200, r.text[:300])
    turn = r.json()
    check("turn status == completed", turn.get("status") == "completed", str(turn.get("status")))
    check("answer is grounded", turn.get("grounded") is True, json.dumps(turn)[:300])
    check("answer mentions 36 months", "36" in (turn.get("answer") or ""),
          (turn.get("answer") or "")[:200])
    check("intent classified as question_answering",
          turn.get("intent") == "question_answering", str(turn.get("intent")))
    check("at least one citation", len(turn.get("citations", [])) >= 1)
    if turn.get("citations"):
        cit = turn["citations"][0]
        check("citation references the uploaded document",
              cit.get("document_id") == doc_id, f"{cit.get('document_id')} vs {doc_id}")
        check("citation carries knowledge_id", len(cit.get("knowledge_id", "")) == 36)
        check("citation carries chunk ids", len(cit.get("chunk_ids", [])) >= 1)
        check("citation confidence in (0,1]", 0 < cit.get("confidence", 0) <= 1.0)
    check("grounding_score present and above zero",
          (turn.get("grounding_score") or 0) > 0, str(turn.get("grounding_score")))
    m = turn.get("metrics", {})
    check("metrics: retrieval latency captured", isinstance(m.get("retrieval_ms"), int))
    check("metrics: llm latency captured", isinstance(m.get("llm_ms"), int) and m["llm_ms"] > 0)
    check("metrics: real token counts from provider",
          isinstance(m.get("prompt_tokens"), int) and m["prompt_tokens"] > 0, str(m))
    check("metrics: citation_count matches", m.get("citation_count") == len(turn.get("citations", [])))
    first_turn_id = turn["turn_id"]

    # ── Conversation memory: follow-up that only resolves via history ────────
    r = c.post(f"{BASE}/conversations/{conv_id}/ask", headers=H,
               json={"question": "And how much does that cost per year for the Enterprise tier?"})
    check("follow-up -> 200", r.status_code == 200, r.text[:300])
    follow = r.json()
    check("follow-up completed and grounded",
          follow.get("status") == "completed" and follow.get("grounded") is True,
          json.dumps(follow)[:300])
    check("follow-up answer mentions 4800", "4800" in (follow.get("answer") or ""),
          (follow.get("answer") or "")[:200])

    # ── Unsupported request fails gracefully (no LLM, no hallucination) ──────
    r = c.post(f"{BASE}/conversations/{conv_id}/ask", headers=H,
               json={"question": "Generate a PDF report of the agreement"})
    check("unsupported request -> 200 (graceful)", r.status_code == 200, r.text[:200])
    uns = r.json()
    check("unsupported intent detected", uns.get("intent") == "unsupported", str(uns.get("intent")))
    check("unsupported refusal reason set",
          uns.get("refusal_reason") == "unsupported_request", str(uns.get("refusal_reason")))
    check("unsupported not grounded, no citations",
          uns.get("grounded") is False and not uns.get("citations"))

    # ── No-knowledge question: honest grounded refusal, never a made-up answer
    r = c.post(f"{BASE}/conversations/{conv_id}/ask", headers=H,
               json={"question": "What is the boiling point of tungsten on Mars?"})
    check("off-knowledge ask -> 200", r.status_code == 200, r.text[:200])
    off = r.json()
    check("off-knowledge answer is not grounded", off.get("grounded") is False,
          json.dumps(off)[:300])
    check("off-knowledge refusal reason present",
          off.get("refusal_reason") in ("no_knowledge_found", "low_confidence")
          or (off.get("refusal_reason") or "").startswith("validation_failed"),
          str(off.get("refusal_reason")))

    # ── Streaming ────────────────────────────────────────────────────────────
    events_seen = []
    tokens = []
    stream_done = {}
    with c.stream("POST", f"{BASE}/conversations/{conv_id}/ask/stream", headers=H,
                  json={"question": "How fast are support tickets answered for premium customers?"}) as resp:
        check("stream -> 200 event-stream", resp.status_code == 200
              and "text/event-stream" in resp.headers.get("content-type", ""))
        current_event = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                current_event = line[7:]
                events_seen.append(current_event)
            elif line.startswith("data: ") and current_event:
                payload = json.loads(line[6:])
                if current_event == "token":
                    tokens.append(payload.get("text", ""))
                elif current_event == "done":
                    stream_done = payload
                elif current_event == "citations":
                    stream_citations = payload
    check("stream emitted meta first", events_seen and events_seen[0] == "meta", str(events_seen[:3]))
    check("stream emitted tokens", len(tokens) > 0, str(len(tokens)))
    check("stream emitted citations event", "citations" in events_seen)
    check("stream emitted done", "done" in events_seen)
    streamed_text = "".join(tokens)
    check("streamed answer mentions 4 business hours",
          "4" in streamed_text, streamed_text[:200])
    check("streamed turn completed", stream_done.get("status") == "completed", str(stream_done))

    # ── Turn history + per-turn events (Objectives 13/14/15) ─────────────────
    r = c.get(f"{BASE}/conversations/{conv_id}/turns", headers=H)
    check("turns list -> 200", r.status_code == 200)
    turns = r.json()
    check("all 5 turns recorded", len(turns) == 5, str(len(turns)))
    check("turn seq is monotonic", [t["seq"] for t in turns] == [1, 2, 3, 4, 5])

    r = c.get(f"{BASE}/conversations/{conv_id}/turns/{first_turn_id}/events", headers=H)
    check("turn events -> 200", r.status_code == 200)
    evs = [e["event_type"] for e in r.json()]
    for expected in ("intent_detected", "retrieval_completed", "ranking_completed",
                     "context_built", "prompt_generated", "reasoning_completed",
                     "response_validated", "response_completed"):
        check(f"event stream contains {expected}", expected in evs, str(evs))

    # ── Ownership / 404 semantics ────────────────────────────────────────────
    r = c.post(f"{BASE}/conversations/{uuid.uuid4()}/ask", headers=H,
               json={"question": "hi"})
    check("unknown conversation ask -> 404", r.status_code == 404)
    r = c.get(f"{BASE}/conversations/{uuid.uuid4()}/turns", headers=H)
    check("unknown conversation turns -> 404", r.status_code == 404)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
