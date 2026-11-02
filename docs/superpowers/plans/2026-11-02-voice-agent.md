# Voice Agent Implementation Plan

> **For agentic workers:** the owner asked for development to start without further questions, so this plan runs natively with superpowers:executing-plans. Commit nothing until the owner asks.

**Goal:** ChatGPT-style voice conversation inside any chat, with a signature full-screen dotted orb.

**Architecture:** The backend mints a short-lived Gemini Live token locked to a server-built system instruction, and saves transcripts. The browser streams audio directly to Gemini, renders the orb in WebGL2 and posts finished turns back.

**Tech Stack:** FastAPI, httpx, Next.js 15, React 19, Zustand, TanStack Query, Framer Motion, raw WebSocket, AudioWorklet, WebGL2.

**Spec:** `docs/superpowers/specs/2026-11-02-voice-agent-design.md`

## Global Constraints

- Default model `gemini-3.8-live`. Audio in 16 kHz PCM, out 24 kHz PCM.
- Session limits: 30 minutes total, 5 minutes of silence.
- Theme tokens only in components, no hex values.
- No new frontend dependency, no new migration (a turn's client id is the message's primary key).
- Measured on 2026-11-02: the REST token body takes `bidiGenerateContentSetup` with `model`, `generationConfig`, `systemInstruction` at its top level. The documented `liveConnectConstraints` is rejected. The constrained WebSocket is `...GenerativeService.BidiGenerateContentConstrained?access_token=`, the client sends `{setup:{model}}`, and frames arrive as binary.

## Review Focus

1. Mute held while Atlas speaks: Atlas must finish and the idle timer must not end the session as silent.
2. Tab closed mid-session: finished turns still saved, once only.
3. Microphone unplugged or denied after opening: plain error, tracks released.
4. An interrupted Atlas turn: only what was spoken is saved.
5. Theme changed while the overlay is open: orb colours follow.

## Task 1: Backend config, persona and token minting

**Files:** `app/config.py`, `.env.example`, create `app/voice/__init__.py`, `app/voice/persona.py`, `app/voice/service.py`; test `tests/unit/test_voice_service.py`.

**Produces:** `build_system_instruction(history, documents) -> str`, `voice_enabled() -> bool`, `async mint_live_token(system_instruction) -> LiveToken`, `VoiceNotConfigured`, `VoiceProviderError`.

Tests: instruction contains identity, history and documents, and caps history size; the token body has the verified shape; missing key raises; provider failure raises without leaking the key.

## Task 2: Backend API

**Files:** create `app/api/v1/voice/__init__.py`, `app/api/v1/voice/router.py`; modify `app/main.py`, `app/db/repositories.py` (`add_message(message_id=...)`); test `tests/integration/voice/`.

**Produces:** `GET /chat/voice/config`, `POST /chat/voice/session`, `POST /chat/voice/turns`.

Tests: another user's conversation is a 404 on both POSTs; a missing key is 503 `voice_not_configured`; the first turn creates and titles the conversation; re-posting a turn saves it once; turns reach session memory; a Redis failure doesn't lose the save.

## Task 3: Audio and Live client

**Files:** create `frontend/public/voice/pcm-capture.worklet.js`, `frontend/lib/voice/audio.ts`, `frontend/lib/voice/live-client.ts`, `frontend/lib/voice/session.ts`, `frontend/lib/stores/voice-store.ts`, `frontend/lib/api/voice.ts`; modify `frontend/types/api.ts`.

**Produces:** `startVoiceSession(conversationId)`, `endVoiceSession()`, `toggleMute()`, `useVoiceStore`, `voiceLevels()`.

Verified in Playwright with a fake microphone file against real Gemini.

## Task 4: Orb

**Files:** create `frontend/components/chat/voice-agent/orb.tsx`, `orb-shaders.ts`.

Grid-mapped dots on a sphere, ridged noise, state targets eased, colours read from CSS variables, theme observer, frame-rate tiering, Canvas 2D fallback, reduced motion. Checked by screenshot against the reference image in both themes.

## Task 5: Overlay and entry

**Files:** create `frontend/components/chat/voice-agent/voice-overlay.tsx`, `voice-button.tsx`; modify `frontend/components/chat/chat-input.tsx`.

Circular reveal from the button, status, caption, Mute, Captions and End, keyboard, focus, error states, query invalidation on close.

## Task 6: End-to-end verification

Playwright against the running stack: new chat, existing chat, interruption, tab close, both themes. `pnpm type-check`, backend tests, ruff on touched files. `pnpm build` is not run while `pnpm dev` is up.
