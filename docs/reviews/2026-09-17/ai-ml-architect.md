---
role: ai-ml-architect
repo: backend
ref: dc9515c
date: 2026-09-17
scope: "Why chat replies read as robotic and terse. Serving path of POST /api/v1/chat/stream (app/api/v1/chat/router.py), the Cognitive OS streaming path (app/cognitive_integration/pipeline.py, service.py, adapters_prod.py), app/llm/profiles.py + gateway.py, app/ollama_client.py chat_stream, session history (app/redis_client.py), the document-chat branch (app/documents/service.py), and the frontend's default agent_mode (frontend/lib/stores/chat-store.ts)."
---

# Summary

Verdict: **the robotic, terse feel is caused on the path that actually serves chat, and most of it is
deliberate instruction rather than model limits.** With default config (`COGNITIVE_BRAIN_ENABLED=True`,
`LLM_PROVIDER=nvidia`, frontend `agentMode: "auto"`), an ordinary chat turn is answered from the hard-coded
`_STREAM_SYSTEM` in `cognitive_integration/pipeline.py` on the `general` profile (Nemotron 3 Super,
thinking off, temperature 0.6, **max_tokens 2048**). The intelligence engine's persona, strategy,
composer, reviewer and formatter stages are **not on this path**, so editing them changes nothing.

The causes I found, in order of impact:
1. A substring keyword scan (`"format "`, `"delete"`, `"erase"`...) escalates harmless questions to a canned
   "held for review" message. No model is called.
2. The live prompt tells the model to keep replies short when the question is one line, and to match the user's length.
3. The prompt pushes warmth out on purpose and never asks for a step-by-step walkthrough.
4. Long answers get cut off at 2048 tokens and the user is not told.
5. Earlier long answers are trimmed to 2000 characters in history, and edit/regenerate leaves deleted turns in the model's memory.
6. Once a document is attached, the chat switches to a different, older persona that gets history as a pasted transcript. That branch also answers requests the policy engine blocked.

Counts: **blocker 0, major 7, minor 4, note 2.** All claims about how a changed prompt would *read*
(warmth, thoroughness) are **unmeasured**: no live model was called (not authorised). The exact runs that
would settle them are listed at the end.

**Serving path (default config), as traced:**

| Step | Code | Decides |
|---|---|---|
| Entry | `router.py:709-711` `POST /chat/stream` | — |
| 1 | `router.py:750` `_maybe_stream_file_response` | file / sheet requests only |
| 2 | `router.py:761` `_ensure_document_context` → `_stream_document_response` | any conversation with an uploaded document |
| 3 | `router.py:782-794` `cognitive_brain_enabled()` → `deliberate_turn` → `_stream_cognitive_response` | `config.py:36 cognitive_brain_enabled: bool = True` |
| 4 | `router.py:796+` orchestrator (intelligence engine) | only if `deliberate()` returns None (exception) |

Model call on step 3: `router.py:548-551` → `OllamaClient.chat_stream(..., profile=profile_for_mode(agent_mode), history=delib.history)` → `config.py:94 llm_provider = "nvidia"` → `ChatGateway.stream`, profile `general` (`profiles.py:116-120`). Frontend sends `agent_mode` from `chat-store.ts:95 agentMode: "auto"` → `AGENT_MODE_PROFILES["auto"] = GENERAL`.

Prompt on step 3: `_STREAM_SYSTEM` (`pipeline.py:39-128`, 4,837 chars) + `_STYLE_REMINDER` as a system turn after history (`pipeline.py:175-187`).

---

## Finding 1 — Harmless questions containing "format ", "delete", "erase" and similar are escalated to a canned hold message, and the model is never called
- **Severity:** major
- **Serving path:** `/chat/stream` step 3 → `CognitivePipeline.deliberate` → `IntentDetectorAdapter.detect`
- **Location:** app/cognitive_integration/adapters_prod.py:48-49 (the `_DANGER` tuple), :66-71 (`d in low` substring match → `stakes=0.95, irreversible=True`); app/cognitive_integration/pipeline.py:28-32 (`_ESCALATION` text); app/api/v1/chat/router.py:538-541 (streamed instead of an answer)
- **Evidence:** scratch script `probe_escalation.py`: real `build_pipeline` with an LLM stub that raises if called, real `IntentDetectorAdapter`, calling `deliberate()`:
  ```
  escalated=True  authorized=False decision=ask_user   | What format should my resume be in?
     hold: That request looks high-stakes or potentially irreversible, so I'm holding it fo
  escalated=True  authorized=False decision=ask_user   | Can you explain step by step how to delete a git branch?
  escalated=True  authorized=False decision=ask_user   | How do I format a date in Python?
  escalated=True  authorized=False decision=ask_user   | Explain what DROP TABLE does in SQL, inch by inch
  escalated=True  authorized=False decision=ask_user   | My landlord wants to erase the damage deposit, what are my rights?
  escalated=False authorized=True  decision=approve    | Explain how React state works, step by step
  ```
  Clarifying (`probe_confirm.py`, with the hold message already in history) gets held again: `True | I just want to know how to format a date string in Python, that's all`.
  `grep -rn "_DANGER\|IntentDetectorAdapter" tests` shows only a *fake* detector with its own `("delete","wipe","destroy")` list (`test_cognitive_chat_slice.py:41`). The production keyword list has no test.
- **Failure scenario:** a user types "How do I format a date in Python?". The reply is a fixed, bureaucratic sentence asking them to confirm a "high-stakes or potentially irreversible" request. Rephrasing the question gets the same sentence. That sentence is then saved to history (`router.py:568-569`), so the model sees it on later turns. This is the most "bot-like" thing the product does, and it hits educational questions about deleting, formatting and erasing, which are common on a coding assistant.
- **Recommendation:** keep the Executive gate, since high-stakes turns must still never be auto-answered. Stop using substring hits on single common words as the risk signal:
  - Match whole words.
  - Treat a question or explanation request ("how do I", "what does", "explain") as a request for knowledge, not a request to act. This chat path performs no actions.
  - Keep escalation for imperative requests aimed at a real system.
  - Let a confirmation after a hold go through.
  - Add `tests/cognitive_integration/test_intent_risk.py` that runs the **production** `IntentDetectorAdapter`. Include the six messages above as must-not-escalate cases, plus "delete all rows in prod now" / "rm -rf /" as must-escalate cases.

## Finding 2 — The live prompt tells the model to answer one-line questions briefly and to copy the user's length, which is the opposite of "explain step by step, thoroughly"
- **Severity:** major
- **Serving path:** `/chat/stream` step 3, `_STREAM_SYSTEM`
- **Location:** app/cognitive_integration/pipeline.py:55-58, :72-73
- **Evidence:** `grep -n` on the file:
  ```
  55:    "- Length follows the message. A bare acknowledgement (\"ok\", \"got it\", \"nice\") "
  57:    "anything. A one-line question gets a short answer. Only a real request to explain "
  72:    "- Match how they write: their rhythm, their length, their slang, the words they "
  ```
  These rules are pinned by tests: `tests/cognitive_integration/test_stream_turns.py:137-138` asserts `"Length follows the message"` and `"gets one or two sentences and no question at all"`. `pytest tests/cognitive_integration --no-cov` → `27 passed`.
- **Failure scenario:** "how does async/await work in JS?" is one line, so the rule gives it "a short answer". Users almost always ask for explanations in one line, so the "long reply" branch is reached only when they explicitly write "explain in detail". A user who writes tersely gets terse answers back ("match... their length").
- **Recommendation:** keep the acknowledgement rule ("ok" → one or two sentences), because it was measured. Make depth follow **what kind of question it is**, not how long it is. Phrase it positively, per the repo's measured lesson: "A how/why/what-is question, or anything asking to understand something, gets a full walkthrough however briefly it was asked." Keep "match their words and register" but drop "their length". Update `test_stream_turns.py:137-138` in the same change. Measure it (see Unmeasured).

## Finding 3 — The live prompt suppresses warmth and empathy by design
- **Severity:** major
- **Serving path:** `/chat/stream` step 3, `_STREAM_SYSTEM` and `_STYLE_REMINDER`
- **Location:** app/cognitive_integration/pipeline.py:41, :52-54, :85-87; :181-182 (reminder)
- **Evidence:** `grep -n`:
  ```
  41:    "find genuinely interesting — not a help desk, not a therapist, not an essay.\n"
  53:    "interesting answer, not reassurance. Don't read distress into a message unless it "
  85:    "- Take a side. If they are right, say so plainly; if you disagree, say that. Never "
  ```
  The reminder, which sits last and so carries the most weight, repeats "Say what you think rather than weighing both sides". `test_stream_turns.py:113-115` asserts that stock empathy phrases are absent. That is correct, since quoting them reproduced them, but nothing in the prompt says what warmth *should* look like.
- **Failure scenario:** a user writes "I've been stuck on this bug all day, can you help me understand why my state isn't updating?". The prompt forbids reassurance and reading distress, and requires committing to a claim and taking a side. The expected reply is a direct, opinionated correction with no acknowledgement of the person. That is the "sharp" voice the prompt asks for, and it is what the user describes as having "no humanism".
- **Recommendation:** add a positively phrased warmth rule tied to specifics, so it does not bring back the measured stock-phrase openers. For example: "When they mention how it's going for them (stuck, frustrated, excited), acknowledge that specific thing in half a sentence using their words, then help." Soften "Never land on a balance" to "When there is a real trade-off, say which way you'd lean and why." Do not quote the unwanted phrases (measured 4/6 reproduction). Measure it.

## Finding 4 — Neither the system prompt nor the closing reminder asks for a step-by-step walkthrough: ordered steps, the why behind each, an example, a check on understanding
- **Severity:** major
- **Serving path:** `/chat/stream` step 3
- **Location:** app/cognitive_integration/pipeline.py:39-128 (`_STREAM_SYSTEM`), :175-187 (`_STYLE_REMINDER`)
- **Evidence:** `grep -n "step by step\|example\|analog\|warm" app/cognitive_integration/pipeline.py` returns only line 34, a *code comment* ("a quoted bad example"). No prompt string asks for steps, examples or analogies. The reminder asks for specificity, taking a side, paragraphs, headings and a closing question, but not for thoroughness.
- **Failure scenario:** "explain how JWT refresh works" gets "a genuinely interesting answer" built around one "distinction they have not put into words" (`pipeline.py:77-80`). It is not a walkthrough from the start to the end of the flow, which is what the user means by "inch by inch".
- **Recommendation:** add an explanation rule next to the long-answer hard rule. The code comment at `pipeline.py:117-121` records that this model follows hard format rules stated last (structure requested in a prose bullet appeared 0 of 4 times). For example: "When explaining how something works: go in order, one step per section; for each step say what happens, why it happens, and give a small concrete example; end by pointing at the step people most often get wrong." Put a one-line echo in `_STYLE_REMINDER`. Add a test in `test_stream_turns.py` pinning the rule's presence and its position after the first-sentence rule.

## Finding 5 — Replies on the default chat path are cut at 2048 output tokens and the user is never told
- **Severity:** major
- **Serving path:** `/chat/stream` step 3 → `OllamaClient._nvidia_chat_stream` → `ChatGateway.stream` with profile `general`
- **Location:** app/llm/profiles.py:116-120 (`GENERAL ... max_tokens=2048`); app/ollama_client.py:319-326 (only `content` and `reasoning` events are forwarded, and the `done` event with `finish_reason` is dropped); app/api/v1/chat/router.py:560-574 (saves and sends `done` with no truncation flag)
- **Evidence:** scratch `probe_trunc.py` with the project's fake `AsyncOpenAI` (`tests/unit/test_llm_gateway.py` pattern) streaming two chunks ending in `finish_reason="length"`:
  ```
  ... Chat model [general/...] thinking=False ... finish=length
  chunks seen by router: [('str', '## Step 1\n\nFirst, the '), ('str', 'state is')]
  max_tokens sent: 2048 temperature: 0.6
  roles sent: ['system', 'system', 'user']
  GENERAL profile (with configured overrides): ChatProfile(name='general', ... max_tokens=2048, ...)
  ```
  The gateway knows the reply was truncated (it logs it). The route receives only strings.
- **Failure scenario:** a thorough step-by-step answer, especially with the mandated `##` headings, `---` rules and blockquotes, runs past about 1,500 words. It stops mid-sentence, the truncated text is saved as the final answer, and the next turn's history holds a half-finished reply. Asking for more thoroughness (Findings 2 and 4) makes this happen more often.
- **Recommendation:**
  - Carry `finish_reason` through. For example, `chat_stream` yields a typed `StreamFinish` marker, and the router adds `"truncated": true` to the `done` frame. The frontend can then offer "Continue".
  - Raise the `general` budget with a measurement. First try `LLM_PROFILE_OVERRIDES={"general":{"max_tokens":4096}}`, record the truncation rate and first-token latency before and after, and write the numbers beside `profiles.py:116`.
  - Test: extend `tests/unit/test_llm_stream_errors.py` or `test_llm_gateway.py` so that a `length` finish reaches the route as a flag.

## Finding 6 — Prior assistant turns are cut to 2000 characters before being sent back, so follow-ups on later steps of a long explanation lose those steps
- **Severity:** major
- **Serving path:** `/chat/stream` step 3, `_stream_history` → `_as_turns`
- **Location:** app/cognitive_integration/pipeline.py:150-151, :162
- **Evidence:**
  ```
  $ python -c "...h=_stream_history([user 'explain X step by step', assistant <4534-char answer with '## Step 4' after char 2500>, user 'go deeper on step 4']) ..."
  assistant turn chars sent: 2000 of 4534 | step 4 present: False
  ```
- **Failure scenario:** the user asks for a step-by-step explanation, then says "go deeper on step 4". Step 4 is not in the context, so the model re-explains or guesses. It reads as not having listened, which is a strong "bot" signal.
- **Recommendation:** keep the most recent assistant turn whole and trim only older ones, or trim from the middle instead of the tail, within a character budget for the whole history. Write the budget beside the constant with the measured prompt-token cost. Test: a `test_stream_turns.py` case in which the last assistant turn over 2000 chars survives intact.

## Finding 7 — Once a conversation has a document, every later turn switches to a different persona with history pasted as a transcript
- **Severity:** major
- **Serving path:** `/chat/stream` step 2 → `_stream_document_response` → `DocumentService.chat_stream`
- **Location:** app/documents/service.py:181 (`"You are Atlas, an AI engineering platform."` fallback base), :190-196 (history as `role: content[:300]` lines for the last 6 messages, pasted into the user message); app/api/v1/chat/router.py:440-458 (base prompt from the intelligence engine, not `_STREAM_SYSTEM`)
- **Evidence:** `grep -n "session_messages\[-6:\]\|\[:300\]\|You are Atlas" app/documents/service.py` →
  ```
  181:        base = system_prompt or "You are Atlas, an AI engineering platform."
  192:            for msg in session_messages[-6:]:
  194:                content = msg.get("content", "")[:300]
  ```
  The project skill records the measured result of pasting history as a transcript: "made the model greet the user again every turn".
- **Failure scenario:** the user attaches a PDF once, then keeps chatting about anything. `_ensure_document_context` is true for the rest of the conversation (`router.py:761`), so the voice changes from the tuned `_STREAM_SYSTEM` to the intelligence-engine or "Atlas" prompt. Earlier replies are shortened to 300 characters, and history arrives as a pasted transcript, the pattern measured to cause repeated greetings.
- **Recommendation:** give document chat the same voice module as `_STREAM_SYSTEM` (the document rules appended) and the same `history=` role turns, rather than a transcript. Test: `DocumentService.build_document_prompt` returns no `## Previous Conversation` block, and `chat_stream` passes `history`.

## Finding 8 — The document-chat branch ignores a policy block from the intelligence engine and still calls the model
- **Severity:** major
- **Serving path:** `/chat/stream` step 2 (and `/chat/stream/vision` via router.py:1116)
- **Location:** app/api/v1/chat/router.py:456-458, :1116
- **Evidence:** `grep -n "is_blocked" app/api/v1/chat/router.py app/agents/orchestrator.py`:
  ```
  app/api/v1/chat/router.py:457:        if not engine_result.is_blocked:
  app/api/v1/chat/router.py:1116:        if not engine_result.is_blocked:
  app/agents/orchestrator.py:216:            if result.is_blocked:
  ```
  The orchestrator (orchestrator.py:216-222) returns `block_response` and `refused: True` without a model call. The router branch only skips *using the system prompt* and then streams `doc_service.chat_stream` regardless, with `system_prompt=""`, which falls back to "You are Atlas…".
- **Failure scenario:** in a conversation with an uploaded document, a message the policy stage blocks is answered by the model under a bare fallback persona, with no policy framing. This breaks the CLAUDE.md invariant "a blocked or ambiguous request must never reach the LLM".
- **Recommendation:** when `engine_result.is_blocked`, stream `engine_result.block_response` and do not call `doc_service.chat_stream`, as the orchestrator does. Test: a stub engine returning `is_blocked=True` and a fake `DocumentService` that fails if `chat_stream` is called. Not proven by mutation here; the claim rests on the executed grep plus the contrasting orchestrator code.

## Finding 9 — Edit and regenerate delete messages from the database but not from the Redis session the model reads
- **Severity:** minor
- **Serving path:** `/chat/stream` reads `get_session_messages` (router.py:747) → `delib.history`
- **Location:** app/api/v1/chat/router.py:1259-1297 (`truncate_messages_from`), :1301-1333 (`delete_single_message`); frontend/lib/hooks/use-chat.ts:375-417 (edit/regenerate call `truncateFrom` and then re-send)
- **Evidence:** `sed -n 1259,1340p router.py | grep -n "redis\|session"` shows no session or Redis call in either endpoint, only `sql_delete(...)`. The frontend `use-chat.ts:384,396,415` calls `truncateFrom` before re-sending.
- **Failure scenario:** the user regenerates a reply they disliked. The model still sees the old user message and the old answer in history (`SESSION_WINDOW = 20`), followed by the same question again. It tends to repeat itself, or to refer to an exchange the user deleted.
- **Recommendation:** rebuild the Redis session key from the remaining DB messages after a truncate or delete (or delete the key and fall back to DB history). Test: after truncate, `get_session_messages` excludes the removed turns.

## Finding 10 — Conversation memory for the model lives only in Redis with a 24-hour TTL, so reopening an older conversation starts from no context
- **Severity:** minor
- **Serving path:** `/chat/stream` step 3 history
- **Location:** app/redis_client.py:50-51 (`SESSION_WINDOW = 20`, `SESSION_TTL = 86400`); app/api/v1/chat/router.py:747
- **Evidence:** `grep -n "SESSION_TTL = \|SESSION_WINDOW = " app/redis_client.py` → `50:SESSION_WINDOW = 20`, `51:SESSION_TTL = 86400  # 24 hours`. `get_session_messages` reads only the Redis list, while `conv_repo` holds the full history in PostgreSQL.
- **Failure scenario:** the user returns the next day to a conversation visible in the UI and says "continue from step 3". The model has no history and answers as a stranger.
- **Recommendation:** when the Redis window is empty and the conversation has DB messages, hydrate from the last N DB messages. Test with a fake Redis returning `[]` and a conversation that has messages.

## Finding 11 — On `LLM_PROVIDER=ollama` the brain path streams at temperature 0.1 on `llama3.2:3b`
- **Severity:** minor (only applies when the deployment sets `LLM_PROVIDER=ollama`; the code default is `nvidia`)
- **Serving path:** `/chat/stream` step 3 → `OllamaClient.chat_stream` Ollama branch
- **Location:** app/ollama_client.py:439 (`temperature = 0.1 if temperature is None else temperature`); router.py:548-551 (passes no temperature); config.py:83 (`ollama_auto_model = "llama3.2:3b"`), :90 (`ollama_chat_temperature = 0.3 # slightly creative for richer prose`, not used on this path)
- **Evidence:** `grep -n` output above for those four lines. `pipeline._select_model` returns `ollama_auto_model` for mode `auto`.
- **Failure scenario:** a local Ollama deployment sends a 4.8k-character, nuance-heavy voice prompt to a 3B model at near-greedy temperature. Replies come out flat and repetitive, and the voice rules are mostly ignored.
- **Recommendation:** on the Ollama branch, fall back to `settings.ollama_chat_temperature` rather than the literal `0.1`, as `documents/service.py:243` already does. Choose the local conversational model by measurement. Unmeasured.

## Finding 12 — `_select_model` comments say `qwen3:8b`, the value it reads defaults to `llama3.2:3b`, and it can never pick the code model because `deliberate_turn` never passes `mode`
- **Severity:** note
- **Location:** app/cognitive_integration/pipeline.py:204, :211; app/cognitive_integration/service.py:44-58 (`Turn(...)` built without `mode`); router.py:785-788
- **Evidence:** `grep -n "mode" app/cognitive_integration/service.py` returns nothing, so `Turn.mode` is always its default `"auto"` (`ports.py:31`). `grep -n "dip_chat_model"` finds only `pipeline.py:211`, and `config.py` has no such field. On NVIDIA the `model` argument is ignored, so this affects only Ollama deployments.
- **Recommendation:** pass `agent_mode` into `deliberate_turn`/`Turn`, remove the `dip_chat_model` lookup, and correct the comments.

## Finding 13 — The voice reminder is sent as a `system` message after the conversation; whether the deployed model's chat template honours a non-leading system turn has not been verified
- **Severity:** note
- **Location:** app/cognitive_integration/pipeline.py:175-199; app/ollama_client.py:292-305
- **Evidence:** `probe_trunc.py` shows `roles sent: ['system', 'system', 'user']` on a first message. Mid-conversation the order is `system, user, assistant, …, system, user`.
- **Recommendation:** measure (see below). If the reminder turns out to be ignored or folded into the leading system message, send it as a short prefix inside the final user turn instead.

---

## Verified clean
- **Reasoning separation on the serving path.** `router.py:555-557` sends `ReasoningDelta` as `type: reasoning` and does not add it to `full`, the text saved at `router.py:562-569`. Checked by reading the route alongside `probe_trunc.py`, where reasoning and content arrive as different types.
- **Stream retry only before the first event.** `gateway.py:407-411` has `if emitted or not error.retryable ... raise`.
- **High-stakes gate still holds.** Real dangerous phrasings still escalate (Finding 1's probe). The recommendation narrows false positives and keeps the gate. `pytest tests/cognitive_integration --no-cov -p no:cacheprovider` → `27 passed in 0.25s`.
- **The intelligence engine's persona, strategy, format and review stages are off the default path.** `grep -rn "from app\.\(intelligence\|prompts\|agents\)" app/cognitive_integration` finds only the intent detector (`adapters_prod.py:58`). Editing `app/intelligence/persona/` or `app/prompts/modules/` will not change default chat replies.
- **DIP grounding and refusal invariants.** DIP is not on this path (`document_platform/conversation/` is reached only from the Knowledge Workspace). None of the recommendations touches `DIP_GROUNDING_MIN_SCORE`, `validator.py` or `REFUSAL_SENTENCE`.
- **Profile layer.** The cognitive route names a profile (`profile_for_mode(agent_mode)`) and passes no literal model, temperature or budget on the NVIDIA branch.

## Unmeasured claims (no live model calls were authorised)
There is no existing harness for streaming-chat voice. `scripts/e2e_chat_docs.py` covers documents only. To settle Findings 2–5, 11 and 13:

1. **Baseline vs. variant voice and thoroughness.** A script such as `scripts/e2e_chat_voice.py` would POST to `/api/v1/chat/stream` with `agent_mode=auto`:
   - Prompt set: 10 fixed prompts. Five one-line how/why questions, two that mention frustration, one "ok", one follow-up "go deeper on step N" after a long answer, and one containing "format".
   - Samples: **6 per prompt per variant** (120 calls for baseline + one variant).
   - Record per reply: word count, whether ordered steps appear, whether the first sentence references the message, whether the user's stated feeling is acknowledged in their words, `finish=length` from the gateway log, and first-token latency.
   - Accept the variant only if one-line how/why prompts reach a walkthrough in ≥5/6 samples, the acknowledgement stays ≤1 sentence, stock openers do not rise above the 2/6 baseline recorded in `pipeline.py:34-38`, and truncation is 0/6 at the chosen budget.
   - Write the rates beside the prompt, as the file already does.
2. **Budget.** The same 5 how/why prompts × 6 samples at `LLM_PROFILE_OVERRIDES={"general":{"max_tokens":4096}}` vs. 2048: truncation rate and p50/p95 first-token and total latency.
3. **Mid-conversation system turn (Finding 13).** 6 samples of a 4-turn conversation where earlier assistant turns greet, with the reminder as a `system` turn vs. as a user-turn prefix. Count greetings.
4. **Ollama branch (Finding 11).** Only if that deployment is in use: 6 samples × 5 prompts at temperature 0.1 vs. 0.3.

Checks run in scratch only (scratchpad `probe_escalation.py`, `probe_confirm.py`, `probe_trunc.py`). Nothing in the repository was modified apart from this report. No `.env` was read directly, though `resolve_profile("general")` resolved settings through the app's own loader.
