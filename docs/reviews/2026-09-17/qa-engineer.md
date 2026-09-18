---
role: qa-engineer
repo: backend
ref: dc9515c
date: 2026-09-17
scope: "Tests around chat tone, persona, answer depth and response formatting. Live path: app/cognitive_integration/pipeline.py (_STREAM_SYSTEM, _STYLE_REMINDER, deliberate), app/api/v1/chat/router.py (_stream_cognitive_response), app/llm/profiles.py (GENERAL budget). Fallback path: app/intelligence/{persona,strategy,prompt,prompting,review,format}. Tests: tests/cognitive_integration/*, tests/unit/intelligence/test_intelligence_engine.py, tests/unit/test_llm_gateway.py. Frontend repo checked for tests only."
---

# Summary

**Verdict: you cannot safely change tone or explanation depth with only these tests as protection.** They do not force short or robotic output: the only brevity rule they pin on the live path is the one for bare acknowledgements ("ok", "got it"). But they would also stay green if someone made the bot terse again. I ran 13 realistic mutations that change tone, depth or wiring, and every one left the suite green. A control mutation was caught, so the setup does detect failures. In the live streaming path, nothing tests how the persona prompt, history or token budget reach the model, and the persona tests only check that certain phrases appear in the prompt. Counts: 0 blocker, 5 major, 6 minor, 3 note.

Which path is live. `COGNITIVE_BRAIN_ENABLED` defaults to `True` (app/config.py:36), so `/chat/stream` (the frontend calls it at frontend/lib/api/chat.ts:94) goes through `deliberate()` and then `_stream_cognitive_response`, using the fixed `_STREAM_SYSTEM`. The intelligence engine (persona/strategy/composer/reviewer/formatter) only runs on the fallback orchestrator path, when the brain is off or `deliberate` returns None. Tone complaints from real use therefore come from `_STREAM_SYSTEM`, not from `PersonaEngine`.

How I ran the mutations. I made a scratch copy of `app/`, `tests/` and `pyproject.toml` in the session scratchpad, run with the repository's venv. I confirmed imports resolved to the copy (`app.cognitive_integration.pipeline.__file__` pointed into the scratchpad). The suite was `tests/unit tests/cognitive_integration tests/e2e --no-cov`. In the copy the baseline is `32 failed, 681 passed, 1 error`, because the copy has no `.env` or data files. Each mutation was judged by whether it added a failing test to that baseline set. Positive control: changing `- Length follows the message.` gave `33 failed, 680 passed`, with the new failure `test_stream_turns.py::test_a_bare_acknowledgement_does_not_earn_an_essay`, so the setup detects failures. The copy was removed with `scratch-copy --remove`. In the real repository the targeted suites pass: `114 passed` (cognitive_integration + test_intelligence_engine + test_llm_gateway).

Mutation results (all against the baseline above):

| # | Mutation | Result |
|---|---|---|
| M1 | Inject `"- Keep every reply under three sentences. Never use headings, bold or lists. "` into `_STREAM_SYSTEM` | SURVIVED — `32 failed, 681 passed` |
| M2 | `_STYLE_REMINDER` gets `Be brief. Short paragraphs. End on a statement, never a question.` | SURVIVED |
| M3 | `deliberate()` sends `system_prompt='You are a helpful AI assistant.'` | SURVIVED |
| M4 | `deliberate()` sends `history=()` | SURVIVED |
| M5 | Route calls `chat_stream(..., system_prompt=None, ...)` | SURVIVED |
| M6 | GENERAL profile `max_tokens=2048` → `256` | SURVIVED |
| M7 | Reviewer "teaching response too brief" check → `if False:` | SURVIVED |
| M8 | Reviewer `Complexity.COMPLEX` min words `150` → `0` | SURVIVED |
| M9 | Teaching formatter's numbered-step spacing disabled | SURVIVED |
| M10 | Depth planner drops the `"step by step"` signal | SURVIVED |
| M11 | Comprehensive depth instruction → `"Answer in two sentences. No sections. "` | SURVIVED |
| M12 | Conversational brevity principles ("Match the brevity of the question") applied to every intent | SURVIVED |
| M13 | TEACHER persona fragment → `"Answer tersely. "` | SURVIVED |

## Finding 1 — No test covers the live streaming route that sends the persona and history to the model
- **Severity:** major
- **Location:** app/api/v1/chat/router.py:520 (`_stream_cognitive_response`; the call at :547-551)
- **Evidence:** `grep -rn "_stream_cognitive_response\|deliberate_turn" tests` → no matches. Coverage scoped to the module (scratch copy, `--cov=app.api.v1.chat`): `app\api\v1\chat\router.py 583 504 14% … 531-586, … 725-858` — neither the cognitive stream nor `stream_message` runs. Mutation M5 (`system_prompt=None`) → `32 failed, 681 passed`, no new failure.
- **Failure scenario:** A refactor drops `system_prompt=delib.system_prompt` or `history=delib.history`. Every reply on `/chat/stream` then goes out with no persona and no conversation turns: generic, re-greeting, bot-like. CI stays green.
- **Recommendation:** Add a route-level test that stubs `get_ollama_client().chat_stream` with a recorder. It should POST `/api/v1/chat/stream` with the brain enabled and assert the recorder received `system_prompt == _STREAM_SYSTEM`, `history[-1] == _STYLE_REMINDER`, the prior turns, and `profile == profile_for_mode(agent_mode)`. Also assert that escalated turns stream `hold_message` and never call `chat_stream`.

## Finding 2 — The persona tests pass when the prompt contains an instruction that makes replies terse
- **Severity:** major
- **Location:** tests/cognitive_integration/test_stream_turns.py:80-145
- **Evidence:** Every persona test is `assert "<phrase>" in _STREAM_SYSTEM` (or `not in`). M1 added "Keep every reply under three sentences. Never use headings, bold or lists." to the middle of the persona, which directly contradicts the long-answer rule at pipeline.py:123-127. Result: `32 failed, 681 passed`, no new failure. M2 turned the closing reminder into "Be brief … End on a statement, never a question": also no new failure. The only reminder check, `test_the_voice_reminder_comes_last_before_the_new_message` (:65), compares against the `_STYLE_REMINDER` object itself, so it cannot fail when that object's content changes.
- **Failure scenario:** Someone adds a brevity line to the persona or the reminder (the reminder weighs most because it is the last instruction). Replies to "explain X thoroughly" go back to three flat sentences, and the suite stays green. In the other direction, rewording a rule to make the bot warmer breaks these tests even when the behaviour improves, because they check wording, not behaviour.
- **Recommendation:** Keep the phrase checks as change detectors, and add checks on how the whole prompt fits together. (a) A "no contradicting rule" test that fails if `_STREAM_SYSTEM` or `_STYLE_REMINDER` contains a length cap or format ban outside the short-answer clause (for example a regex for `under \w+ sentences|never use headings|be brief`). (b) Assert that the reminder content agrees with the persona: the question-ending rule and the "use headings when long" rule both appear. (c) Outside pytest, a recorded-sample check (see Finding 4) that counts headings and paragraph grouping on real outputs, since only model output can show whether a reply sounds human.

## Finding 3 — `deliberate()` can send a generic bot prompt or drop history and its test stays green
- **Severity:** major
- **Location:** app/cognitive_integration/pipeline.py:249-251; test at tests/cognitive_integration/test_cognitive_chat_slice.py:111
- **Evidence:** The test asserts only `normal.system_prompt and normal.user_prompt` (truthy). M3 (`system_prompt='You are a helpful AI assistant.'`) and M4 (`history=()`) → both `32 failed, 681 passed`, no new failure. The `_as_turns`/`_stream_history` unit tests (test_stream_turns.py:15-77) do catch helper bugs, but no test checks that `deliberate` actually uses those helpers.
- **Failure scenario:** `Turn(message="and the second step?", history=[…])` is deliberated with no history. The model answers as if the conversation just started, which is exactly the "greets every time" bug described in the pipeline.py:243-245 comment.
- **Recommendation:** In `test_deliberate_governs_without_generating_for_streaming`, assert `normal.system_prompt is _STREAM_SYSTEM`. Add a case with history and assert `delib.history == _stream_history(turn.history)`, with the prior user turn present and `_STYLE_REMINDER` last.

## Finding 4 — "Explain step by step, thoroughly" gets exactly the same instructions as "ok", and no test covers a depth request
- **Severity:** major
- **Location:** app/cognitive_integration/pipeline.py:249 (fixed `_STREAM_SYSTEM`) and :55-58 ("A one-line question gets a short answer")
- **Evidence:** A read-only probe using the test's `_build()` fakes: `deliberate(Turn("ok"))` vs `deliberate(Turn("Explain step by step, thoroughly, how DNS resolution works"))` → `same system prompt: True | same history: True | len 4837`. `grep -rn "step by step\|thorough" tests/cognitive_integration` → no matches.
- **Failure scenario:** The user asks for an explanation "step by step" in one line. The only depth instructions the model gets are "A one-line question gets a short answer" and "Match … their length", so it gives a short answer, which is the complaint in scope. The depth detection that exists (`_TUTORIAL_SIGNALS`, depth_planner.py:49) is only on the fallback path. Lock-in check: no test asserts the "one-line question gets a short answer" sentence, so it can be changed freely. Only "Length follows the message" (:55) and the acknowledgement clause are pinned (test_stream_turns.py:137-138).
- **Recommendation:** Before changing depth behaviour, add the missing test cases: bare acknowledgement, short factual question, and an explicit depth request ("step by step", "walk me through", "in detail"). Assert that the explicit request produces a different instruction, whether through a per-turn depth hint in `Deliberation` or a reminder variant, and that the acknowledgement case still gets the short rule. Pair this with an offline eval script (not in pytest, no network in CI) that records N samples for each case and checks reply length and heading count.

## Finding 5 — Only a comparison with REASONING protects the GENERAL profile's output budget, which limits long step-by-step answers
- **Severity:** major
- **Location:** app/llm/profiles.py:112 (`max_tokens=2048`); test at tests/unit/test_llm_gateway.py:125
- **Evidence:** The only budget assertion is `resolve_profile(REASONING, s).max_tokens > resolve_profile(GENERAL, s).max_tokens`. M6 (GENERAL `2048` → `256`) → `32 failed, 681 passed`, no new failure. `auto` and `business` both map to GENERAL (profiles.py:161-162), and those are the modes chat uses.
- **Failure scenario:** Someone lowers GENERAL's `max_tokens` to cut latency (via code or `LLM_PROFILE_OVERRIDES`). A thorough explanation then stops mid-sentence at about 190 words, and it reads as a clipped, robotic reply. Even at 2048 tokens, an "inch by inch" answer with headings (about 1,500 words) is near the ceiling.
- **Recommendation:** Add an absolute lower-bound test (for example `resolve_profile(GENERAL).max_tokens >= 2048`, or whatever floor the team chooses), with a docstring tying the value to long explanations. If depth is raised, move the floor with it in the same commit.

## Finding 6 — On the fallback path, the depth planner, prompt-intelligence engine and composer have no tests, so a terse depth instruction goes unnoticed
- **Severity:** minor
- **Location:** app/intelligence/prompting/depth_planner.py:49-58, :134-164; app/intelligence/prompting/engine.py:132-142; app/intelligence/prompt/composer.py:198-251
- **Evidence:** `grep -rln "composer\|depth_planner\|DepthPlanner" tests` → no matches. Scoped coverage: `depth_planner.py 48% … 134-164, 181-189`, `prompting\engine.py 39% … 133-142, 173-250`, `prompt\composer.py 18%`. M10, M11 and M12 all left the suite green. Probe on the original code: `"how does DNS work?"` with intent `general_chat` → `brief` ("Be concise … 1-3 paragraphs. No headers."); `"explain step by step how DNS works"` → `comprehensive`.
- **Failure scenario:** With the brain disabled or erroring, every `general_chat` question that lacks a depth keyword is told "1-3 paragraphs. No headers." Removing the "step by step" signal, or applying "Match the brevity of the question" to every intent, would pass CI.
- **Recommendation:** Add table tests for `ResponseDepthPlanner.plan` (each `_INTENT_DEPTH` entry, each signal list including "step by step" and "walk me through", and brief-signal precedence). Also add a composer test asserting the depth and personality sections appear in `compose()` output for a teaching and a chat context.

## Finding 7 — The persona prompt fragments are never used, so the persona tests check a choice that never reaches the prompt
- **Severity:** minor
- **Location:** app/intelligence/persona/engine.py:38-109, :170 (`get_definition`); tests/unit/intelligence/test_intelligence_engine.py:284-331
- **Evidence:** `grep -rn "get_definition\|\.persona\b" app` → only the definition at persona/engine.py:170 and imports. The composer builds from `STRATEGY_REGISTRY` and `plan.personality_principles` (composer.py:56-60, :221-224), never from the persona. M13 (TEACHER fragment → "Answer tersely.") → no new failure.
- **Failure scenario:** An engineer edits the TEACHER fragment to make the assistant warmer and more thorough, sees the persona tests pass, and nothing changes for users. The tone lever everyone is tuning is not connected to the prompt.
- **Recommendation:** Either connect the persona fragment into `DynamicPromptComposer.compose` and add a test that it appears in the output, or delete the fragments and keep `select()` only as a routing signal. Don't count the current persona tests as coverage of tone.

## Finding 8 — Removing the reviewer's depth checks leaves the suite green
- **Severity:** minor
- **Location:** app/intelligence/review/reviewer.py:31-36 (`_MIN_WORDS`), :113-117 (teaching completeness)
- **Evidence:** Scoped coverage `reviewer.py 73% … 99-103, 108-111, 115-117, 123`: the repetition, context-contradiction and teaching checks never run. Tests use only `Complexity.SIMPLE`/`MEDIUM` (test_intelligence_engine.py:469-548). M7 and M8 → no new failure.
- **Failure scenario:** A 40-word reply to a VERY_COMPLEX teaching request should be flagged "too short". With the checks removed it is `APPROVED` and CI does not notice.
- **Recommendation:** Add reviewer cases with a COMPLEX/VERY_COMPLEX context and a TEACHING strategy just below and just above the thresholds (149/150 words, 199/200 words). Assert the issue text and the decision.

## Finding 9 — The reviewer marks an honest "I can't be certain" as refusal language, which conflicts with the honesty rule
- **Severity:** minor
- **Location:** app/intelligence/review/reviewer.py:46-49 (`"i can't"` in `_REFUSAL_PHRASES`)
- **Evidence:** A read-only probe on the original code: `review("I can't be certain of the exact year it shipped, but it was in the early 2010s, …", DIRECT_ANSWER ctx)` → `ReviewDecision.NEEDS_FORMATTING 0.6 ["Response contains refusal language: 'i can't'"]`. The only refusal test (test_intelligence_engine.py:545) uses a real refusal, so no test shows that a hedge is allowed.
- **Failure scenario:** The fallback path scores a humble, honest reply 0.6 with a refusal issue. If regeneration is ever wired to this score (see Finding 12), the most human replies get pushed toward confident ones, contradicting "A hedged true answer beats a confident wrong one" (pipeline.py:101).
- **Recommendation:** Add a test that hedges ("I can't be certain", "I'm not sure, but") are `APPROVED`. Narrow the phrase match to refusals ("I can't help", "as an AI").

## Finding 10 — The direct-answer formatter removes a natural opening word and leaves a lowercase start, and a test pins that stripping
- **Severity:** minor
- **Location:** app/intelligence/format/formatter.py:67-73; test at tests/unit/intelligence/test_intelligence_engine.py:598-601
- **Evidence:** Probe: `format("Sure, this one is subtle.\n\nStep one...", DIRECT_ANSWER)` → `'this one is subtle.\n\nStep one...'`. The test only asserts `not result.startswith("Sure")`. It does not check that the remaining sentence is still well-formed, so it pins the stripping but not its correctness.
- **Failure scenario:** On the streaming fallback path (orchestrator.py:806-808) the user sees "Sure, this one is subtle." as it streams, but the reformatted "this one is subtle." is what goes to session memory. A later turn then works from text the user never saw.
- **Recommendation:** Add cases where the preamble is followed by content in the same sentence, and assert the output is either unchanged or re-capitalised. Decide whether a humanised persona should strip "Sure" at all.

## Finding 11 — Disabling the teaching formatter's step-list spacing leaves the suite green
- **Severity:** minor
- **Location:** app/intelligence/format/formatter.py:45-50
- **Evidence:** Coverage `formatter.py 73% … 48-51, 55, 59, 63`. M9 → no new failure. Probe: `"## Step by step\n1. First\n2. Second"` → `'## Step by step\n\n1. First\n\n2. Second'`. That turns a tight list into a loose one, which markdown renders with `<p>` inside each item.
- **Failure scenario:** A step-by-step answer's spacing changes, in either direction, and no test notices.
- **Recommendation:** Add a TEACHING-strategy formatter test with the exact expected output for a numbered list, including nested and code-fenced lists that the regex must not touch.

## Finding 12 — The reviewer's regenerate decision is never used, so reviewer tests cannot affect what the user sees
- **Severity:** note
- **Location:** app/intelligence/engine.py:327
- **Evidence:** `grep -rn "should_regenerate" app` → only engine.py:83, :311, :327 (set, never read). On the stream path the reviewer result is only logged (orchestrator.py:806-810).
- **Failure scenario:** A test proving an empty or too-short reply gets `REGENERATE` passes, but no reply is ever regenerated.
- **Recommendation:** Wire the decision into the review loop or remove it. Either way, add an orchestrator-level test that asserts the end-to-end effect rather than the enum value.

## Finding 13 — The chat integration tests cannot run here, and none of them call `/chat/stream`
- **Severity:** note
- **Location:** tests/conftest.py:46 (`sqlite+aiosqlite:///:memory:`); tests/integration/test_chat_api.py
- **Evidence:** In the real repo, `pytest tests/integration/test_chat_api.py --no-cov` fails with `ModuleNotFoundError: No module named 'aiosqlite'` for every test. `grep -rn aiosqlite requirements*.txt pyproject.toml` → no matches. The endpoints posted are `/api/v1/chat/conversations` (4) and `/api/v1/chat/message` (7), never `/chat/stream`.
- **Failure scenario:** A reader assumes chat has integration coverage. It has none that runs, and none on the endpoint the frontend actually calls.
- **Recommendation:** Declare `aiosqlite` as a test dependency, and put the Finding 1 route test here against `/chat/stream`.

## Finding 14 — The frontend has no tests, so nothing checks that it renders the markdown the persona now asks for
- **Severity:** note
- **Location:** frontend/components/chat/message-markdown.tsx; frontend/app/globals.css (`.assistant-content`)
- **Evidence:** `find frontend -path ./node_modules -prune -o -path ./.next -prune -o ( -name "*.test.*" -o -name "*.spec.*" -o -name "vitest.config*" -o -name "playwright.config*" ) -print` → no output. The docstring of test_stream_turns.py:100 claims "`.assistant-content` already styles h1-h4, strong, blockquote, hr and ol", and no test backs it.
- **Failure scenario:** The persona produces `##` headings, bold lines and blockquotes (pipeline.py:62-66, :123-127). If the renderer loses those styles, long answers look worse than before the persona change, and no test notices.
- **Recommendation:** When the chat UI work lands, add one component test rendering a fixture reply that contains `##`, `**bold**`, `>` and `---`, and assert the elements exist. Until then, `pnpm type-check` and `pnpm build` are the only verification (per CLAUDE.md).

## Verified clean
- History-to-turns helpers — `_as_turns` merge, cap and leading-assistant trim, and `_stream_history` putting the reminder last. The positive control shows the persona substring tests do fail when a pinned phrase is removed: `33 failed, 680 passed`, new failure `test_a_bare_acknowledgement_does_not_earn_an_essay`.
- Targeted suites pass at dc9515c: `pytest tests/cognitive_integration tests/unit/intelligence/test_intelligence_engine.py tests/unit/test_llm_gateway.py --no-cov` → `114 passed`.
- No model provider is called by these tests — cognitive slice tests inject `FakeLLM` (test_cognitive_chat_slice.py:27-36). `deliberate` is asserted to make no LLM call (`len(llm.calls) == 0`).
- The tests do not lock in terse output on the live path: the only pinned brevity is the acknowledgement clause (test_stream_turns.py:137-138). "A one-line question gets a short answer" and "Match … their length" are unpinned. On the fallback path the only brevity mechanism with a test is the "Sure!" strip (Finding 10).
- Known unrelated failures are pre-existing: the two confidence-evaluator failures (`test_repo_with_no_chunks_gives_very_low_repo_match`) show up in `tests/unit/intelligence` with or without any mutation.
- Repository state unchanged by this review: `git status --short` in backend was empty at start. At the end it shows only `?? docs/reviews/`, which holds this file plus reports written in parallel by ai-ml-architect, frontend-engineer and ux-architect. Frontend is empty before and after. The scratch copy was removed.
