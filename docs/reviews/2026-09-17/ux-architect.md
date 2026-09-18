---
role: ux-architect
repo: frontend (filed in backend at the caller's request; backend locations are marked "backend/")
ref: frontend a1bc2f7, backend dc9515c (both clean)
date: 2026-09-17
scope: "Why chat feels like a bot / make it human and step-by-step / better chat UI" — frontend components/chat/**, components/workspace/conversation-view.tsx, workspace-composer, message-actions, components/knowledge/stage-indicator.tsx, lib/hooks/use-chat.ts, lib/stores/chat-store.ts, app/globals.css chat rules; backend app/api/v1/chat/router.py stream paths that feed them
---

# Summary

Verdict: **changes recommended, no blockers.** 5 major, 8 minor, 8 notes. The chat feels mechanical less because of how it looks and more because of how it behaves when things go off the happy path. A reply you stop or that fails disappears. Errors show up as raw exception text on one cut-off line. Edit and retry quietly switch to a different model. The workspace thread drags you to the bottom on every token. On top of that come machine words ("Assembling context", "S1", "1.2k tokens") and a reading layout that does not help with long step-by-step answers. Limits: this repo has no UI tests, I cannot see screenshots, and nothing was rendered. Every visual claim below comes from the code and CSS, not from a screen.

## Finding 1 — A reply that is stopped or fails vanishes from the thread, including the text the user was already reading
- **Severity:** major
- **Location:** frontend components/chat/chat-thread.tsx:55-58 and :349; backend app/api/v1/chat/router.py:814-856
- **Evidence:**
  ```
  $ sed -n 48,58p components/chat/chat-thread.tsx
  // ... The hand-over ends when the reply is the
  // last message, or when fresh data from after the stream arrives (a stopped
  // or failed turn saves no reply). ...
  const handingOver = !isActiveStream && !streamError && streamEndedAt !== null ...
  $ grep -n "(isActiveStream || handingOver)" components/chat/chat-thread.tsx
  349:                {(isActiveStream || handingOver) && (
  $ grep -rn "CancelledError\|GeneratorExit\|is_disconnected" backend/app/api/v1/chat/router.py
  (no output)   # the generator catches only Exception; full_response is saved only after the loop finishes (router.py:833)
  ```
- **Failure scenario:** The user asks for a 12-step setup guide and presses Stop at step 6 because they have what they need. `streamEndedAt` is set, the messages refetch comes back with no assistant row, `handingOver` turns false, and steps 1–6 disappear. The same happens on an error: `streamError` makes `handingOver` false straight away, so the partial answer is swapped for a red banner. A person who stops talking has still said what they said. Here the words are taken back.
- **Recommendation:** Keep the partial text as a finished bubble marked "Stopped" or "Interrupted — the answer is incomplete". The backend option is to save `full_response` with a status on client disconnect (catch `asyncio.CancelledError`, or a `finally` that saves). The frontend-only option is to keep `streamingContent` for that turn until the next send. To test it, simulate `stop()` mid-stream in a component test and assert the partial text is still in the DOM with an "incomplete" label.

## Finding 2 — Stream errors show the raw Python exception string, cut to one line
- **Severity:** major
- **Location:** backend app/api/v1/chat/router.py:856 (and 7 more emit sites); frontend components/chat/chat-thread.tsx:364
- **Evidence:**
  ```
  $ grep -rn "'type': 'error', 'message': str(e)\|\"message\": str(e)" app/api app/workspace | wc -l
  8
  $ grep -n "streamError}" components/chat/chat-thread.tsx
  364:                      <span className="truncate">{streamError}</span>
  ```
- **Failure scenario:** Ollama at the default LAN host is unreachable, so the user sees something like `ConnectError: All connection attempts failed` (or an SQLAlchemy message), ellipsised at the width of the banner. It is jargon, it may expose internals, and on a phone it cannot be read. This is the least human moment in the product. (The workspace conversation gateway already does the right thing: it sends "The response could not be generated." and logs the detail, see backend app/document_platform/conversation/gateway.py:273.)
- **Recommendation:** Send a stable error `code` and a sentence a person can act on, and log `str(e)` server-side only. In the UI, render the sentence in full (no `truncate`), in first person ("I couldn't reach the model just now — try again in a moment"), and keep Retry. Add a test that a raised `RuntimeError("secret detail")` yields an SSE error frame without `secret detail`.

## Finding 3 — Edit and Retry resend in "auto" mode, whatever mode the composer shows
- **Severity:** major
- **Location:** frontend lib/hooks/use-chat.ts:385 and :397
- **Evidence:**
  ```
  $ grep -n 'send(.*"auto"' lib/hooks/use-chat.ts components/chat/chat-thread.tsx
  lib/hooks/use-chat.ts:385:      send(newText, repoId, "auto", files.length > 0 ? files : undefined);
  lib/hooks/use-chat.ts:397:      send(content, repoId, "auto", files.length > 0 ? files : undefined);
  components/chat/chat-thread.tsx:416:              send(msg, selectedRepoId ?? undefined, agentId ?? "auto", files);
  $ grep -n "agentMode" components/chat/chat-input.tsx
  87:  const agent = useChatStore((s) => s.agentMode);
  ```
- **Failure scenario:** The user picks "Reasoning — deepest model, step by step" (chat-input.tsx:33-34), gets a shallow answer, edits the question to say "explain each step thoroughly", and sends. The resend goes out as `auto`, a different model with a different depth, while the picker still says Reasoning. The UI is stating something the request did not do, and it hits exactly the user who is asking for more thorough explanations.
- **Recommendation:** Pass `useChatStore.getState().agentMode` in both calls, as `onClarifySubmit` already does (chat-thread.tsx:333). Add a unit test that sets `agentMode="reasoning"`, calls `retry`, and asserts the payload's `agent_mode`.

## Finding 4 — The workspace thread smooth-scrolls to the bottom on every streamed token, pulling the reader away from what they are reading
- **Severity:** major
- **Location:** frontend components/workspace/conversation-view.tsx:185
- **Evidence:**
  ```
  $ grep -n "scrollIntoView" components/workspace/conversation-view.tsx
  185:  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [items]);
  $ sed -n 110,113p components/chat/chat-thread.tsx
  // The rule: follow new content only while the reader is at the bottom. The
  // moment they scroll up, they are reading something, and a streaming reply
  // must not drag them away from it.
  ```
- **Failure scenario:** `items` changes on every `token` event (lines 236-238). A long step-by-step answer streams in 40-character slices (backend gateway STREAM_SLICE). The reader scrolls up to re-read step 2, and the next slice snaps them back down. The main chat fixed this exact problem. The workspace surface still has it, so the two chat surfaces behave differently.
- **Recommendation:** Reuse the chat-thread follow and pin logic (follow only while near the bottom, pin the question to the top on send, "new below" button). Ideally pull it out into a shared hook so both surfaces use one implementation.

## Finding 5 — A network failure on a workspace question leaves the question with no reply in the thread; the only sign is a toast
- **Severity:** major
- **Location:** frontend components/workspace/conversation-view.tsx:250 and :632-637
- **Evidence:**
  ```
  $ sed -n 250p components/workspace/conversation-view.tsx
        () => { setBusy(false); patchAsk(key, { current: null }); toast.error("The response could not be generated."); },
  $ sed -n 637p components/workspace/conversation-view.tsx
                  {(item.answer || item.error) && (
  ```
- **Failure scenario:** The backend restarts while a question is pending. `onError` never sets `item.error`, so `answer === ""` and `error === null`. The stage indicator hides because `busy` is false, and the bubble does not render. The toast fades after a few seconds, and what is left is a question that looks unanswered, with no reason and no retry button next to it. "Unknown" ends up looking like "nothing happened".
- **Recommendation:** `patchAsk(key, { error: "I lost the connection before I could answer." , grounded: false })` in `onError`, and show Retry inside that bubble.

## Finding 6 — "N tokens" on hover is an estimate (characters ÷ 4) shown as a measured count
- **Severity:** minor
- **Location:** frontend components/chat/message-bubble.tsx:310-313; backend app/api/v1/chat/router.py:830 (also :479, :560, :642)
- **Evidence:**
  ```
  $ grep -rn "tokens_used\s*=" app/api/v1/chat/router.py
  app/api/v1/chat/router.py:479:            tokens_used = len(full_response) // 4
  app/api/v1/chat/router.py:560:            tokens_used = max(1, len(full) // 4)
  app/api/v1/chat/router.py:642:                agent_used=agent_used, tokens_used=max(1, len(content) // 4),
  app/api/v1/chat/router.py:830:            tokens_used = len(full_response) // 4
  $ grep -n "tokens_used > 0" -A3 components/chat/message-bubble.tsx
  310:          {message.tokens_used > 0 && (
  312:              {formatTokenCount(message.tokens_used)} tokens
  ```
- **Failure scenario:** A 4,800-character answer shows "1.2k tokens" as if the provider reported it. It is a fabricated figure, and it is also developer vocabulary sitting under a conversational reply.
- **Recommendation:** Remove it from the chat bubble, or show it only in a developer/details view labelled "≈ estimated". If a real count is needed, take it from the provider's usage field.

## Finding 7 — Main-chat message actions are hover-only: invisible on touch, and invisible while focused by keyboard
- **Severity:** minor
- **Location:** frontend components/chat/message-bubble.tsx:274 and :309
- **Evidence:**
  ```
  $ grep -rn "opacity-0 transition-opacity group-hover:opacity-100" components/chat
  components/chat/message-bubble.tsx:274: ... opacity-0 transition-opacity group-hover:opacity-100">
  components/chat/message-bubble.tsx:309: ... opacity-0 transition-opacity group-hover:opacity-100">
  $ grep -rn "focus-within:opacity-100" components/chat components/workspace
  components/workspace/message-actions.tsx:40: ... group-hover:opacity-100 focus-within:opacity-100 ...
  ```
- **Failure scenario:** On a phone there is no hover, so Copy / Edit / Retry on an answer never appear. A keyboard user tabs onto Copy and focus lands on a button they cannot see. The workspace version already handles focus, the main chat does not.
- **Recommendation:** Add `focus-within:opacity-100`. Always show the actions on the latest assistant message, and use `@media (hover: none)` to show them on touch.

## Finding 8 — The streaming answer is not announced to assistive technology
- **Severity:** minor
- **Location:** frontend components/chat/streaming-message-bubble.tsx:126-133
- **Evidence:**
  ```
  $ grep -rn "aria-live\|role=\"log\"" components/chat components/workspace components/knowledge
  components/chat/voice-input.tsx:74:      aria-live="polite"
  components/knowledge/stage-indicator.tsx:34: ... role="status" aria-live="polite">
  ```
- **Failure scenario:** A screen-reader user hears "UnityWorks is thinking" (line 134). Once tokens start, that status node unmounts and nothing announces the answer or the fact that it finished.
- **Recommendation:** Put `role="log" aria-live="polite"` on the message list. Announce "Answer ready" once on `done` rather than on every token.

## Finding 9 — Wide markdown tables have no horizontal scroll container
- **Severity:** minor
- **Location:** frontend app/globals.css:1012-1020; components/chat/message-markdown.tsx:89 (no `table` renderer)
- **Evidence:**
  ```
  $ grep -n "table\|ol(\|li(\|a(\|h2(" components/chat/message-markdown.tsx
  (no output — only `code` is overridden)
  $ sed -n 1012,1020p app/globals.css
  .assistant-content table { width: 100%; ... border-radius: 10px; overflow: hidden; }
  ```
- **Failure scenario:** A step-by-step comparison with 6 columns inside the 768px column (or a 390px phone) gets squeezed into one-word lines, or runs past the column. Nothing lets the user scroll it.
- **Recommendation:** Add a `table` component override that wraps the table in `<div class="table-scroll" style="overflow-x:auto">`, and move the border radius to the wrapper.

## Finding 10 — The tool-call narration, the one place the assistant says why it is doing something, is cut off at 200px and dimmed to 50%
- **Severity:** minor
- **Location:** frontend components/chat/tool-call-indicator.tsx:35
- **Evidence:**
  ```
  $ grep -n "max-w-\[200px\]" components/chat/tool-call-indicator.tsx
  35:              <span className="max-w-[200px] truncate opacity-50">— {call.rationale}</span>
  ```
- **Failure scenario:** The rationale "Looking at auth/session.ts to see where the refresh token is rotated" shows as "— Looking at auth/session.ts to…" in half-opacity text, next to a generic "Searching code" label. The human part is hidden and the mechanical label is what stands out. The indicator also disappears on the first token (chat-store.ts:145), so the finished answer keeps no trace of what was checked.
- **Recommendation:** Let the rationale wrap at full contrast, as a first-person line ("Checking how the refresh token is rotated…"). Keep a collapsed "What I looked at" list on the finished message, fed from the sequence of tool calls rather than just the last one.

## Finding 11 — Workspace answers to document-task questions are rendered as plain text, not markdown
- **Severity:** minor
- **Location:** frontend components/workspace/conversation-view.tsx:702-704
- **Evidence:**
  ```
  $ grep -n "whitespace-pre-wrap" components/workspace/conversation-view.tsx
  702:  <div className="rounded-2xl rounded-bl-md px-4 py-3 text-[13px] whitespace-pre-wrap" ...>
  703:    {item.answer}
  ```
- **Failure scenario:** A computed answer containing `**Total:** 1,251 rows` or a numbered list shows literal asterisks and hashes, while the answer bubble right next to it (line 642) renders markdown properly.
- **Recommendation:** Use `<MessageMarkdown content={item.answer} />` here as well.

## Finding 12 — Workspace and knowledge question bubbles collapse the user's own line breaks
- **Severity:** minor
- **Location:** frontend components/workspace/conversation-view.tsx:622-624
- **Evidence:**
  ```
  $ grep -n "{item.question}\|{turn.question}" -B2 components/workspace/conversation-view.tsx | grep className
  622-                    <div className="rounded-2xl rounded-br-md px-4 py-2.5 text-[13.5px]"
  $ grep -n "whitespace-pre-wrap" components/chat/message-bubble.tsx
  430:    return <p className="whitespace-pre-wrap">{content}</p>;
  ```
- **Failure scenario:** The user types "1. install\n2. configure\n3. deploy — explain each". The workspace bubble shows it as one run-on line. The main chat keeps the lines.
- **Recommendation:** Add `whitespace-pre-wrap` to the workspace and knowledge question bubbles.

## Finding 13 — Generated documents still in progress on reload are shown as "ready" items: no progress, no status, only a Delete button
- **Severity:** minor
- **Location:** frontend components/workspace/conversation-view.tsx:176; backend app/document_platform/generation/lifecycle.py:9-14
- **Evidence:**
  ```
  $ sed -n 176p components/workspace/conversation-view.tsx
      status: a.status === "ready" ? "ready" : a.status === "cancelled" ? "cancelled" : a.status === "failed" ? "failed" : "ready",
  $ grep -n "REQUESTED\|PLANNING\|STORING\|READY" backend/app/document_platform/generation/lifecycle.py
  9:    REQUESTED = "requested"   10: PLANNING = "planning"   13: STORING = "storing"   14: READY = "ready"
  ```
- **Failure scenario:** The user reloads while a PDF is at `planning`. The item is treated as finished, so there is no "Preparing document…" row. `GeneratedDocumentCard` shows neither Completed nor Failed, and offers Delete but no View. An unknown state is presented as done.
- **Recommendation:** Map any non-terminal status to `"running"` and poll restore until it becomes terminal.

## Finding 14 — Hard-coded hex colours in the tool indicator instead of theme tokens
- **Severity:** note
- **Location:** frontend components/chat/tool-call-indicator.tsx:8-13; components/chat/message-markdown.tsx:63
- **Evidence:**
  ```
  $ grep -rnoE "#[0-9a-fA-F]{6}\b" components/chat/tool-call-indicator.tsx
  :8 #60a5fa  :9 #fb923c  :10 #4ade80  :11 #818cf8  :13 #818cf8
  ```
- **Failure scenario:** In light theme, `#4ade80` text on an 8% green tint is low-contrast. Tool calls each get their own colour (blue/orange/green), which looks like a dashboard, not a conversation.
- **Recommendation:** One neutral, token-based style for every tool narration line (`--text-secondary` on `--surface-1`), with the icon carrying the difference.

## Finding 15 — Stage labels and citation chips use pipeline vocabulary
- **Severity:** note
- **Location:** frontend components/knowledge/stage-indicator.tsx:12-13, :17, :20; components/workspace/conversation-view.tsx:84
- **Evidence:**
  ```
  $ grep -n "preparing_prompt\|generating_answer\|AI is planning\|Uploading to storage" components/knowledge/stage-indicator.tsx
  12:  preparing_prompt: "Assembling context",
  13:  generating_answer: "Generating answer",
  17:  planning: "AI is planning the document",
  20:  storing: "Uploading to storage",
  ```
  The chat's own file stages speak like a person ("Reading your spreadsheet", "Checking every row against your request" — streaming-message-bubble.tsx FILE_STAGE_LABELS). Citation chips render `source_id` ("S1 · p.3"), and confidence is visible only in a `title` tooltip.
- **Failure scenario:** The same product speaks in two voices, and the workspace one reads like a job log.
- **Recommendation:** Rewrite the labels in the chat's voice ("Reading the passages that matched", "Writing your answer", "Saving your file"). Show citations as the document name + page ("Handbook.pdf, p. 3") and keep `S1` as the in-text anchor only.

## Finding 16 — The model's visible thinking disappears as soon as the reply is saved
- **Severity:** note
- **Location:** frontend components/chat/chat-thread.tsx:350; lib/stores/chat-store.ts:42
- **Evidence:**
  ```
  $ grep -n "never saved" lib/stores/chat-store.ts
  42:  /** The model's reasoning for the message being streamed — never saved. */
  $ grep -n "reasoning={isActiveStream ? streamingReasoning" components/chat/chat-thread.tsx
  350: ... reasoning={isActiveStream ? streamingReasoning : ""} ...
  ```
- **Failure scenario:** The user watches "Thinking…" and then "Thought for 14s". When the saved message replaces the streamed one, the fold disappears, so the "how I got here" is gone at the moment they want to check it. This is honest (nothing is kept), but it takes away the part that felt the most human.
- **Recommendation:** A product decision for the backend owner: save reasoning (or a short summary) with the message and show it as a collapsed "How I worked this out". Until then, leave it as it is. Do not fake it.

## Finding 17 — "Thought for Ns" counts from the first reasoning token, not from when the user sent
- **Severity:** note
- **Location:** frontend components/chat/streaming-message-bubble.tsx:45 and :79
- **Evidence:**
  ```
  $ grep -n "startedAt = useRef\|Thought for" components/chat/streaming-message-bubble.tsx
  45:  const startedAt = useRef<number>(Date.now());
  79:        {answering && seconds !== null ? `Thought for ${seconds}s` : "Thinking…"}
  ```
- **Failure scenario:** 20s of prep (intelligence_prepare, retrieval) plus 5s of reasoning shows "Thought for 5s". The number is right about reasoning but reads as the whole wait.
- **Recommendation:** Label it "Reasoned for 5s", or measure from `startStream`.

## Finding 18 — Long step-by-step answers get no structural reading aids, and step numbers are styled as muted text
- **Severity:** note
- **Location:** frontend app/globals.css:971-975; components/chat/prompt-navigator.tsx (lists prompts only)
- **Evidence:**
  ```
  $ sed -n 971,975p app/globals.css
  .assistant-content ol > li::marker { color: var(--text-tertiary); font-variant-numeric: tabular-nums; font-weight: 500; }
  ```
  The body typography is already good for long reading (14.5px / 1.75 line-height, 768px measure — globals.css:908-912). What is missing is structure.
- **Failure scenario:** A 15-step answer is one long column in which the numbers, which are how a reader navigates it, are the faintest text on the page. There is no way to see "step 7 of 15" or jump to a section.
- **Recommendation:** Give ordered-list markers full contrast, maybe as small numbered discs, with more space between top-level items. Add anchor links on h2/h3 and a "Sections" jump list on answers with 3 or more headings (the prompt navigator could show the headings of the active answer). Put a "Copy step" affordance on top-level list items.

## Finding 19 — `BrainMeta` is unused, and as written it uses emoji icons, a hard-coded palette, internal jargon and colour-only confidence
- **Severity:** note
- **Location:** frontend components/chat/brain-meta.tsx:34, :47, :51, :56
- **Evidence:**
  ```
  $ grep -rn "BrainMeta\|brain-meta" app components lib | grep -v brain-meta.tsx
  (no output)
  $ grep -n "🧠\|⏸\|decision: \|intent: " components/chat/brain-meta.tsx
  34:        🧠 Cognitive OS
  47:        <span className="text-muted-foreground">decision: {decision}</span>
  51:        <span ...>intent: {intent}</span>
  56:          ⏸ Held for your review — ...
  ```
- **Failure scenario:** If someone wires it in to "show the mind", every reply gets "🧠 Cognitive OS · decision: respond · intent: explain": the most bot-like line possible.
- **Recommendation:** Delete it, or rebuild it on lucide icons and tokens with plain-language wording before using it.

## Finding 20 — The streaming cursor is placed after a block-level wrapper, so it probably appears on its own line under the text
- **Severity:** note
- **Location:** frontend components/chat/streaming-message-bubble.tsx:127-129; components/chat/message-markdown.tsx:86
- **Evidence:**
  ```
  $ grep -n '<div className="assistant-content">' components/chat/message-markdown.tsx
  86:    <div className="assistant-content">
  $ grep -n "<MessageMarkdown content={content}\|animate-cursor" components/chat/streaming-message-bubble.tsx
  127:            <MessageMarkdown content={content} />
  129:              className="ml-0.5 inline-block h-[1em] w-0.5 ... animate-cursor"
  ```
  Not rendered: I cannot see screenshots, and this is inferred from the block/inline structure.
- **Failure scenario:** Instead of the text appearing to be typed, a blinking bar sits under the paragraph.
- **Recommendation:** Check this in the browser. If confirmed, drop the separate cursor and use a CSS `::after` on the last child of `.assistant-content` while streaming.

## Finding 21 — Cross-reference (outside UX scope): the backend defaults conversation and follow-ups to "brief"
- **Severity:** note
- **Location:** backend app/intelligence/prompting/depth_planner.py:58 and :144
- **Evidence:**
  ```
  $ grep -n "general_chat\|Follow-ups and corrections" app/intelligence/prompting/depth_planner.py
  58:    "general_chat":        "brief",
  144:    # Follow-ups and corrections should be brief — don't repeat everything
  $ grep -n "Be concise and direct" app/intelligence/prompting/depth_planner.py
  87:            "Be concise and direct. Answer the question clearly in 1-3 paragraphs. "
  ```
- **Failure scenario:** "Can you walk me through that?" is a follow-up, so it is capped at "brief", which is the opposite of explaining step by step. No UI change can fix what the prompt tells the model to leave out.
- **Recommendation:** Hand to ai-ml-architect. Not reviewed further here.

## Verified clean
- Main-chat scroll behaviour: follows only while at the bottom, pins the sent prompt to the top, "new below" button (chat-thread.tsx:108-236). Read, and consistent with the wheel/touch intent handlers.
- Empty state: a time-of-day greeting with the user's first name and plain first-person copy, no fabricated numbers (chat-thread.tsx:430-499).
- Grounding honesty in the workspace: the "Grounded" badge only renders when the backend's `citations` frame sets `grounded` (conversation-view.tsx:240, :644). The live document-task artifact's `grounded: true` (conversation-view.tsx:301) matches what the backend saves (`grep -n "grounded=True" backend/app/document_platform/execution/gateway.py` → 146), so it is not fabricated.
- Refusals render as answers with a "No source found" badge, not as errors (backend conversation/gateway.py:214-235 streams the refusal as tokens).
- Clarify and file cards are excluded from Copy so raw JSON is never copied (message-bubble.tsx:316).
- Icon-only controls in scope have accessible names: Copy code (message-markdown.tsx), ActionBtn `aria-label` (message-bubble.tsx:392), Stop/Send (chat-input.tsx:552, :572).
- Reduced motion is honoured globally (globals.css:420).
- `pnpm type-check` (tsc --noEmit) ran from frontend/ and printed no errors.
- Not run: there are no frontend unit/e2e tests (per project CLAUDE.md) and no rendered check was done. No finding above is claimed as visually confirmed.
