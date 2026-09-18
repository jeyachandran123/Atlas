---
role: tech-lead
date: 2026-09-17
refs: backend dc9515c, frontend a1bc2f7
inputs: [ai-ml-architect.md, qa-engineer.md, ux-architect.md, frontend-engineer.md]
area: "why the agent chat feels very like a bot ... it should explain things inch by inch, and the chat UI should be better"
---

# Verdict
**ship after blockers.** There is one blocker. At backend lines `app/api/v1/chat/router.py:456-458` and `:1116`, the document-chat branch still streams a model reply after the intelligence engine has blocked the request (ai-ml-architect#8). That breaks the documented rule that a blocked request never reaches the LLM. The evidence is a grep plus the contrasting orchestrator code, not a mutation, so remediation step 1 starts with the test that proves it. If that test passes on dc9515c, drop the finding.

Apart from the blocker, the reports agree on why the chat feels like a bot. It is mostly deliberate instruction and error handling on the path that actually serves chat, not a model limit:
- A substring keyword gate holds harmless questions.
- The live `_STREAM_SYSTEM` prompt ties reply length to message length and holds back warmth.
- Replies are silently cut at 2048 tokens.
- Streamed text is wiped on error.
- Raw exception strings reach the user.

**Do not ship any prompt or voice change until two things exist.** First, the guard tests in steps 3-5, because 13 of 13 tone and depth mutations currently leave the suite green (qa-engineer). Second, the baseline voice measurement in step 6. No model was called in any review, so every claim about how a reworded prompt will *read* is still unmeasured.

Counts after triage: 62 findings filed. 2 were returned for evidence. 9 merges folded the rest into **51 ranked findings: 1 blocker, 20 major, 22 minor, 8 note.**

## Remediation order

### Phase 0 — prove the blocker, then build the guards every later change depends on
| # | Finding (source#n) | Severity | Depends on | Why this position |
|---|---|---|---|---|
| 1 | Document-chat branch calls the model after a policy block. Fix at backend `app/api/v1/chat/router.py:456-458` and `:1116`, streaming `engine_result.block_response` the way `orchestrator.py:216-222` does (ai-ml-architect#8) | **blocker** (re-rated from major) | — | Broken invariant. Write the test first: a stub engine with `is_blocked=True` and a fake `DocumentService` whose `chat_stream` raises. It must fail at dc9515c before the fix. Step 11 edits the same lines, so this lands first. |
| 2 | Declare `aiosqlite` as a test dependency. The chat integration tests cannot import, and none of them hit `/chat/stream` (`tests/conftest.py:46`) (qa-engineer#13) | note | — | Route-level tests in steps 3 and 7 cannot run without it. |
| 3 | Add a route test for `_stream_cognitive_response` (backend `router.py:520`, call at `:547-551`) that asserts `system_prompt`, `history`, `profile`, and that an escalated turn never calls `chat_stream` (qa-engineer#1) | major | 2 | This is the only guard that the persona and history reach the model. It must exist before steps 7-10 change what is sent. |
| 4 | Assert `deliberate()` sends `_STREAM_SYSTEM` and `_stream_history(turn.history)` (`pipeline.py:249-251`, test at `test_cognitive_chat_slice.py:111`) (qa-engineer#3) | major | — | Mutations M3 and M4 survived. This guards the history change in step 10. |
| 5 | Add prompt-structure tests: no length cap or format ban outside the acknowledgement clause, and the reminder agrees with the persona (`tests/cognitive_integration/test_stream_turns.py:80-145`; today the reminder check compares an object to itself at `:65`) (qa-engineer#2) | major | — | Tautological guard. The prompt rewrite in step 8 needs a test that catches a regression back to terse output. |
| 6 | Voice-evaluation harness and baseline (`scripts/e2e_chat_voice.py`, protocol under "Unmeasured claims" in ai-ml-architect.md). Also add a pytest case that "ok" and "explain step by step" produce different instructions (qa-engineer#4 recommendation) | prerequisite | — | Steps 8 and 9 have acceptance thresholds (walkthrough in ≥5/6 samples, stock openers ≤2/6, truncation 0/6) that need a recorded baseline first. |

### Phase 1 — backend voice and depth (backend repo)
| # | Finding (source#n) | Severity | Depends on | Why this position |
|---|---|---|---|---|
| 7 | Substring danger list escalates "How do I format a date in Python?" and "delete a git branch" to a canned hold, and the model is never called (`app/cognitive_integration/adapters_prod.py:48-49`, `:66-71`; `pipeline.py:28-32`; `router.py:538-541`) (ai-ml-architect#1) | major | 3 | Highest-impact "bot" signal, backed by the strongest evidence (an executed probe of the production adapter). Keep the Executive gate. Add `tests/cognitive_integration/test_intent_risk.py` with the six must-not-escalate cases and the must-escalate cases. |
| 8 | **Land together, as one prompt change:** (a) "A one-line question gets a short answer" / "match … their length" sends step-by-step requests the same instruction as "ok" (`pipeline.py:55-58`, `:72-73`) (ai-ml-architect#2 = qa-engineer#4). (b) No step-by-step walkthrough rule in the prompt or the reminder (`pipeline.py:39-128`, `:175-187`) (ai-ml-architect#4). (c) Warmth held back by design (`pipeline.py:41`, `:52-54`, `:85-87`, `:181-182`) (ai-ml-architect#3). Update `test_stream_turns.py:137-138` in the same commit. | major ×3 | 4, 5, 6; deploy with 15 | All three edit the same two strings and share one measurement. Changing them separately would mean three rounds of eval. Longer answers make step 15's rendering cost worse, so do not deploy ahead of it. |
| 9 | **Land together:** (a) the GENERAL profile caps replies at 2048 tokens and `finish_reason` is dropped (`app/llm/profiles.py:116-120`; `app/ollama_client.py:319-326`; `router.py:560-574`) (ai-ml-architect#5). (b) The only budget test is a relative comparison (`tests/unit/test_llm_gateway.py:125`) (qa-engineer#5). | major ×2 | 6, 8, 12 (contract), 15 | Step 8 makes truncation more frequent. Raise the budget by measurement (4096 vs 2048) and add an absolute floor test in the same commit. The `truncated` flag in the `done` frame belongs to the step 12 contract. |
| 10 | Earlier assistant turns are trimmed to 2000 characters, so "go deeper on step 4" loses step 4 (`pipeline.py:150-151`, `:162`) (ai-ml-architect#6) | major | 4 | Needed for step-by-step follow-ups. Guarded by step 4. |
| 11 | A conversation with an attached document switches to the older "You are Atlas" persona and pastes history as a transcript (`app/documents/service.py:181`, `:190-196`; `router.py:440-458`) (ai-ml-architect#7) | major | 1, 8 | Reuses the voice module from step 8 and edits the router lines fixed in step 1. |

### Phase 2 — streaming contract (backend emits first, then `frontend/types/api.ts` in the same frontend commit)
| # | Finding (source#n) | Severity | Depends on | Why this position |
|---|---|---|---|---|
| 12 | **One contract change to the SSE frames**, each frame added to `ChatStreamEvent`: (a) error frame carries a stable `code` and a human sentence, never `str(e)`: backend `router.py:856` plus sibling sites, 5 in router.py per frontend-engineer and 8 across `app/api` + `app/workspace` per ux-architect (ux-architect#2 = frontend-engineer#2). (b) `done.truncated` (ai-ml-architect#5). (c) a `status` / `tool_call` stage event during the pre-reply wait (`router.py:760-790`), since no backend path emits `tool_call` today (frontend-engineer#6, absorbs ux-architect#10). (d) backend saves the partial reply on disconnect or error in a `finally` (`router.py:814-856`) (backend half of ux-architect#1). | major | 9 (for b) | Every frontend fix in phase 3 consumes these frames. Define the contract once, not four times. The error text may also expose internals (SQLAlchemy/httpx messages); no security reviewer looked at this. |
| 13 | Frontend: streamed text and reasoning vanish when an error arrives (and, per ux-architect, when the user presses Stop). Fix `components/chat/chat-thread.tsx:56`, `:349`; render the error sentence in full at `:364` and `lib/api/chat.ts:109` (frontend-engineer#1 = ux-architect#1; frontend-engineer#2 = ux-architect#2) | major ×2 | 12 | Uses the error `code` from step 12 for the inline "interrupted" message. |
| 14 | Frontend: render the stage events as a first-person running line that folds into "What I did". Let the rationale wrap at full contrast (`lib/stores/chat-store.ts:147-155`, `components/chat/tool-call-indicator.tsx:17-42`, `:35`) (frontend-engineer#6, ux-architect#10). Handle `clarify` (`chat-store.ts:134-162`) (frontend-engineer#13, minor) | major | 12 | Consumer of 12(c). |

### Phase 3 — frontend chat UI (frontend repo). Set up vitest first: there is no test config (qa-engineer#14), and every recommendation below names a component test.
| # | Finding (source#n) | Severity | Depends on | Why this position |
|---|---|---|---|---|
| 15 | Every token re-parses the whole markdown message, measured at 38 ms per token at 18k characters (`chat-store.ts:144-145`, `streaming-message-bubble.tsx:127`, `message-markdown.tsx:84`) (frontend-engineer#4) | major | vitest setup | Must be live before steps 8 and 9 produce long answers. |
| 16 | Edit and Retry resend in `"auto"` whatever mode is selected (`lib/hooks/use-chat.ts:385`, `:397`) (ux-architect#3 = frontend-engineer#10). Group with: edit/regenerate delete DB rows but not the Redis session (backend `router.py:1259-1297`, `:1301-1333`) (ai-ml-architect#9, minor) | major (re-rated from minor in frontend-engineer) | — | Both break the same user action: regenerate a disliked answer. Ship the two together so a regenerate actually changes the reply. |
| 17 | Stream POST skips the single-flight 401 refresh (`lib/api/chat.ts:66-110` vs `client.ts:25-63`) (frontend-engineer#3) | major | — | Independent. After a laptop sleeps, the next send fails with a raw 401. |
| 18 | A code fence with no language loses styling and the Copy button, and `pre` wraps `div` (`components/chat/message-markdown.tsx:93-96`) (frontend-engineer#5) | major | vitest setup | Independent. Shell steps in walkthroughs are usually untagged fences. |
| 19 | Workspace thread smooth-scrolls to the bottom on every token (`components/workspace/conversation-view.tsx:185`) (ux-architect#4) | major | — | Pull the follow/pin logic from `chat-thread.tsx:108-236` into a shared hook. |
| 20 | A network failure on a workspace question leaves no reply and no retry (`conversation-view.tsx:250`, `:632-637`) (ux-architect#5) | major | — | Independent. |

### Minors and notes (after the majors, in this order; each independent unless stated)
| # | Finding (source#n) | Severity | Depends on |
|---|---|---|---|
| 21 | Model memory lives only in Redis with a 24h TTL; hydrate from the DB (backend `app/redis_client.py:50-51`, `router.py:747`) (ai-ml-architect#10) | minor | 16 (same session-key rebuild) |
| 22 | Ollama branch streams at literal temperature 0.1 (`app/ollama_client.py:439`) (ai-ml-architect#11) | minor | only if a deployment uses `LLM_PROVIDER=ollama` |
| 23 | Reasoning panel unmounts on `done` (`chat-thread.tsx:350`) (frontend-engineer#7 = ux-architect#16) | minor | product decision on saving a reasoning summary |
| 24 | Caret renders on its own line; the saved reply jumps at handover (`streaming-message-bubble.tsx:126-131`) (frontend-engineer#8 = ux-architect#20) | minor | 15 (same render path) |
| 25 | Proxy buffers SSE when `NEXT_PUBLIC_STREAM_BASE_URL` is unset (`app/api/backend/[...path]/route.ts:57`, `.env.example:4-7`) (frontend-engineer#12) | minor | — |
| 26 | Hover-only message actions (`message-bubble.tsx:274`, `:309`) (ux-architect#7) · no `aria-live` on the answer (`streaming-message-bubble.tsx:126-133`) (ux-architect#8) · wide tables do not scroll (`globals.css:1012-1020`) (ux-architect#9) · document-task answers render as plain text (`conversation-view.tsx:702-704`) (ux-architect#11) · question bubbles collapse line breaks (`conversation-view.tsx:622-624`) (ux-architect#12) · in-progress generated documents shown as ready (`conversation-view.tsx:176`) (ux-architect#13) · "N tokens" is characters ÷ 4 shown as a real count (`message-bubble.tsx:310-313`, backend `router.py:479/560/642/830`) (ux-architect#6) · no "new below" signal while the prompt is pinned (`chat-thread.tsx:218`) (frontend-engineer#9) · language regex truncates `c#`/`c++` (`message-markdown.tsx:92`) (frontend-engineer#11) | minor ×9 | — |
| 27 | Fallback path only (brain off or `deliberate` raising): depth planner defaults `general_chat` and follow-ups to "brief" and is untested (`app/intelligence/prompting/depth_planner.py:49-58`, `:134-164`) (qa-engineer#6 = ux-architect#21) · persona fragments never reach the prompt (`persona/engine.py:38-109`) (qa-engineer#7) · reviewer depth checks untested (`review/reviewer.py:31-36`, `:113-117`) (qa-engineer#8) · reviewer flags "I can't be certain" as refusal (`reviewer.py:46-49`) (qa-engineer#9) · "Sure," strip leaves a lowercase start (`format/formatter.py:67-73`) (qa-engineer#10) · step-list spacing untested (`formatter.py:45-50`) (qa-engineer#11) | minor ×6 | only after the default path (steps 7-11). Editing these does not change default chat. |
| 28 | `should_regenerate` never read (`app/intelligence/engine.py:327`) (qa-engineer#12) · frontend has no tests (qa-engineer#14) · hex colours in tool indicator (`tool-call-indicator.tsx:8-13`) (ux-architect#14, fold into 14) · pipeline vocabulary in stage labels and citation chips (`knowledge/stage-indicator.tsx:12-20`) (ux-architect#15) · "Thought for Ns" timer start (`streaming-message-bubble.tsx:45`, `:79`) (ux-architect#17) · no structure aids for long answers (`globals.css:971-975`) (ux-architect#18) · `BrainMeta` unused and bot-like (`brain-meta.tsx:28-56`) (frontend-engineer#14 = ux-architect#19) | note ×7 (qa-engineer#13 is already step 2) | — |

## Merged duplicates (9)
- **ai-ml-architect#2 = qa-engineer#4.** Both are the same length rule at `pipeline.py:55-58`. Kept ai-ml-architect's location and grep; added qa-engineer's executed `deliberate()` probe (the same 4,837-char prompt for "ok" and for "Explain step by step…"), which is the stronger evidence. Kept qa-engineer's note that "a one-line question gets a short answer" is not pinned by any test.
- **qa-engineer#6 = ux-architect#21.** Same file and root cause (`depth_planner.py` "brief" default). Kept qa-engineer: it has an executed probe and correctly scopes the finding to the fallback path. See Contradictions.
- **frontend-engineer#1 = ux-architect#1.** Both are streamed text vanishing, at `chat-thread.tsx:56`/`:349`. Kept frontend-engineer's zustand replay (executed, textShown 77 → 0). Kept ux-architect's Stop case and backend `finally`-save recommendation, which frontend-engineer did not probe.
- **frontend-engineer#2 = ux-architect#2.** Both are raw `str(e)` in a truncated banner. Kept both site counts, because they cover different scopes (5 in router.py, 8 across app/api + app/workspace), and kept ux-architect's pointer to the correct pattern in `document_platform/conversation/gateway.py:273`.
- **ux-architect#3 = frontend-engineer#10.** Both are Edit/Retry sending `"auto"` at `use-chat.ts:385`/`:397`. Kept ux-architect's severity (major) and its Reasoning-mode scenario.
- **frontend-engineer#6 ⊃ ux-architect#10.** ux-architect#10 critiques the tool rationale styling, but frontend-engineer's grep shows the backend never sends `tool_call` (count 0), so that UI never renders at dc9515c. Kept frontend-engineer. ux-architect#10's wording and fold-into-summary advice goes into step 14.
- **frontend-engineer#7 = ux-architect#16.** Reasoning panel disappears. Kept frontend-engineer's thread probe (reasoningShown 22 → 0) and severity minor.
- **frontend-engineer#8 = ux-architect#20.** Caret on its own line. ux-architect wrote "probably" and did not render it; frontend-engineer rendered the structure. Kept frontend-engineer and severity minor.
- **frontend-engineer#14 = ux-architect#19.** `BrainMeta` unused and bot-like. Kept frontend-engineer, which also notes the `done` metadata is dropped.

Grouped, not merged (different claims that must land together): ai-ml-architect#2/#3/#4 (step 8); ai-ml-architect#5 + qa-engineer#5 (step 9); ux-architect#3 + ai-ml-architect#9 (step 16); qa-engineer#1 + #3 (steps 3-4).

## Contradictions
- **ux-architect#21 says `depth_planner.py:58`/`:144` forces "brief" answers and "no UI change can fix" it. ai-ml-architect and qa-engineer say that stage is not on the default serving path.** The executed evidence favours ai-ml-architect and qa-engineer:
  - qa-engineer ran a `deliberate()` probe showing the same fixed `_STREAM_SYSTEM` goes out regardless of the message.
  - ai-ml-architect's grep (`grep -rn "from app\.\(intelligence\|prompts\|agents\)" app/cognitive_integration`) found only the intent detector imported.
  - Both trace `config.py:36 cognitive_brain_enabled: bool = True`.
  - ux-architect's grep proves the file's contents, not that it runs.

  Resolution: the depth planner is real but fallback-only (step 27, minor). The "brief" behaviour on the default path comes from `_STREAM_SYSTEM` (step 8). What is still open: no report checked the *deployed* environment. If a deployment sets `COGNITIVE_BRAIN_ENABLED=false`, or `deliberate` raises often, the fallback becomes live and step 27 rises to major. Settle with `.\venv\Scripts\python.exe -c "from app.config import settings; print(settings.cognitive_brain_enabled, settings.llm_provider)"` in each deployed environment, plus a count of the orchestrator-fallback log line.
- **ai-ml-architect's summary says "major 7, minor 4, note 2"; its body has 8 major (#1-#8), 3 minor (#9-#11), 2 note (#12-#13).** The body governs. This triage uses the body, then re-rates #8 to blocker.
- **Where GENERAL's `max_tokens=2048` is.** ai-ml-architect cites `app/llm/profiles.py:116-120`, qa-engineer cites `:112`. Both are at dc9515c, so one line reference is wrong. The finding is unaffected. Settle with `grep -n "max_tokens=2048" app/llm/profiles.py` before editing.
- **Severity of Edit/Retry-in-auto.** ux-architect says major, frontend-engineer says minor. Both have the same grep evidence. Re-rated to major, because the UI states a mode the request did not use, and it hits exactly the user asking for more depth.
- **Does Stop (not just an error) wipe the partial reply?** ux-architect claims it from reading the `handingOver` logic. frontend-engineer probed only the error path, and its "Verified clean" covers only `stop()` invalidating messages. The evidence is not equal (reading vs an unrun case), so neither is picked. Settle by extending frontend-engineer's zustand/thread replay with token, token, abort → refetch with no assistant row, and asserting `textShown`.

## Re-rated
- **ai-ml-architect#8: major → blocker.** A blocked request reaching the model breaks an invariant documented in CLAUDE.md ("a blocked or ambiguous request must never reach the LLM"). Conditional on the step 1 test failing at dc9515c.
- **frontend-engineer#10: minor → major** (merged into ux-architect#3). Reason above.
- **ux-architect#10: minor → note-level, folded into frontend-engineer#6.** Its failure scenario cannot happen at dc9515c, because the backend emits no `tool_call` event.
- **ux-architect#16 and ux-architect#20: note → minor** (merged into frontend-engineer#7 and #8), because an executed probe confirmed the behaviour.
- **ux-architect#21: note → minor** (merged into qa-engineer#6), fallback path only.

## Returned for evidence
- **ai-ml-architect#12** (`_select_model` comments and unused `mode`, `pipeline.py:204`, `:211`). There is no failure scenario, and it affects only Ollama deployments. Refile with a named input → wrong model, or leave as a comment fix alongside step 22.
- **ai-ml-architect#13** (whether the chat template honours a mid-conversation `system` reminder, `pipeline.py:175-199`). The report says it is "not verified" and gives no failure scenario. Run measurement 3 from ai-ml-architect's Unmeasured list (6 samples, reminder as system turn vs user-turn prefix, count greetings) and refile with the counts. This matters to step 8, which relies on the reminder carrying weight.

## Coverage gaps
- **No live model output anywhere.** No reviewer was authorised to call a model. Every claim that a changed prompt will read warmer or more thorough, and every truncation rate, is unmeasured. Step 6 exists to close this.
- **No rendered UI.** ux-architect saw no screenshots. frontend-engineer rendered HTML strings in Node, not a browser. Mobile layout, light theme contrast (ux-architect#14) and actual scroll behaviour have not been observed.
- **No security reviewer.** Two findings sit in that territory: the policy bypass in the document branch (step 1) and `str(e)` exception text sent to clients (step 12). Neither has been examined for data exposure. The blocker area is covered by ai-ml-architect's grep only, not a mutation.
- **Deployed configuration not read.** `COGNITIVE_BRAIN_ENABLED`, `LLM_PROVIDER` and `LLM_PROFILE_OVERRIDES` on the demo deployment (Vercel/Render) are unknown. This decides whether steps 22 and 27 matter.
- **Not examined:** `/chat/stream/vision` beyond the one `is_blocked` line; the Knowledge Workspace conversation voice (DIP `conversation/` prompts; ux-architect covered its UI only); the orchestrator fallback's frequency in production; the backend `/chat/message` non-stream endpoint.
- **Test infrastructure gaps block recommended tests.** The frontend has no vitest or playwright config (qa-engineer#14, CLAUDE.md), so every frontend "add a component test" recommendation needs setup first. Backend chat integration tests cannot import `aiosqlite` (step 2).
- **Pre-existing gate state noted, not triaged.** Frontend repo-wide `pnpm lint` has 818 errors and 1029 warnings (frontend-engineer), and the backend has two pre-existing `tests/unit/intelligence` confidence-evaluator failures (qa-engineer). Both are outside this area.
- **All four requested specialists reported. None is missing.**
