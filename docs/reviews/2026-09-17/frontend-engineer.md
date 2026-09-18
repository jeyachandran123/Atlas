---
role: frontend-engineer
repo: frontend
ref: a1bc2f7
date: 2026-09-17
scope: "Frontend chat path (reviewed from the backend reviews dir by request): lib/api/chat.ts, lib/hooks/use-chat.ts, lib/stores/chat-store.ts, components/chat/{chat-thread,streaming-message-bubble,message-markdown,message-bubble,tool-call-indicator,scroll-to-bottom,brain-meta}.tsx, app/api/backend/[...path]/route.ts, next.config.ts, .env.example; backend SSE emitters in app/api/v1/chat/router.py (backend ref dc9515c, clean) read to check what the client receives. User concern: the chat feels like a bot, not a person; answers should explain step by step; the chat UI should be better."
---

# Summary

**Verdict: the chat works, but six major defects make it feel mechanical. Fix them before any visual redesign.** Counts: 0 blocker, 6 major, 7 minor, 1 note.

The SSE parser matches what the backend sends. The mechanical feel comes from what happens around it:
- **Errors:** a failure mid-reply wipes the text the user was reading and puts a one-line raw Python exception in its place.
- **Waiting:** the only thing shown while waiting is a generic "Thinking…". The tool-progress UI exists, but no backend path ever sends it an event.
- **Long answers:** every token re-parses the whole markdown message, so the long step-by-step answers the user wants get slower as they grow (measured at 38 ms per token at 18k characters).
- **Code:** a code block without a language tag loses all styling and its copy button.
- **Session expiry:** the streaming request skips the 401-refresh path, so an expired session shows a raw "Stream request failed: 401" instead of refreshing quietly.

**Gates.** Frontend `pnpm type-check` exit 0. Scoped `eslint` on the six chat files printed nothing (clean). Repo-wide `pnpm lint` fails with 818 errors and 1029 warnings; those are already in the codebase and unrelated to this scope. The backend `team.conf` gates (`pytest` / `ruff` on what changed) do not apply because nothing changed: both trees are clean and I edited nothing. They were not run.

**How the evidence was gathered.** Scratch probe files were refused by the agent-scope hook, so the probes ran as Node ESM scripts fed through stdin. They loaded the frontend's own installed `react-markdown@9.1.0`, `remark-gfm@4.0.1`, `shiki@1.29.2`, `react-dom@19.2.7` and `zustand`, plus exact copies of the component and store logic they test.

## Finding 1 — A reply that fails mid-stream erases the text already streamed, including its reasoning
- **Severity:** major
- **Location:** components/chat/chat-thread.tsx:56 (the `handingOver` condition requires `!streamError`), components/chat/chat-thread.tsx:349
- **Evidence:** I replayed the store transitions from chat-store.ts:133-171 in real zustand and evaluated chat-thread.tsx:38-58 and :349 exactly as written:
  ```
  fail: mid-stream   : streamedChars=77 bubbleShown=true  textShown=77 reasoningShown=31 errorBanner=false
  fail: after error  : streamedChars=77 bubbleShown=false textShown=0  reasoningShown=0  errorBanner="httpx.ReadTimeout: timed out"
  ```
- **Failure scenario:** The user asks "explain this step by step". Three steps stream in, then the provider times out and the backend sends `{"type":"error"}` (router.py:856). All 77+ characters the user was reading disappear in the same render and a red one-line banner replaces them. The backend saves no partial reply either, so the text is gone for good.
- **Recommendation:** Keep the streamed text on screen when an error arrives. Mark it as interrupted inline, e.g. "I lost the connection partway through. Want me to pick up from here?", with Retry next to it. Showing the partial text should not depend on `!streamError`. Test: a store/thread test that applies token, token, then error, and asserts the partial content is still rendered next to the error.

## Finding 2 — Errors are shown as raw exception or HTTP text, clipped to one line
- **Severity:** major
- **Location:** components/chat/chat-thread.tsx:364 (`<span className="truncate">{streamError}</span>`), lib/api/chat.ts:109, backend app/api/v1/chat/router.py:856 (plus 4 more sites sending `'message': str(e)`)
- **Evidence:** `grep -n "Stream request failed" lib/api/chat.ts` returned `109: throw new Error(\`Stream request failed: ${response.status} — ${errText}\`)`. `grep -n 'className="truncate">{streamError}'` returned `364`. On the backend, `grep "'type': 'error', 'message': str(e)" app/api/v1/chat/router.py | wc -l` returned `5`.
- **Failure scenario:** When the backend is down, the user reads `Stream request failed: 502 — <html>…` cut off at the banner width. When the model times out, they read `httpx.ReadTimeout: timed out`. No person talks like that, and a long message is clipped so the user can't read it in full.
- **Recommendation:** Map the error type or HTTP status to a short first-person sentence on the client (network down, timed out, session expired, server error). Keep the raw text only in a "details" disclosure and the console. Allow the banner to wrap. Separately, the backend should stop sending `str(e)` to users. Test: a unit test of the mapping function for 401, 429, 5xx, network TypeError and a server error event.

## Finding 3 — The streaming request skips the shared 401 refresh, so an expired session fails the send
- **Severity:** major
- **Location:** lib/api/chat.ts:66-110 (compare lib/api/client.ts:25-63)
- **Evidence:** `grep -c "refresh" lib/api/chat.ts` returned `0`. `client.ts:57-59` has `// Auto-refresh on 401 and retry once … await refreshAccessToken()`. `streamChatMessage` reads `getAccessToken()` once and throws on `!response.ok`.
- **Failure scenario:** A laptop sleeps for 20 minutes. Background timers are throttled, so the proactive refresh (client.ts:41-51) never fires. The user wakes the machine and sends a message. Every other API call would refresh quietly, but the stream POST gets a 401 and shows `Stream request failed: 401 — {"detail":…}`. The user has to press Retry or reload.
- **Recommendation:** Export the single-flight `refreshAccessToken` from client.ts. In `streamChatMessage`, on a 401 before any bytes are read, call it once, rebuild the headers and replay the request. The FormData is still in scope. Test: mock `fetch` to return 401 then 200 with SSE frames, and assert one refresh call and events delivered. A second test runs two concurrent streams and asserts they share one refresh.

## Finding 4 — Every streamed token re-parses the whole message, so long step-by-step answers get slower as they grow
- **Severity:** major
- **Location:** lib/stores/chat-store.ts:144-145 (one `set` per token), components/chat/streaming-message-bubble.tsx:127, components/chat/message-markdown.tsx:84 (`memo` keyed on the whole `content`, which changes every token)
- **Evidence:** A probe rendered `ReactMarkdown` with `remarkGfm` on each 4-character prefix of a realistic answer with paragraphs, an ordered list and a table:
  ```
  chars=6060 renders=1515 total_ms=9258 avg_ms=6.11 last_render_ms=7.86
  chars=6060  one_full_parse_ms=19.5
  chars=18180 one_full_parse_ms=38.0
  ```
  That time is spent before React reconciles or the browser lays out the DOM.
- **Failure scenario:** The user gets what they asked for: a thorough answer of about 18k characters. Near the end, each token costs more than two 16 ms frames of main-thread work. The text arrives in jerks and the composer and scrolling lag behind. The longer and more thorough the answer, the less smooth it feels.
- **Recommendation:**
  - Batch token appends: buffer incoming text and flush once per `requestAnimationFrame`.
  - Split the streamed markdown into blocks at blank lines outside code fences. Memoise the finished blocks so only the last, still-growing block is re-parsed.
  - Optionally release buffered text at a steady characters-per-frame rate so large provider chunks read as natural typing instead of bursts.

  Test: a vitest render test that streams 5k tokens and asserts the finished blocks render once. Add a perf assertion on the number of `ReactMarkdown` renders per block.

## Finding 5 — A code block with no language tag loses all styling and its copy button
- **Severity:** major
- **Location:** components/chat/message-markdown.tsx:93-96 (`if (!match) return <code>{children}</code>`)
- **Evidence:** The probe copied the `code` override exactly:
  ```
  == A. fence without language ==
  <p>Run this:</p>
  <pre><code>cd app
  python main.py
  </code></pre>
  == A2. fence with language ==
  <pre><div data-codeblock="bash">[CodeBlock+copy]</div></pre>
  ```
  `grep` in app/globals.css found no `.assistant-content pre` rule. The only `pre` rule is the font reset at line 247, and `.assistant-content code:not(pre code)` (line 1048) excludes this case.
- **Failure scenario:** The model writes a step-by-step answer with a fence that has no language tag, which models often do for shell commands and output. The block renders as a bare, borderless `<pre>` with no background, header or copy button, and no horizontal scroll container. It looks broken next to the tagged blocks. The A2 output also shows every tagged `CodeBlock` nested inside the default `<pre>` (a `div` inside `pre`), because `pre` is never overridden.
- **Recommendation:** Override `pre` to render its child directly. Treat a `code` element as a block when its parent is a `pre` or its text contains a newline, not only when it has a `language-` class, and fall back to `CodeBlock language="text"`. Test: render the A and A2 inputs and assert both produce `.code-block` with a Copy button and no `pre > div`.

## Finding 6 — The tool-progress UI never runs, so the wait before a reply shows only a generic "Thinking…"
- **Severity:** major
- **Location:** lib/stores/chat-store.ts:147-155, components/chat/tool-call-indicator.tsx:17-42, components/chat/streaming-message-bubble.tsx:133-150; backend app/api/v1/chat/router.py:760-790 (turn routing and `deliberate_turn` run before the response starts)
- **Evidence:** In the frontend, `grep -rn "activeToolCall" components lib | wc -l` returned `14`, so the client is fully built for it. In the backend, `grep -rn "'type': 'tool_call'\|\"type\": \"tool_call\"" app | wc -l` returned `0`.
- **Failure scenario:** A user asks about their repo. The backend decides the file flow, checks document context, runs `deliberate_turn`, then loads memory, retrieves context and plans tools. During all of that the screen shows three dots and "Thinking…". The labels "Searching code" and "Reading file", with their rationale, are never shown. The user can't see what the assistant is doing, and that silent wait is a big part of why it feels like a bot.
- **Recommendation:** This needs a cross-team contract. The backend should send the SSE headers and `meta` immediately, then short `status` / `tool_call` events per stage, e.g. `{"type":"status","stage":"retrieving","label":"Looking through your repo"}`. The frontend should show them as a quiet running line in the first person ("Looking through `auth/`…", "Reading `client.ts`…") that folds into a "What I did" summary once the answer starts. Add the new event to `ChatStreamEvent` in types/api.ts in the same commit. Test: a store test that applies status then token and asserts the label shows and then folds.

## Finding 7 — The reasoning panel disappears the moment `done` arrives, before the saved reply replaces the bubble
- **Severity:** minor
- **Location:** components/chat/chat-thread.tsx:350 (`reasoning={isActiveStream ? streamingReasoning : ""}`)
- **Evidence:** The thread probe output: `ok: streaming : … reasoningShown=22` and then `ok: done,handover: bubbleShown=true textShown=9 reasoningShown=0`.
- **Failure scenario:** A reply with thinking turned on shows "Thought for 12s" above the answer. When `done` lands, the panel unmounts, the answer jumps up by the panel's height, and the reasoning can't be reopened. The backend never saves reasoning, so it is gone for good.
- **Recommendation:** Pass `streamingReasoning` during the handover as well. Decide with the AI/ML side whether to save a reasoning summary so "Thought for Ns" survives a reload. Test: a thread test asserting the reasoning is still rendered while `handingOver` is true.

## Finding 8 — The typing cursor renders on its own line below the text, and the saved reply replaces the bubble with a visible jump
- **Severity:** minor
- **Location:** components/chat/streaming-message-bubble.tsx:126-131
- **Evidence:** The probe rendered the bubble structure:
  ```
  <div class="assistant-content"><div class="assistant-content"><p>Step one is done.</p></div><span class="inline-block animate-cursor"></span></div>
  ```
  The cursor span comes after a block-level `div`, so it wraps onto a new line.
- **Failure scenario:** While a reply streams, the caret blinks on an empty line under the paragraph instead of at the end of the last word, which looks like a terminal rather than someone typing. At handover the extra line (about 26px at line-height 1.75) disappears, so the thread jumps. The nested `.assistant-content` wrapper also doubles the `> *:first-child` / `> *:last-child` margin rules.
- **Recommendation:** Render the caret inside the last block, either with a rehype plugin that appends it to the last text node or with a CSS `::after` on `.streaming > :last-child`. Drop the outer duplicate wrapper. Test: a render test asserting the caret is a descendant of the last `p` or `li`.

## Finding 9 — After sending, no "new content below" signal is shown while the answer grows past the bottom of the screen
- **Severity:** minor
- **Location:** components/chat/chat-thread.tsx:218
- **Evidence:** `grep -n "!pinned && (isActiveStream"` returned `218: } else if (!pinned && (isActiveStream || activeStreamContent)) {`. While `pinned` is true, `hasNewBelow` is never set, and following is turned off at chat-thread.tsx:187.
- **Failure scenario:** The user sends a question and the prompt moves to the top. A long step-by-step answer soon grows past the bottom of the screen. The scroll button appears because `atBottom` is false, but it has no pulse or dot, so nothing says the answer is still being written below.
- **Recommendation:** While pinned, set `hasNewBelow` once the streaming bubble's bottom edge passes the viewport's bottom edge. Test: a thread test with a mocked `scrollHeight` / `clientHeight`.

## Finding 10 — Edit and Retry always resend in "auto" mode, whatever mode the conversation used
- **Severity:** minor
- **Location:** lib/hooks/use-chat.ts:385, lib/hooks/use-chat.ts:397
- **Evidence:** `grep -n 'send(.*"auto"' lib/hooks/use-chat.ts` returned `385: send(newText, repoId, "auto", …)` and `397: send(content, repoId, "auto", …)`. Compare chat-thread.tsx:333, where the clarify card uses `useChatStore.getState().agentMode`.
- **Failure scenario:** A user in "business" mode edits a question. The reply comes from `ollama_auto_model` with the auto profile, so the assistant's voice and depth change mid-conversation for no visible reason.
- **Recommendation:** Use `useChatStore.getState().agentMode` in both calls, matching the clarify path. Test: a hook test asserting the payload's `agent_mode` equals the store's mode on retry.

## Finding 11 — The language regex cuts common names short, so the wrong highlighter and label are used
- **Severity:** minor
- **Location:** components/chat/message-markdown.tsx:92 (`/language-(\w+)/`)
- **Evidence:** Probe output: `c++ -> c`, `objective-c -> objective`, `shell-session -> shell`, `c# -> c`.
- **Failure scenario:** A C# snippet in a fence tagged `c#` is labelled and highlighted as C, and `objective` is not a Shiki language, so highlighting fails silently.
- **Recommendation:** Use `/language-([^\s]+)/` and map aliases (`c#` to `csharp`, `c++` to `cpp`). Test: a table test over those inputs.

## Finding 12 — If NEXT_PUBLIC_STREAM_BASE_URL is unset, the reply arrives all at once, and .env.example never mentions the variable
- **Severity:** minor
- **Location:** lib/api/chat.ts:7-10, app/api/backend/[...path]/route.ts:57, .env.example:4-7
- **Evidence:** `grep -n "arrayBuffer()"` on the proxy returned `57: const resBody = await upstream.arrayBuffer();`. `grep -c "STREAM_BASE" .env.example` returned `0`. `.env.local:9` and `.env.production:12` do set it, so configured environments are unaffected.
- **Failure scenario:** A new developer copies `.env.example`. `STREAM_BASE` falls back to `/api/backend`, and the proxy waits for the whole SSE body before responding. The user watches "Thinking…" for the full generation time, then the answer appears in one piece. The `X-Accel-Buffering` headers in next.config.ts:9-18 don't help, because the handler itself buffers.
- **Recommendation:** Add `NEXT_PUBLIC_STREAM_BASE_URL` to .env.example with the reason. Better, make the proxy return `new NextResponse(upstream.body, …)` for `text/event-stream`, so the same-origin path streams and the direct cross-origin call is no longer needed. Test: an integration check that the first SSE frame reaches the client before the upstream closes.

## Finding 13 — A `clarify` event during the stream is ignored, so its questions appear only after the stream ends
- **Severity:** minor
- **Location:** lib/stores/chat-store.ts:134-162 (no `case "clarify"`), types/api.ts:262 (the event is declared)
- **Evidence:** `grep -n 'case "' lib/stores/chat-store.ts` lists `file_stage, file, reasoning, token, tool_call, error, done`, with no `clarify`. The backend sends `{"type":"clarify",…}` at app/chat_artifacts/service.py:262.
- **Failure scenario:** The user asks for a file and the assistant needs to ask questions first. The questions exist, but the bubble keeps showing "Thinking…" until `done` and the messages refetch, then the card appears all at once.
- **Recommendation:** Handle `clarify` in the store: stop the thinking indicator and show a short line such as "I have a couple of questions first". Test: a store test for the clarify case.

## Finding 14 — The component for Cognitive OS metadata is never used, and the `done` metadata is dropped
- **Severity:** note
- **Location:** components/chat/brain-meta.tsx:28, lib/stores/chat-store.ts:159-161
- **Evidence:** `grep -rln "brain-meta" app components lib | wc -l` returned `0`. The `done` case stores none of `confidence`, `decision`, `escalated` or `intent`.
- **Failure scenario:** A held reply ("Held for review") looks exactly like a normal answer, with no badge saying why. In its current form the component would also add a bot-like "decision: approve · intent: …" row, which works against the goal.
- **Recommendation:** Decide deliberately. Either delete it, or show only the human-meaningful part: the escalation note, and perhaps a hedge when confidence is low, worded in the first person.

## Verified clean
- **SSE framing:** client and server agree. The backend sends `data: {json.dumps(...)}\n\n` everywhere, with single-line JSON and the `meta` frame first (router.py:699, 824-856). The client splits on `\n\n` and keeps the unfinished remainder (chat.ts:120-124). No multi-line `data:` or `event:` lines are sent, so the parser's single-`data:` assumption holds.
- **Stop/abort:** an `AbortError` resolves through `onComplete` (chat.ts:144-146). `stop()` invalidates messages so the stopped prompt gets its real id (use-chat.ts:402-408).
- **Token handling:** the Bearer token is read from memory (`getAccessToken`) and sent only in the `Authorization` header. It never appears in a URL or web storage (chat.ts:87, 100).
- **Scroll following:** instant `scrollTop` rather than a smooth scroll per token, and wheel or touch intent stops following before the next token (chat-thread.tsx:157-164, 213-217).
- **Shiki highlighting per token:** cheap. The probe measured 232 highlight calls over a 930-character TS block, 483 ms total, about 2 ms each. Not a cause of jank.
- **Store isolation:** streaming state lives in zustand with per-field selectors in chat-thread.tsx:22-35, so the sidebar doesn't re-render per token.
- **Type-check:** `pnpm type-check` exit 0. Scoped `npx eslint` over the six chat files printed no findings.
