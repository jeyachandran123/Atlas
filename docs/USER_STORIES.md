# Atlas — Product User Stories

> Source of truth: **AI Coding Assistant — Platform Overview v1.0** (product vision) + the verified `dev` backend (FastAPI / LangGraph / Ollama / ChromaDB / MSSQL).
> This document is the development backlog for the Web App (primary client), backend services, and secondary clients (VS Code extension, CLI, IDE).

---

## How to read this document

**Story format**

```
[ID] Title
As a <persona>, I want <capability>, so that <benefit>.
AC: acceptance criteria (testable)
Priority: P0 (MVP) | P1 (V1) | P2 (V2)
Maps to: EXISTING <module>  |  NEW  |  EXTEND <module>
Depends on: <story IDs>
```

**Personas**

| Persona | Description |
|---|---|
| **Developer** | Primary user. Writes/reads code, debugs, asks about the repo. |
| **Tech Lead** | Reviews, manages repo access, cares about standards & quality. |
| **Business User** | Analyst / product / PM. Non-technical; uses document & knowledge features. |
| **Org Admin** | Manages organization, users, billing/plan, model config, audit. |
| **System** | Background workers, schedulers, internal services. |

**Priority key**
- **P0 — MVP**: required for a usable end-to-end product (connect repo → ask question → grounded answer).
- **P1 — V1**: the full single-team product described in the Platform Overview.
- **P2 — V2**: scale, additional clients, enterprise features.

**Status legend**
- `EXISTING` — implemented in the `dev` backend (may need hardening).
- `EXTEND` — partial implementation exists; needs additional work.
- `NEW` — not built yet.

---

## Scope map: Platform Overview vs. current backend

| Platform Overview capability | Backend today | Gap |
|---|---|---|
| Codebase understanding / Q&A | EXISTING (orchestrator, retriever, coding agent) | Hardening only |
| Repository-wide semantic search | EXISTING (retriever + MMR, indexer) | Search API surface |
| Code generation / feature assistance | EXISTING (coding agent + tools) | — |
| Bug investigation | EXISTING (tools + agent) | Dedicated intent/UX |
| Refactoring assistance | EXTEND (agent can, no dedicated flow) | Detectors |
| Test generation | EXISTING (intent `test`) | — |
| Code review | EXISTING (ReviewAgent) | — |
| Documentation generation | NEW | Generators + export |
| **Document Intelligence (PDF/Word/specs)** | **NEW** | Ingestion, parsing, indexing |
| **Presentation generation** | **NEW** | Generator + export (PPTX) |
| **Knowledge management (FAQ, meeting notes, onboarding, action items)** | **NEW** | Artifact generators + store |
| Knowledge discovery (cross-document Q&A) | EXTEND (code retrieval exists) | Multi-source retrieval |
| Web application | **NEW** | Entire frontend |
| VS Code extension / CLI / IDE | **NEW** | Clients + API contract |
| Memory / personalization | EXISTING (session + long-term) | — |
| Auth, RBAC, multi-tenant | EXISTING | Hardening |
| Observability / audit | EXISTING (OTel, Prometheus, AuditLog) | Dashboards |

---

# PART A — BACKEND USER STORIES

## Epic B1 — Identity, Authentication & Multi-tenancy
*Maps to: EXISTING `app/api/v1/auth`, `app/auth.py`, `app/db/models.py` (Organization, User, APIKey, RepositoryAccess)*

**[BE-AUTH-01] User registration**
As a Developer, I want to register with email + password under an organization, so that I can access the platform.
AC:
- `POST /api/v1/auth/register` creates a `User` bound to an `org_id`; password stored only as a hash.
- Duplicate (org_id, email) is rejected with 409.
- Returns the created user without the password hash.
Priority: P0 · Maps to: EXISTING · Depends on: —

**[BE-AUTH-02] Login & JWT issuance**
As a Developer, I want to log in and receive access + refresh tokens, so that my session is authenticated.
AC:
- Returns short-lived access token (15 min) + refresh token (7 days).
- Invalid credentials return 401 with no user enumeration.
- `last_login_at` is updated.
Priority: P0 · Maps to: EXISTING

**[BE-AUTH-03] Token refresh & logout**
As a Developer, I want to refresh an expired access token and to log out, so that I stay signed in securely.
AC: refresh endpoint issues a new access token; revoked/expired refresh tokens are rejected.
Priority: P0 · Maps to: EXTEND

**[BE-AUTH-04] API keys for non-web clients**
As a Developer, I want to create scoped API keys, so that the CLI/IDE extension can authenticate without my password.
AC:
- Raw key shown once at creation; only a hash is stored.
- Keys carry scopes and optional `expires_at`; `last_used_at` is tracked.
- Keys can be revoked.
Priority: P1 · Maps to: EXISTING (`APIKey`) · Depends on: BE-AUTH-02

**[BE-AUTH-05] Role-based access control**
As an Org Admin, I want admin/developer/viewer roles enforced, so that users only do what their role allows.
AC: viewer cannot write files or trigger indexing; developer cannot manage users; admin can.
Priority: P1 · Maps to: EXISTING (`User.role`)

**[BE-AUTH-06] Per-repository access control**
As a Tech Lead, I want to grant read/write/admin access per repository, so that the assistant only answers from repos a user may see.
AC:
- Every retrieval and file/git operation checks `RepositoryAccess`.
- Requests for unauthorized repos return 403 and are audited.
Priority: P0 · Maps to: EXISTING (`RepositoryAccess`)

## Epic B2 — Repository Connection & Indexing
*Maps to: EXISTING `app/api/v1/repositories`, `app/api/v1/indexing`, `app/indexing/*`, `app/workers/index_worker.py`*

**[BE-REPO-01] Connect a repository**
As a Developer, I want to connect a local or remote Git repository, so that the assistant can learn it.
AC: create `Repository` with provider (local/github/gitlab/bitbucket), `local_path`/`remote_url`, default branch; `index_status=pending`.
Priority: P0 · Maps to: EXISTING

**[BE-REPO-02] Trigger indexing (full)**
As a Developer, I want to start a full index of a connected repo, so that its code becomes searchable.
AC:
- Creates an `IndexJob` (`type=full`, `status=queued`); processed by the background worker.
- Scanner walks the repo honoring skip patterns; each file hashed with SHA256.
- AST chunker produces semantic chunks; embedder writes vectors to ChromaDB + `IndexedFile` rows.
- On completion, `Repository.index_status=ready`, counts populated.
Priority: P0 · Maps to: EXISTING · Depends on: BE-REPO-01

**[BE-REPO-03] Incremental re-indexing**
As a System, I want to re-index only files whose SHA256 changed, so that updates are fast.
AC: files with unchanged hash are skipped; deleted files have their chunks removed from ChromaDB.
Priority: P1 · Maps to: EXISTING (hash) / EXTEND (delete path)

**[BE-REPO-04] Indexing progress & status**
As a Developer, I want to see live indexing progress, so that I know when the repo is ready.
AC: `GET /repositories/{id}/index/status` returns files_total/processed/skipped, chunks_created, status, error.
Priority: P0 · Maps to: EXISTING (`IndexJob`)

**[BE-REPO-05] Cancel / retry index job**
As a Developer, I want to cancel a running index and retry a failed one, so that I can recover from problems.
AC: cancel sets `status=cancelled` and stops the worker; retry creates a new job.
Priority: P1 · Maps to: EXTEND

**[BE-REPO-06] Webhook-driven re-index**
As a Tech Lead, I want pushes to trigger incremental re-indexing, so that knowledge stays current.
AC: signed Git webhook enqueues an incremental `IndexJob` for the changed branch.
Priority: P2 · Maps to: NEW · Depends on: BE-REPO-03

## Epic B3 — Document Intelligence (NEW)
*Net-new per Platform Overview: ingest and answer over PDF, Word, requirement/functional specs, architecture & design docs, user manuals, knowledge-base docs.*

**[BE-DOC-01] Document upload & storage**
As a Business User, I want to upload PDF/Word/spec files, so that the assistant can answer from them.
AC:
- `POST /api/v1/documents` accepts PDF, DOCX, MD, TXT (configurable allowlist), max size enforced.
- File stored with org/repo scoping, checksum, content-type validated (not just extension).
- A `Document` record is created with status `pending`.
Priority: P0 (for doc-intelligence value) · Maps to: NEW · Depends on: BE-AUTH-06

**[BE-DOC-02] Document parsing & text extraction**
As a System, I want to extract clean text + structure from uploaded documents, so that they can be indexed.
AC:
- PDF and DOCX parsed to text with page/section boundaries preserved.
- Tables and headings retained as structural metadata where available.
- Parse failures recorded with a clear error; partial extraction allowed.
Priority: P0 · Maps to: NEW · Depends on: BE-DOC-01

**[BE-DOC-03] Document chunking & embedding**
As a System, I want documents chunked by section/heading and embedded, so that retrieval returns coherent passages.
AC: section-aware chunking with overlap; vectors stored in a `documents` collection keyed by `document_id`; `IndexedDocument`-style records persisted.
Priority: P0 · Maps to: NEW (reuse embedder) · Depends on: BE-DOC-02

**[BE-DOC-04] Connect a document source / batch**
As a Business User, I want to upload multiple documents and group them by project, so that I can query across a document set.
AC: documents can be tagged to a repo or a standalone "knowledge space"; batch upload supported.
Priority: P1 · Maps to: NEW · Depends on: BE-DOC-01

**[BE-DOC-05] Document lifecycle management**
As a Business User, I want to list, re-process, and delete documents, so that I control my knowledge base.
AC: delete removes vectors + record; re-process re-parses and re-embeds.
Priority: P1 · Maps to: NEW

## Epic B4 — Conversational AI & Agent Orchestration
*Maps to: EXISTING `app/agents/orchestrator.py` (LangGraph), `coding_agent`, `tool_planner`, `tool_executor`, `review_agent`*

**[BE-CHAT-01] Ask a question (non-streaming)**
As a Developer, I want to send a message and get a grounded answer, so that I can understand the project.
AC:
- `POST /api/v1/chat` runs the graph: route_intent → load_memory → retrieve_context → plan_tools → tool loop → (review) → finalise.
- Response includes answer, citations (files/chunks used), tokens, intent.
- Answers are grounded in indexed knowledge, not generic model knowledge.
Priority: P0 · Maps to: EXISTING

**[BE-CHAT-02] Streaming responses (SSE)**
As a Developer, I want tokens streamed as they generate, so that responses feel fast.
AC: `GET/POST /chat/stream` streams via SSE; client can cancel mid-stream; final message persisted.
Priority: P0 · Maps to: EXISTING (`orchestrator.stream`) · Depends on: BE-CHAT-01

**[BE-CHAT-03] Intent routing**
As a System, I want to detect intent (code/explain/search/fix/test/review), so that the right prompt/flow runs.
AC: keyword router today; pluggable to an LLM classifier; intent returned in the response.
Priority: P1 · Maps to: EXTEND (`_detect_intent`)

**[BE-CHAT-04] Autonomous tool use**
As a Developer, I want the agent to read files, search code, run safe commands, and inspect git as needed, so that answers are accurate.
AC: tool planner emits structured calls; executor runs them with timeout + isolation; max 5 iterations; tool failure never crashes the request.
Priority: P0 · Maps to: EXISTING · Depends on: BE-CHAT-01, BE-TOOL-*

**[BE-CHAT-05] Multi-source retrieval (code + documents)**
As a Business User, I want answers that draw from both code and uploaded documents, so that I get complete answers.
AC: retrieve_context queries code + document collections, merges/re-ranks, and labels each citation with its source type.
Priority: P1 · Maps to: EXTEND (retriever) · Depends on: BE-DOC-03

**[BE-CHAT-06] Citations & provenance**
As a Developer, I want every answer to cite the files/sections it used, so that I can trust and verify it.
AC: response carries a list of sources (path, lines/section, score); empty when nothing relevant was retrieved.
Priority: P0 · Maps to: EXTEND

## Epic B5 — Semantic Search & Retrieval
*Maps to: EXISTING `app/retrieval/retriever.py` (MMR), `app/retrieval/context_builder.py`*

**[BE-SEARCH-01] Intent-aware code search**
As a Developer, I want to search by meaning, not just keywords, so that I find code by what it does.
AC: `POST /search` embeds the query, fetches candidates, MMR re-ranks (λ=0.7), returns top-k diverse results with scores.
Priority: P0 · Maps to: EXISTING

**[BE-SEARCH-02] Symbol search**
As a Developer, I want to find a function/class by name, so that I can jump to a definition.
AC: exact symbol matches are boosted above semantic matches.
Priority: P1 · Maps to: EXISTING (`search_by_symbol`)

**[BE-SEARCH-03] Filtered search**
As a Developer, I want to filter search by language/file/chunk-type, so that I can narrow results.
AC: filters passed to the vector store; results respect filters.
Priority: P1 · Maps to: EXISTING

**[BE-SEARCH-04] Cross-document knowledge discovery**
As a Business User, I want to ask "what are the key features / integrations / user roles?" and get direct answers across documents, so that I avoid manual searching.
AC: query spans the document collection(s); returns a synthesized answer with per-document citations.
Priority: P1 · Maps to: NEW (uses BE-DOC-03 + BE-CHAT-05)

## Epic B6 — Code Generation & Feature Assistance
*Maps to: EXISTING coding agent + file/diff tools*

**[BE-GEN-01] Generate code from a request**
As a Developer, I want to generate services, endpoints, models, repositories, components, and validation logic, so that I write features faster.
AC: generation grounded in repo conventions retrieved from context; output returned as code blocks or diffs.
Priority: P0 · Maps to: EXISTING

**[BE-GEN-02] Apply generated changes to files**
As a Developer, I want to apply a generated diff to a file safely, so that I don't copy-paste manually.
AC: uses the robust diff applier (4 formats, 4 strategies); path-traversal protected; backup created; dry-run supported.
Priority: P1 · Maps to: EXISTING (`diff_applier`, `file_tool`) · Depends on: BE-FILE-02

## Epic B7 — Bug Investigation
**[BE-BUG-01] Diagnose from error/stack/log**
As a Developer, I want to paste an error, stack trace, or failing snippet and get likely root causes, so that I debug faster.
AC: `fix` intent triggers; agent retrieves impacted components and proposes causes + fixes referencing real files.
Priority: P1 · Maps to: EXISTING (intent `fix`)

## Epic B8 — Refactoring Assistance
**[BE-REFAC-01] Identify refactor opportunities**
As a Tech Lead, I want detection of duplicate code, unused logic, oversized functions, and reusable components, so that we keep the codebase clean.
AC: an analysis endpoint returns findings with file/line + suggested action.
Priority: P2 · Maps to: NEW (detectors) + EXISTING agent

## Epic B9 — Test Generation
**[BE-TEST-01] Generate tests**
As a Developer, I want unit/integration tests, edge cases, and mock data generated for a target, so that I improve coverage.
AC: `test` intent; output is runnable test code grounded in the target's signature/behavior; ReviewAgent validates.
Priority: P1 · Maps to: EXISTING

## Epic B10 — Code Review
*Maps to: EXISTING `app/agents/review_agent.py`*

**[BE-REVIEW-01] Adversarial review with revision loop**
As a Developer, I want generated code reviewed for bugs/security/edge cases before I see it, so that quality is higher.
AC: review runs on fix/test/review intents or when files changed; returns APPROVED or NEEDS_REVISION with specific feedback; max 2 revision cycles; failure degrades gracefully.
Priority: P1 · Maps to: EXISTING

## Epic B11 — Documentation Generation (NEW)
*Net-new per Platform Overview: API/module/service docs, technical guides, onboarding docs.*

**[BE-DOCGEN-01] Generate documentation for a target**
As a Developer, I want to generate API/module/service documentation from code, so that docs stay current with less effort.
AC: endpoint accepts a target (file/module/service); output is structured Markdown grounded in retrieved code; citations included.
Priority: P1 · Maps to: NEW

**[BE-DOCGEN-02] Generate onboarding / technical guide**
As a Tech Lead, I want an onboarding guide generated from the repo + docs, so that new hires ramp faster.
AC: produces a structured guide (setup, architecture, key flows) from indexed knowledge.
Priority: P2 · Maps to: NEW · Depends on: BE-CHAT-05

**[BE-DOCGEN-03] Export documentation**
As a Developer, I want to export generated docs as Markdown/PDF, so that I can share them.
AC: export endpoint returns the artifact in the requested format.
Priority: P2 · Maps to: NEW

## Epic B12 — Presentation Generation (NEW)
*Net-new per Platform Overview: outlines, project overview decks, architecture decks, doc→slide conversion, meeting-summary decks.*

**[BE-PRES-01] Generate presentation outline**
As a Business User, I want a slide outline generated from a document or repo, so that I can prep faster.
AC: returns an ordered slide structure (title + bullets + speaker notes) grounded in source content with citations.
Priority: P1 · Maps to: NEW · Depends on: BE-DOC-03

**[BE-PRES-02] Convert document to slide deck**
As a Business User, I want a document transformed into presentation-ready slides, so that documents and decks stay consistent.
AC: section-to-slide mapping; configurable depth; preserves key points.
Priority: P2 · Maps to: NEW · Depends on: BE-PRES-01

**[BE-PRES-03] Export presentation (PPTX)**
As a Business User, I want to export a generated deck to PPTX, so that I can present it.
AC: export produces a valid .pptx; renders titles, bullets, and notes.
Priority: P2 · Maps to: NEW

## Epic B13 — Knowledge Management (NEW)
*Net-new per Platform Overview: meeting summaries, action item lists, FAQs, onboarding docs, knowledge repositories.*

**[BE-KNOW-01] Generate meeting summary**
As a Business User, I want a meeting transcript/notes summarized, so that decisions are captured.
AC: input notes → structured summary; stored as a knowledge artifact.
Priority: P2 · Maps to: NEW

**[BE-KNOW-02] Extract action items**
As a Tech Lead, I want action items extracted from notes/threads, so that follow-ups aren't missed.
AC: returns owner/task/status list.
Priority: P2 · Maps to: NEW

**[BE-KNOW-03] Generate FAQ**
As a Business User, I want an FAQ generated from documents, so that common questions are answered once.
AC: produces Q/A pairs grounded in sources.
Priority: P2 · Maps to: NEW

**[BE-KNOW-04] Knowledge repository (store/retrieve artifacts)**
As a Team, I want generated artifacts saved to a centralized, searchable space, so that knowledge is reusable.
AC: artifacts persisted, listable, and retrievable via search.
Priority: P2 · Maps to: NEW

## Epic B14 — Memory & Personalization
*Maps to: EXISTING `app/memory/*`*

**[BE-MEM-01] Session memory**
As a Developer, I want the assistant to remember the recent conversation, so that follow-ups have context.
AC: last N messages stored in Redis with TTL; injected into context.
Priority: P0 · Maps to: EXISTING

**[BE-MEM-02] Long-term memory & consolidation**
As a Developer, I want important facts/preferences remembered across sessions, so that the assistant adapts to me.
AC: consolidation extracts facts post-conversation; relevant memories retrieved by query; user can delete a memory.
Priority: P1 · Maps to: EXISTING

## Epic B15 — Conversation Management
*Maps to: EXISTING `Conversation`, `Message` models + chat router*

**[BE-CONV-01] Conversation CRUD**
As a Developer, I want to create, list, rename, archive, and delete conversations, so that I organize my work.
AC: standard CRUD; messages loaded lazily; tokens tracked per conversation.
Priority: P0 · Maps to: EXTEND

**[BE-CONV-02] Conversation history retrieval**
As a Developer, I want to reopen a past conversation with full history, so that I continue where I left off.
AC: returns ordered messages with agent/tokens/latency metadata.
Priority: P1 · Maps to: EXISTING (model)

## Epic B16 — Git & File Operations
*Maps to: EXISTING `app/api/v1/files`, `app/api/v1/git`, `app/agents/tools/*`*

**[BE-FILE-01] Read file / list directory / search-in-file**
As a Developer, I want to read files and browse the tree through the API, so that the assistant and UI can show code.
AC: path-traversal protected; binary rejected; size-capped.
Priority: P0 · Maps to: EXISTING

**[BE-FILE-02] Write / patch file with safety**
As a Developer, I want to write or patch files safely, so that changes are controlled and reversible.
AC: realpath containment, size limit, backup on write, audited.
Priority: P1 · Maps to: EXISTING

**[BE-GIT-01] Read-only git operations**
As a Developer, I want status/diff/log/blame/branches via API, so that I can see repository state.
AC: read-only; scoped to authorized repo path.
Priority: P1 · Maps to: EXISTING

**[BE-TOOL-01] Sandboxed command execution**
As a System, I want shell commands run in an isolated sandbox, so that tool use is safe.
AC: ephemeral container, no network, CPU/mem/pid limits, blocklist, output cap, timeout; fallback mode flagged as non-isolated.
Priority: P1 · Maps to: EXISTING (`terminal_tool`) — *harden before prod: remove/secure non-sandboxed fallback*

## Epic B17 — Observability, Admin & Audit
*Maps to: EXISTING `app/observability.py`, `app/api/v1/admin`, `AuditLog`, `AgentExecution`*

**[BE-OBS-01] Metrics & tracing**
As an Org Admin, I want request metrics and distributed traces, so that I can monitor health and latency.
AC: Prometheus metrics + OTel traces emitted; per-request IDs propagated.
Priority: P1 · Maps to: EXISTING

**[BE-OBS-02] Audit trail**
As an Org Admin, I want security-relevant actions audited immutably, so that we meet compliance.
AC: file writes, command exec, access denials recorded with user/org/request id.
Priority: P1 · Maps to: EXISTING (`AuditLog`)

**[BE-ADMIN-01] Org / user / model administration**
As an Org Admin, I want to manage users, plans/limits, and per-org model config, so that I run the tenant.
AC: admin endpoints for user CRUD, repo/user limits, and `ModelConfig` (model, temperature, context window).
Priority: P1 · Maps to: EXISTING (`ModelConfig`)

**[BE-ADMIN-02] Rate limiting**
As an Org Admin, I want chat/index/search rate limits, so that the platform stays stable.
AC: configurable per-endpoint limits enforced; 429 with retry info.
Priority: P1 · Maps to: EXISTING (`rate_limit`)

## Epic B18 — Client Platform API
**[BE-API-01] Stable versioned API contract**
As a Client developer, I want a documented, versioned API (OpenAPI), so that web/CLI/IDE clients integrate reliably.
AC: `/api/v1` stable; OpenAPI published; auth via JWT (web) or API key (CLI/IDE); SSE contract documented.
Priority: P0 · Maps to: EXTEND · Depends on: BE-AUTH-04

---

# PART B — FRONTEND USER STORIES (Web Application)
*Net-new. The web app is the primary `Client Layer` interface; all backend epics surface here.*

## Epic F1 — Auth & Onboarding
**[FE-AUTH-01] Register / login / logout**
As a Developer, I want to sign up, log in, and log out, so that I can access my workspace securely.
AC: form validation, error states, token stored securely, auto-refresh, redirect on expiry.
Priority: P0 · Depends on: BE-AUTH-01/02/03

**[FE-AUTH-02] First-run onboarding**
As a new user, I want a guided first run (connect a repo or upload a document), so that I reach value quickly.
AC: empty-state walkthrough; completes when first repo/document is connected.
Priority: P1 · Depends on: FE-REPO-01, FE-DOC-01

## Epic F2 — Repository Dashboard & Indexing UX
**[FE-REPO-01] Connect repository**
As a Developer, I want to connect a repo via a form, so that I can index it.
AC: choose provider, path/url, branch; validation; shows in repo list as `pending`.
Priority: P0 · Depends on: BE-REPO-01

**[FE-REPO-02] Live indexing progress**
As a Developer, I want a progress indicator during indexing, so that I know when it's ready.
AC: progress bar with files processed/total, chunks, status; error surfaced with retry.
Priority: P0 · Depends on: BE-REPO-04

**[FE-REPO-03] Repository list & detail**
As a Developer, I want to see all my repos with status/last-indexed/counts, so that I can manage them.
AC: list with status badges; detail shows file/chunk counts, last commit, re-index/cancel actions.
Priority: P1 · Depends on: BE-REPO-04/05

## Epic F3 — Document Upload & Management (NEW)
**[FE-DOC-01] Upload documents**
As a Business User, I want to drag-and-drop PDF/Word/spec files, so that I can query them.
AC: multi-file upload, type/size validation, per-file progress + parse status.
Priority: P0 (doc value) · Depends on: BE-DOC-01/02

**[FE-DOC-02] Document library**
As a Business User, I want to browse, group, re-process, and delete documents, so that I manage my knowledge base.
AC: list with status, grouping by project/knowledge space, delete confirm.
Priority: P1 · Depends on: BE-DOC-04/05

## Epic F4 — Conversational Chat UI
**[FE-CHAT-01] Chat interface with streaming**
As a Developer, I want a chat window that streams responses, so that interaction feels live.
AC: message list, streaming tokens, stop button, markdown + syntax-highlighted code, copy buttons.
Priority: P0 · Depends on: BE-CHAT-02

**[FE-CHAT-02] Source citations panel**
As a Developer, I want to see and open the files/sections an answer used, so that I can verify it.
AC: citations listed per answer; clicking opens the referenced code/section; source-type labeled (code vs document).
Priority: P0 · Depends on: BE-CHAT-06, BE-CHAT-05

**[FE-CHAT-03] Repo/document context selector**
As a Developer, I want to pick which repo/documents a conversation is scoped to, so that answers are relevant.
AC: selector in the chat header; scope persisted on the conversation.
Priority: P1 · Depends on: BE-CONV-01

**[FE-CHAT-04] Quick-action prompts**
As a Developer, I want one-click prompts (explain, find, fix, test, review, document), so that I trigger common flows fast.
AC: buttons map to intents; prefilled prompt templates.
Priority: P2 · Depends on: BE-CHAT-03

## Epic F5 — Knowledge Discovery / Search UI
**[FE-SEARCH-01] Semantic search page**
As a Developer, I want a search box returning ranked code/doc results, so that I find things by meaning.
AC: results show snippet, path, score, source type; filters for language/type/source; click opens result.
Priority: P1 · Depends on: BE-SEARCH-01/04

## Epic F6 — Code Viewing & Change UX
**[FE-CODE-01] File/code viewer**
As a Developer, I want to view files referenced in answers/search, so that I read code in context.
AC: syntax highlighting, line numbers, jump-to-line from citations.
Priority: P1 · Depends on: BE-FILE-01

**[FE-CODE-02] Diff preview & apply**
As a Developer, I want to preview a generated diff and apply it, so that I accept changes safely.
AC: side-by-side/inline diff; apply triggers backend patch with backup; success/failure feedback.
Priority: P2 · Depends on: BE-GEN-02

## Epic F7 — Documentation Generation UI (NEW)
**[FE-DOCGEN-01] Generate & preview docs**
As a Developer, I want to generate docs for a target and preview/edit them, so that I publish quality docs.
AC: pick target → preview rendered Markdown → edit → export (MD/PDF).
Priority: P1 · Depends on: BE-DOCGEN-01/03

## Epic F8 — Presentation Generation UI (NEW)
**[FE-PRES-01] Generate & preview deck**
As a Business User, I want to generate a slide outline/deck from a doc or repo and preview slides, so that I prep presentations fast.
AC: source selector → slide preview (title/bullets/notes) → export PPTX.
Priority: P1 · Depends on: BE-PRES-01/03

## Epic F9 — Knowledge Artifacts UI (NEW)
**[FE-KNOW-01] Generate knowledge assets**
As a Business User, I want to create meeting summaries, action items, FAQs, and onboarding docs from sources, so that knowledge is captured and shared.
AC: input/source selection → generate → preview/edit → save to knowledge space.
Priority: P2 · Depends on: BE-KNOW-01..04

## Epic F10 — Conversation History & Management
**[FE-CONV-01] Conversation sidebar**
As a Developer, I want a list of past conversations with rename/archive/delete, so that I organize my work.
AC: sidebar list; search; reopening restores full history.
Priority: P1 · Depends on: BE-CONV-01/02

## Epic F11 — Settings, Team & Admin UI
**[FE-ADMIN-01] Profile & API keys**
As a Developer, I want to manage my profile and API keys, so that I configure CLI/IDE access.
AC: create/revoke keys (raw shown once), edit profile.
Priority: P1 · Depends on: BE-AUTH-04

**[FE-ADMIN-02] Team & repo access management**
As a Tech Lead, I want to manage members and per-repo access, so that I control who sees what.
AC: invite/remove users, set roles, grant/revoke repo access.
Priority: P1 · Depends on: BE-AUTH-05/06

**[FE-ADMIN-03] Org admin console**
As an Org Admin, I want to manage plan limits, model config, and view audit/usage, so that I run the tenant.
AC: model config form, usage charts, audit log viewer.
Priority: P2 · Depends on: BE-ADMIN-01, BE-OBS-01/02

## Epic F12 — Global UX & Non-Functional (Frontend)
**[FE-UX-01] Responsive, accessible, themed UI**
As any user, I want a responsive, accessible (WCAG AA), light/dark UI, so that the app is usable everywhere.
AC: keyboard nav, ARIA, contrast, mobile/tablet layouts.
Priority: P1

**[FE-UX-02] Loading, empty, and error states**
As any user, I want clear loading/empty/error states, so that I always know what's happening.
AC: skeletons, retry actions, friendly error messages with request id.
Priority: P0

---

# PART C — Secondary Clients

## Epic C1 — VS Code Extension (NEW)
**[EXT-01] Authenticate via API key** — connect the extension to a workspace. P2 · Depends on: BE-AUTH-04
**[EXT-02] Ask about selection / file** — query the assistant about highlighted code. P2 · Depends on: BE-CHAT-02
**[EXT-03] Inline diff apply** — apply suggested changes in-editor. P2 · Depends on: BE-GEN-02

## Epic C2 — CLI (NEW)
**[CLI-01] Auth & config** — `atlas login` with API key. P2 · Depends on: BE-AUTH-04
**[CLI-02] Ask / search from terminal** — `atlas ask "..."`, `atlas search "..."`. P2 · Depends on: BE-CHAT-01, BE-SEARCH-01
**[CLI-03] Index a local repo** — `atlas index .`. P2 · Depends on: BE-REPO-02

## Epic C3 — IDE Integrations (JetBrains, etc.) (NEW)
**[IDE-01] Basic query integration** — parity with EXT-02 in JetBrains IDEs. P2

---

# PART D — Cross-Cutting Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-01 | Local-first / privacy | No code or documents leave the deployment; all inference via local Ollama |
| NFR-02 | Chat latency | First token < 2s on warm model; full short answer < 10s |
| NFR-03 | Indexing throughput | Handle 100k+ file repos; incremental re-index of changed files only |
| NFR-04 | Security | Path-traversal protection, sandboxed exec, RBAC + per-repo ACL on every data path, secrets never logged |
| NFR-05 | Reliability | Graceful degradation when ChromaDB/Ollama down; tool failures isolated |
| NFR-06 | Observability | Metrics, traces, audit on all security-relevant actions |
| NFR-07 | Scalability | Stateless API; background worker queue; vector store abstracted (ChromaDB→Qdrant) |
| NFR-08 | Test & quality gates | Lint (ruff) + format (black) + types (mypy) + tests ≥75% coverage enforced in CI |
| NFR-09 | Accessibility | Web app meets WCAG 2.1 AA |
| NFR-10 | API stability | Versioned `/api/v1`, published OpenAPI, documented SSE contract |

---

# PART E — Release / Milestone Plan

### Milestone 0 — Production hardening (prerequisite, from repo verification)
- Unblock DB (Postgres or ODBC fix), fix package build, add CI (lint/format/type/test), run full suite. *(Not user stories — engineering gate before product work.)*

### MVP (P0) — "Connect → Ask → Grounded answer", web app
BE-AUTH-01/02/06, BE-REPO-01/02/04, BE-CHAT-01/02/04/06, BE-SEARCH-01, BE-GEN-01, BE-MEM-01, BE-CONV-01, BE-FILE-01, BE-API-01
FE-AUTH-01, FE-REPO-01/02, FE-CHAT-01/02, FE-UX-02
+ Document MVP: BE-DOC-01/02/03, FE-DOC-01 (enables the document-intelligence differentiator)

### V1 (P1) — Full single-team product (matches Platform Overview)
BE-AUTH-03/04/05, BE-REPO-03/05, BE-CHAT-03/05, BE-SEARCH-02/03/04, BE-GEN-02, BE-BUG-01, BE-TEST-01, BE-REVIEW-01, BE-DOCGEN-01, BE-PRES-01, BE-MEM-02, BE-CONV-02, BE-FILE-02, BE-GIT-01, BE-TOOL-01, BE-OBS-01/02, BE-ADMIN-01/02, BE-DOC-04/05
FE-AUTH-02, FE-REPO-03, FE-DOC-02, FE-CHAT-03, FE-SEARCH-01, FE-CODE-01, FE-DOCGEN-01, FE-PRES-01, FE-CONV-01, FE-ADMIN-01/02, FE-UX-01

### V2 (P2) — Scale, knowledge management, multi-client
BE-REPO-06, BE-REFAC-01, BE-DOCGEN-02/03, BE-PRES-02/03, BE-KNOW-01..04
FE-CHAT-04, FE-CODE-02, FE-KNOW-01, FE-ADMIN-03
Clients: EXT-01..03, CLI-01..03, IDE-01

---

*Generated as the development backlog. Each story is intended to become a tracked issue; IDs are stable references for branches/PRs/commits.*
