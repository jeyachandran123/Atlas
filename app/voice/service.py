"""Mint the short-lived token a browser uses to talk to Gemini Live.

The browser connects directly because a relay through this server would add
latency to every syllable. The real API key stays here. The token can start one
session and is locked to the model, voice and system instruction, so the browser
cannot change what Atlas has been told.

The request body follows the live endpoint, not its documentation. Measured
2026-11-02: ``liveConnectConstraints`` from the docs is refused with HTTP 400;
``bidiGenerateContentSetup`` with the setup fields at its top level is accepted,
and the session then honours the locked instruction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from loguru import logger

from app.config import get_settings

_TOKEN_URL = "https://generativelanguage.googleapis.com/v1beta/auth_tokens"  # noqa: S105 — a URL
_LIVE_URL = (
    "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta."
    "GenerativeService.BidiGenerateContentConstrained"
)

#: The session limits the client enforces and the token backs up. A token also
#: resumes dropped connections, so it must outlive the whole session.
MAX_SESSION_SECONDS = 30 * 60
IDLE_TIMEOUT_SECONDS = 5 * 60

_TOKEN_GRACE_SECONDS = 60
_START_WINDOW_SECONDS = 60


class VoiceNotConfigured(Exception):
    """No Gemini key on this deployment."""


class VoiceProviderError(Exception):
    """Gemini could not issue a token. The message is safe to log and show."""

    def __init__(self, message: str, *, upstream_status: int | None = None) -> None:
        super().__init__(message)
        self.upstream_status = upstream_status


@dataclass(frozen=True, slots=True)
class LiveToken:
    token: str
    model: str
    websocket_url: str
    expires_at: str


def voice_enabled() -> bool:
    return bool(get_settings().gemini_api_key.get_secret_value())


def _timestamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


async def mint_live_token(system_instruction: str, resume_handle: str | None = None) -> LiveToken:
    """One locked session token, or a typed error. Never exposes the key.

    Each reconnect gets a fresh token with the resume handle locked inside it.
    Measured 2026-11-02, against the docs: reusing a ``uses: 1`` token is refused
    ("Token has been used too many times"), and a handle sent only by the client
    connects but silently starts a new session, because the token's locked empty
    ``sessionResumption`` wins. Locked in the token, the session kept its context.
    """
    cfg = get_settings()
    key = cfg.gemini_api_key.get_secret_value()
    if not key:
        raise VoiceNotConfigured

    model = f"models/{cfg.gemini_live_model}"
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=MAX_SESSION_SECONDS + _TOKEN_GRACE_SECONDS)
    body = {
        "uses": 1,
        "expireTime": _timestamp(expires),
        "newSessionExpireTime": _timestamp(now + timedelta(seconds=_START_WINDOW_SECONDS)),
        "bidiGenerateContentSetup": {
            "model": model,
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": cfg.gemini_live_voice}}
                },
            },
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
            "sessionResumption": {"handle": resume_handle} if resume_handle else {},
            "contextWindowCompression": {"slidingWindow": {}},
            # The default was too eager. In the owner's first real session on laptop
            # speakers, replies kept cutting off after a word or two, each followed by
            # a stray transcript such as "dezenas": noise or Atlas's own voice taken
            # for an interruption. Harder to trigger, and it waits out a thinking pause.
            "realtimeInputConfig": {
                "automaticActivityDetection": {
                    "startOfSpeechSensitivity": "START_SENSITIVITY_LOW",
                    "endOfSpeechSensitivity": "END_SENSITIVITY_LOW",
                    "silenceDurationMs": 800,
                }
            },
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(_TOKEN_URL, headers={"x-goog-api-key": key}, json=body)
    except httpx.HTTPError as exc:
        logger.warning(f"Gemini token request failed: {type(exc).__name__}")
        raise VoiceProviderError("could not reach the voice service") from exc

    if response.status_code != 200:
        logger.warning(f"Gemini token request refused: HTTP {response.status_code}")
        raise VoiceProviderError(
            "the voice service refused the session", upstream_status=response.status_code
        )

    return LiveToken(
        token=response.json()["name"],
        model=model,
        websocket_url=_LIVE_URL,
        expires_at=_timestamp(expires),
    )
