"""Voice sessions: what Atlas is told, and the locked token that carries it."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import get_settings
from app.shared.identity import ASSISTANT_IDENTITY
from app.voice import service
from app.voice.persona import MAX_DOCUMENT_CHARS, MAX_HISTORY_CHARS, build_system_instruction


class TestSystemInstruction:
    def test_it_says_who_atlas_is(self) -> None:
        assert ASSISTANT_IDENTITY in build_system_instruction([], "")

    def test_the_chat_so_far_is_included_in_order(self) -> None:
        text = build_system_instruction(
            [("user", "What is the total?"), ("assistant", "It is 20.80.")], ""
        )
        assert text.index("What is the total?") < text.index("It is 20.80.")

    def test_the_newest_messages_survive_the_history_budget(self) -> None:
        text = build_system_instruction(
            [("user", "OLDEST " * 4000), ("user", "NEWEST message")], ""
        )
        assert "NEWEST message" in text
        assert "OLDEST" not in text
        assert len(text) < MAX_HISTORY_CHARS + MAX_DOCUMENT_CHARS + 4000

    def test_document_text_is_included_within_its_budget(self) -> None:
        text = build_system_instruction([], "X" * (MAX_DOCUMENT_CHARS + 500))
        assert "X" * MAX_DOCUMENT_CHARS in text
        assert "X" * (MAX_DOCUMENT_CHARS + 1) not in text

    def test_an_empty_chat_has_no_empty_context_sections(self) -> None:
        text = build_system_instruction([], "")
        assert "The chat so far" not in text
        assert "Files attached" not in text


def _settings(monkeypatch, key: str = "secret-gemini-key") -> None:
    monkeypatch.setattr(get_settings(), "gemini_api_key", SecretStr(key))
    monkeypatch.setattr(get_settings(), "gemini_live_model", "gemini-test-live")
    monkeypatch.setattr(get_settings(), "gemini_live_voice", "Kore")


def _transport(monkeypatch, handler) -> None:
    real = httpx.AsyncClient

    def client(**kwargs):
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(service.httpx, "AsyncClient", client)


class TestMintToken:
    async def test_the_token_locks_what_the_browser_cannot_change(self, monkeypatch) -> None:
        _settings(monkeypatch)
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["key"] = request.headers["x-goog-api-key"]
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"name": "auth_tokens/abc"})

        _transport(monkeypatch, handler)
        token = await service.mint_live_token("You are Atlas.")

        assert token.token == "auth_tokens/abc"
        assert token.model == "models/gemini-test-live"
        assert "BidiGenerateContentConstrained" in token.websocket_url
        assert seen["key"] == "secret-gemini-key"
        body = seen["body"]
        assert body["uses"] == 1
        setup = body["bidiGenerateContentSetup"]
        assert setup["model"] == "models/gemini-test-live"
        assert setup["systemInstruction"]["parts"][0]["text"] == "You are Atlas."
        assert setup["generationConfig"]["responseModalities"] == ["AUDIO"]
        assert "inputAudioTranscription" in setup
        assert "outputAudioTranscription" in setup
        assert "sessionResumption" in setup
        assert "contextWindowCompression" in setup
        detection = setup["realtimeInputConfig"]["automaticActivityDetection"]
        assert detection["startOfSpeechSensitivity"] == "START_SENSITIVITY_LOW"

    async def test_a_resume_handle_is_locked_into_the_new_token(self, monkeypatch) -> None:
        """Sent only by the client, a handle silently starts a new session."""
        _settings(monkeypatch)
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"name": "auth_tokens/abc"})

        _transport(monkeypatch, handler)
        await service.mint_live_token("x", "handle-1")
        assert seen["body"]["bidiGenerateContentSetup"]["sessionResumption"] == {"handle": "handle-1"}
        assert seen["body"]["uses"] == 1

    async def test_a_missing_key_is_not_configured(self, monkeypatch) -> None:
        _settings(monkeypatch, key="")
        assert service.voice_enabled() is False
        with pytest.raises(service.VoiceNotConfigured):
            await service.mint_live_token("x")

    async def test_a_provider_failure_never_shows_the_key(self, monkeypatch) -> None:
        _settings(monkeypatch)
        _transport(
            monkeypatch,
            lambda request: httpx.Response(429, text="quota secret-gemini-key"),
        )
        with pytest.raises(service.VoiceProviderError) as caught:
            await service.mint_live_token("x")
        assert "secret-gemini-key" not in str(caught.value)
        assert caught.value.upstream_status == 429

    async def test_an_unreachable_provider_is_a_provider_error(self, monkeypatch) -> None:
        _settings(monkeypatch)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("nope")

        _transport(monkeypatch, handler)
        with pytest.raises(service.VoiceProviderError):
            await service.mint_live_token("x")
