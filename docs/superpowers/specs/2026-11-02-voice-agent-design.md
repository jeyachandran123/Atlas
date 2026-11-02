# Voice Agent in Chat: Design

Status: awaiting approval. Spans `backend/` and `frontend/`, which are separate git repositories.

## Intent

People should be able to talk to Atlas out loud from any chat, the way ChatGPT's voice mode works. It is the same assistant in the same conversation, reached by voice. It knows what has been said in that chat, can discuss it, and can talk about anything else.

The voice screen is also a signature moment for the product. The owner's bar: it must look and feel like work worth $5,000, not a cheap template, and it must be technically solid.

## Decided by the owner

- A voice session starts from the blue waveform button in the chat composer, beside Think and the microphone.
- The voice model is Gemini's, using a Gemini API key held in the backend `.env`.
- It works in every chat and has that chat's context. It is a chat voice agent, not a concierge or a separate product.
- When the session ends, what was said stays in the chat as normal text messages. The person can carry on typing and Atlas remembers it.
- The layout is full screen: the chat steps away, leaving the orb, a status word, a live caption and the controls (mockup option A).
- The orb follows the owner's reference image: thousands of fine dots forming a soft, folded, organic sphere, blue flowing into violet, on a near-black field.
- The screen is built on our existing theme and UI, not a separate look.

Reference images: [the orb](assets/voice-agent/orb-reference.jpg) and [the composer button](assets/voice-agent/composer-button-reference.png). Prototype the orb and check it against the image before building the session work. The owner judges it by eye.

- **Safety checks.** Voice connects directly to Gemini. The server's per-turn policy gates cannot run before an answer, so the safety rules go in the locked system instruction, and the server sees turns only when they are saved. This is an accepted exception to "a blocked request never reaches the LLM".
- **Attachments.** The session passes in the extracted text of the chat's PDF and Word files, within a size limit. Answers from them carry no `[S#]` citations. For images, Atlas says it can't see them by voice.
- **Gemini plan.** The owner's key is on the free plan, and the owner chose to use it. Free-plan terms may let Google use content to improve its products; this applies to real company conversations too.

## Calls made by the designer, for the owner to check

- **One voice persona.** The selected mode (Auto, Code, Business) does not change voice.
- **Session limits.** A session ends gracefully at 30 minutes, the default life of the token, and after 5 minutes of silence. Both are explained on screen, and the transcript is kept. This also limits Gemini cost from an overlay left open.
- **Availability.** Everyone who can use chat gets voice once `GEMINI_API_KEY` is set. No staged rollout.
- **Where "done" applies.** Local stack first, then the deployed stack before release. If Render's free tier is still sleeping, the first tap after idle will wait on the backend, so production needs an always-on tier for "talking within a moment".
- **Phones.** Laptop browsers are the target for this version. The layout works at phone width, and real-phone audio on iOS and Android is checked and fixed in a follow-up.
- **Typed follow-ups.** Voice turns go into session memory, which the normal and document chat paths both read, so a typed follow-up remembers them on either path.

## Goals

1. Tap the button and be talking within a moment, with no setup beyond the microphone permission.
2. Natural conversation: interrupt Atlas at any time and it stops at once.
3. Atlas continues the chat it was opened from and comes back with the conversation saved.
4. The orb visibly responds to the actual voices, not a canned loop.
5. The Gemini API key never reaches the browser.

## Non-goals for this version

- Voice does not use tools: no web search, repo search, Workspace documents or file generation by voice. Atlas says plainly that it can't do those by voice and suggests typing. (Builder's note: keep the design open to adding tools later.)
- No camera or screen sharing.
- No saved audio. Only the text transcript is stored.
- No voice inside the Knowledge Workspace (`/w/...`). Chat section only.
- No voice or language picker in settings.

## Anti-goals: this fails even if it technically works

- It looks like a generic gradient blob or a stock template.
- The API key, or any long-lived credential, is exposed to the browser.
- Atlas hears itself through the speakers and talks to itself.
- A dropped connection or closed tab loses what was already said.
- The orb stutters, or the screen hard-cuts in and out.
- Hard-coded colours that break in the light theme.

## Product flow

1. **Starting.** In the composer, the blue waveform button sits in the send button's place while the box is empty. As soon as text is typed or a file attached, it becomes the normal send arrow, as in the owner's screenshot. The existing microphone stays as it is, for dictating text. While a reply is streaming, the stop button shows, as it does today.
2. **Opening.** The screen expands out of the button into a full-viewport overlay covering the sidebar too, and the dots gather into the orb. The browser asks for the microphone the first time.
3. **Talking.** A status word, the orb, one live caption and the controls. Atlas waits for the person to speak first. The status moves through Connecting, Listening, Thinking, Speaking.
4. **Interrupting.** When the person talks over Atlas, its audio stops immediately and it listens.
5. **Ending.** End button or Esc. The overlay collapses back into the composer, and the chat shows the new messages.

A session that said nothing leaves nothing behind: no messages, and no empty chat.

A session started from a brand-new chat creates the conversation when the first turn is saved, titled from that first turn the way typed chats are.

## Visual design

Tokens only, read from `app/globals.css` ("Obsidian Design System"). No hex values in components.

**Field.** `--canvas`, the same near-black the app already uses in dark mode. The overlay follows the active theme. In light mode the same orb sits on the light canvas with deeper tones.

**Orb colour.** A ramp through existing tokens: `--info` (blue) into `--accent-bright` (indigo) into `--accent-2` (violet), running top to bottom as in the reference. That gives the reference's blue-to-violet look using our own brand colours. Colours are read from the CSS variables at runtime and passed to the shader, so a theme switch just works.

**Orb form.**
- Fine dots on a sphere, deformed by layered noise into soft folds and ridges like the reference, not a smooth ball or a sine-wave wobble.
- Dots crowd where the surface folds, giving those bright ridges; dots on the far side fade with depth, giving real volume.
- Dots stay crisp and small. No glow bloom, no gradient blob behind it.

**How the orb behaves in each state.** Each must be recognisable with the status word hidden.

| State | Behaviour |
|---|---|
| Connecting | Scattered dots drift inward and settle into the sphere |
| Listening | Slow breathing; the surface swells with the person's microphone level |
| Thinking | Folds roll steadily around the sphere; no audio response |
| Speaking | Stronger, quicker folds driven by Atlas's actual output audio |
| Muted | Surface calms and dims; ignores the microphone |
| Reconnecting | Dots loosen slightly, then re-gather |
| Ended | Dots collapse toward the composer as the overlay closes |

Changes between states are eased, never snapped. Audio levels are smoothed so the orb flows instead of jittering.

**Type and controls.** The app's own font and text tokens.
- Status word: small, quiet, `--text-secondary`, above the orb.
- Caption: one or two lines under the orb, fading as a new line starts. A control can hide captions.
- Three controls at the foot: Mute, Captions, End. Round, using the existing surface and border tokens; End uses `--danger`. Lucide icons, consistent with the rest of the app.
- Nothing else on screen. No title bar, no branding block.

**Motion.** Framer Motion (already a dependency) for the open and close: a circular reveal from the button's real position on screen, reversed on close. The orb's colours and form must feel continuous with the button that opened it.

**Accessibility.**
- `role="dialog"`, focus held inside the overlay, focus returned to the button afterwards.
- Status changes announced through an `aria-live` region.
- All controls reachable by keyboard: Esc ends, M mutes.
- `prefers-reduced-motion`: a calm, near-still orb with only a gentle change in brightness for level, and a fade instead of the reveal.
- Works at phone width.

## Technical design

**Connection.** The browser talks directly to the Gemini Live API over WebSocket, using a short-lived token minted by our backend. Google's documentation recommends this for streaming latency and recommends ephemeral tokens over API keys. A proxy through FastAPI would add latency and hold a connection per user on the server.

**Backend: `POST /api/v1/chat/voice/session`**
- Same auth as chat (`require_developer`), and rate limited with the existing `slowapi` limiter.
- Input: optional `conversation_id`. A conversation that isn't the caller's gets a 404, same as `/chat/stream`.
- Builds the system instruction on the server: a voice-specific persona plus `ASSISTANT_IDENTITY` from `app/shared/identity.py`, plus the chat's recent messages as context.
- Mints an ephemeral token with `uses: 1`, locked through `live_connect_constraints` to the model, voice, audio modality, system instruction, both transcriptions, context compression and session resumption. The browser cannot change what Atlas has been told.
- Returns the token, the model name and expiry.
- If `GEMINI_API_KEY` is unset it returns a typed "voice not configured" error. Backend startup stays degrade-don't-die: a missing key must not stop the app.

The voice persona is short and written for the ear: spoken sentences, no markdown, no lists read aloud, replies sized to speech. Follow the repo's prompt lessons: state the wanted behaviour positively, and don't quote unwanted output. Because the persona is a prompt, it needs real listening tests, with what was found recorded in a comment, per the repo's convention.

**Backend: `POST /api/v1/chat/voice/turns`**
- Same auth and ownership checks. Saves finished turns through `ConversationRepository.add_message` with `agent_used="voice_agent"`, and pushes them to session memory with `push_session_message`, so a typed follow-up remembers them.
- Creates the conversation and its title on the first saved turn if there isn't one yet.
- Idempotent: each turn carries a client-generated id, so a retry can't duplicate a message. This needs a home on the message record or a small new table, which may mean a migration.

**Frontend: audio.**
- Microphone via `getUserMedia` with echo cancellation, noise suppression and auto gain on. An `AudioWorklet` converts to the 16 kHz, 16-bit PCM the API requires.
- Playback through Web Audio from the API's 24 kHz PCM, scheduled gaplessly. On the API's interrupted signal, drop everything queued immediately.
- Separate analysers on microphone and output feed the orb.

**Frontend: session.**
- Turn on input and output transcription; those become captions and saved turns. An interrupted Atlas turn saves only what was actually spoken, so the record matches what was heard.
- Save each turn as it completes rather than only at the end, so a crash or closed tab loses at most the turn in progress. Flush on end, using `keepalive` for tab close.
- Long sessions: Google caps audio sessions at about 15 minutes without context compression, and connections at about 10 minutes. Turn on compression and resumption, and on the server's going-away notice reconnect with the resumption handle, showing Reconnecting only if it takes noticeable time. Each reconnect mints a fresh one-use token with the handle locked inside it: measured against the live service, a used token is refused despite the docs, and a handle sent only by the client silently starts a new session.
- Stop the microphone and close audio contexts on every exit path, so the browser's recording indicator never lingers.
- When the overlay closes, invalidate `chatKeys.messages` and the conversations query so the thread shows the new turns.

**Frontend: orb.** WebGL2 point rendering, with deformation computed in the vertex shader so tens of thousands of dots stay smooth. No new 3D dependency. Scale dot count down if frames drop, and fall back to a smaller Canvas 2D orb if WebGL2 is unavailable. Pause rendering when the tab is hidden.

**Code placement.** A self-contained area, for example `components/chat/voice-agent/` and `lib/voice/`, with a Zustand store for session state (client state, per the repo's convention) and TanStack Query for saved messages. Keep `types/api.ts` in step with the new endpoints in the same commit, as `CLAUDE.md` requires.

**Configuration.** `GEMINI_API_KEY` (secret), `GEMINI_LIVE_MODEL` (default `gemini-3.8-live`, which Google's guide recommends for low-latency voice agents; confirm against the current model list when building), and `GEMINI_LIVE_VOICE`. Add to `config.py`, `.env.example` and the deployment notes. No key is ever sent to the frontend.

**Language.** The native-audio models choose the language automatically and can't be told one. Expect Tamil, English and mixed speech to be tried in testing. Give input transcription a custom vocabulary of product and company names (Atlas, UnityWorks and so on).

**Errors, shown in plain words on the voice screen with a way back.**

| Case | What the person sees |
|---|---|
| Microphone blocked | How to allow it, and a retry |
| Voice not configured | Button hidden, not a broken experience |
| Can't connect | "Couldn't connect" with retry; chat untouched |
| Connection lost mid-session | Reconnecting, then a clear end with the transcript saved |
| Turn failed to save | Retried; if it still fails, the person is told rather than losing it silently |

## Data and privacy

Voice audio and recent chat text go to Google while a session runs. Chat text currently goes to NVIDIA, so this adds a second outside provider for company conversations. We store transcripts only, never audio. Check the Gemini API plan's data-use terms before production: Google's terms differ between free and paid tiers.

## Done means

- Works from a new chat and an existing one, in Chrome, Edge and Safari, in both themes.
- Ask something in a typed chat, then ask about it by voice: Atlas knows. Then type a follow-up about the voice conversation: Atlas knows.
- Interrupting stops Atlas's audio immediately. Playing through laptop speakers, Atlas does not hear itself.
- A session past 15 minutes keeps going with context intact.
- Closing the tab mid-session keeps every finished turn, once only.
- The orb holds a steady 60 fps on an ordinary laptop, and every state is recognisable.
- Backend tests cover ownership, the missing-key path, idempotent saves and session memory. No test reaches Gemini. `pnpm type-check` and `pnpm build` pass; note that the frontend has no test runner, so verification there is manual, and it must not run `pnpm build` over a running dev server.
- The owner has seen it running and judged the look by the $5,000 bar. Expect rounds of visual polish before this is called done.

## Left to the builder

File layout, shader details, noise functions, exact timing and easing, dot counts, whether to use Google's JS SDK or a raw WebSocket in the browser, the Python SDK or plain HTTP for minting tokens, the rate limit's value, and how to store the idempotency id.
