# Web search in chat — design

**Date:** 2026-09-21
**Status:** approved, in implementation
**Scope:** the main chat assistant only (`POST /api/v1/chat/stream`, cognitive path)

## What this adds

When a question needs current information, the assistant searches the web, reads the
pages that matter, and answers from what it found — with the sources shown as cards
the user can click.

Out of scope: the Knowledge Workspace / DIP. Its grounding contract requires every
answer to cite the user's own documents; mixing web sources into it would break that
guarantee and needs its own design.

## Decisions taken

| Decision | Choice | Why |
|---|---|---|
| Provider | You.com Search API + Contents API | One call returns results *and* cleaned page text *and* thumbnails. 100 free calls/day, then $5/1k. `X-API-Key` header, `POST https://ydc-index.io/v1/search`. |
| Trigger | Automatic, plus a manual toggle | The model decides; the toggle is the escape hatch when it decides wrong. |
| Images | Up to 2 per-result thumbnails, shown only when the decision model sets `images: true` | You.com has no image-search section, so these are page previews from the same call — no second provider and no extra cost. The flag rides on the decision call that already happens. |
| Source list | A vertical bordered list: favicon, title, domain right-aligned, under a "Searched the web" header with the query as a chip | Reads as one block; a horizontal card row made the user scroll sideways to see what was found. |
| Rounds | One search, then at most one read round of ≤2 pages | A single round finds a price but misses an endpoint. Two rounds is what a person does. A third is where cost and latency run away. |
| Persistence | New `message_sources` table | `messages` has no JSON column, and `MessageImage` / `MessageDocument` are the house pattern for exactly this. |
| Answer generation | Our own model, our own persona | You.com's Research API would write the answer in its own voice, discarding the tuned persona. |

## Flow

```
stream_message
  ├─ file request?   → unchanged
  ├─ has documents?  → unchanged
  └─ cognitive path
       ├─ 1. worth_searching(message)        pattern gate, no LLM
       ├─ 2. decide()                        small LLM call → {search: bool, queries: [≤3]}
       ├─ 3. provider.search(queries)        You.com, with highlights extraction
       ├─ 4. enough?                         one LLM check → ≤2 URLs to read in full
       ├─ 5. provider.contents(urls)         You.com Contents
       ├─ 6. emit `sources` event            cards render before the first token
       └─ 7. stream the answer               sources injected as one system turn
```

The manual toggle skips steps 1–2.

## Modules

`backend/app/web_search/`

| File | Responsibility | Depends on |
|---|---|---|
| `schemas.py` | `WebSource`, `SearchPlan`, `SearchOutcome` | nothing |
| `decision.py` | `worth_searching`, decide/follow-up prompts, JSON parsing | nothing (pure) |
| `provider.py` | `SearchProvider` protocol + `YouComProvider` | httpx, config |
| `context.py` | Turn sources into the system turn the model reads | schemas |
| `service.py` | Runs the flow, yields SSE events | all of the above |

Existing files changed:

- `app/api/v1/chat/router.py` — wire the service in before `_stream_cognitive_response`;
  emit `sources`; persist rows on `done`.
- `app/cognitive_integration/pipeline.py` — `with_web_context(delib, turn)` inserts the
  sources turn **before** `_STYLE_REMINDER`, which must stay last (asserted by
  `test_the_voice_reminder_comes_last_before_the_new_message`).
- `app/db/models.py` + a migration — `message_sources`.
- `app/config.py` — settings below.

## Settings

| Key | Default | Meaning |
|---|---|---|
| `WEB_SEARCH_ENABLED` | `true` | Master switch. Off → chat behaves exactly as today. |
| `YOU_API_KEY` | `""` | Empty is treated as disabled, not as an error. |
| `WEB_SEARCH_DAILY_CAP` | `80` | Searches per day across the deployment, counted in Redis. Below You.com's 100/day free tier. |
| `WEB_SEARCH_MAX_RESULTS` | `6` | Results kept per query. |
| `WEB_SEARCH_TIMEOUT_S` | `12` | Per HTTP call. |
| `WEB_SEARCH_COUNTRY` | `SG` | Regional bias for results. |

## Failure handling

Every failure path answers the question without the web rather than failing the turn.
A search that cannot run is a missing improvement, never a lost reply. This mirrors
`_maybe_stream_file_response`, which returns `None` on any decision error.

Specifically: no API key, cap reached, HTTP error, timeout, malformed JSON, zero
results — all fall through to the normal cognitive stream, logged at `warning`.

## Testing

Pure logic (`decision.py`, `context.py`) is unit-tested directly. `provider.py` is
tested against a stubbed httpx transport — no live calls in the suite, so the test
run costs nothing and works offline. The service is tested with a fake provider,
asserting the event sequence and that a provider raising still yields an answer.

## What live calls corrected

Three assumptions failed against the real API and the real model. Each was
found by running it, not by reading it:

1. **`contents` is an object, not a string** — `{"highlights": [...]}` under
   highlights extraction, `{"markdown": "..."}` under full_page, and absent
   entirely on plain results, which carry `snippets` instead. Reading it as a
   string gave every source an empty extract while reporting a successful
   search, so the model was answering from titles alone.
2. **The decision model read "who is the chief minister" as a fact question**
   and returned `images: false`. The prompt now says an office holder is still
   a person, and that `images: true` requires `search: true`, because pictures
   come from search results.
3. **"show me the eiffel tower" never reached the web** — the pattern gate
   rejected it as small talk, so the one thing asked for was the one thing it
   could not return. `_WANTS_TO_SEE` now passes those straight through.

## Known limits

- One read round. A question needing three hops gets two.
- Citation markers `[1]` depend on the model following instructions; this model
  ignored formatting rules in prior testing. Source cards are built from search data,
  not from the model's text, so links survive regardless.
- The classic orchestrator fallback path (used when the brain returns `None`) gets no
  web context in this version.
