"""Chat vision on the self-hosted UnityWorks endpoint.

The request shape is asserted through the pure body builder rather than over
HTTP: ``VisionModel`` constructs its own client inline, and a test that reached
for the network to check that two strings were joined would be testing httpx.

What matters here is what the endpoint's narrow contract forces — one prompt
string, at most one image — and that several attachments are combined rather
than quietly reduced to the first one.
"""

from __future__ import annotations

import base64
import io

import pytest

from app.vision.vision_model import _STREAM_SLICE, VisionModel


def real_png(width: int, height: int, colour: tuple[int, int, int] = (7, 9, 11)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def decode_data_uri(uri: str) -> bytes:
    return base64.b64decode(uri.split(",", 1)[1])


class TestRequestBody:
    def test_system_and_user_prompts_are_joined_into_one_field(self) -> None:
        body = VisionModel._unityworks_body("What is this?", "You are terse.", [], 256)
        assert body["prompt"] == "You are terse.\n\nWhat is this?"

    def test_an_absent_system_prompt_adds_no_blank_lines(self) -> None:
        body = VisionModel._unityworks_body("What is this?", "", [], 256)
        assert body["prompt"] == "What is this?"

    def test_the_token_budget_is_forwarded(self) -> None:
        body = VisionModel._unityworks_body("hi", "", [], 512)
        assert body["max_new_tokens"] == 512

    def test_a_text_only_turn_sends_no_image_key(self) -> None:
        body = VisionModel._unityworks_body("no picture here", "", [], 256)
        assert "image_url" not in body

    def test_a_single_attachment_is_sent_untouched(self) -> None:
        original = real_png(20, 30)
        body = VisionModel._unityworks_body("describe", "", [original], 256)
        assert body["image_url"].startswith("data:image/png;base64,")
        assert decode_data_uri(body["image_url"]) == original

    def test_the_media_type_is_read_from_the_bytes(self) -> None:
        """A JPEG announced as PNG is a payload a server can refuse outright."""
        jpeg = b"\xff\xd8\xff" + b"0" * 32
        body = VisionModel._unityworks_body("describe", "", [jpeg], 256)
        assert body["image_url"].startswith("data:image/jpeg;base64,")


class TestSeveralAttachments:
    def test_three_attachments_become_one_image(self) -> None:
        """The endpoint accepts one image; chat allows several attachments."""
        body = VisionModel._unityworks_body(
            "compare these", "", [real_png(30, 40), real_png(30, 50), real_png(30, 60)], 256
        )
        assert isinstance(body["image_url"], str)

    def test_no_attachment_is_dropped(self) -> None:
        from PIL import Image

        body = VisionModel._unityworks_body(
            "compare these", "", [real_png(30, 40), real_png(30, 50)], 256
        )
        combined = Image.open(io.BytesIO(decode_data_uri(body["image_url"])))
        assert combined.width == 30
        assert combined.height == 90


class TestStreamingPacing:
    async def test_a_one_shot_answer_is_emitted_in_slices(self, monkeypatch) -> None:
        """One enormous chunk makes a finished answer look like a frozen one."""
        answer = "x" * (_STREAM_SLICE * 3)

        async def _fake_chat(self, prompt, system_prompt, image_data, temperature):
            return answer

        monkeypatch.setattr(VisionModel, "_unityworks_vision_chat", _fake_chat)

        chunks = [
            chunk async for chunk in VisionModel()._unityworks_vision_stream("q", "", [], 0.3)
        ]
        assert len(chunks) == 3
        assert "".join(chunks) == answer

    async def test_an_empty_answer_yields_nothing_rather_than_a_blank_chunk(
        self, monkeypatch
    ) -> None:
        async def _fake_chat(self, prompt, system_prompt, image_data, temperature):
            return ""

        monkeypatch.setattr(VisionModel, "_unityworks_vision_chat", _fake_chat)

        chunks = [
            chunk async for chunk in VisionModel()._unityworks_vision_stream("q", "", [], 0.3)
        ]
        assert chunks == []


class TestConfiguration:
    async def test_an_unset_url_fails_loudly_rather_than_calling_localhost(
        self, monkeypatch
    ) -> None:
        from app.vision import vision_model as module

        monkeypatch.setattr(module.settings, "unityworks_base_url", "  ", raising=False)
        with pytest.raises(RuntimeError, match="UNITYWORKS_BASE_URL"):
            await VisionModel()._unityworks_vision_chat("q", "", [], 0.3)

    def test_unityworks_is_an_accepted_vision_provider(self) -> None:
        """The Literal must admit the new name, or the app refuses to start."""
        from app.config import Settings

        settings = Settings(_env_file=None, vision_provider="unityworks")
        assert settings.vision_provider_resolved == "unityworks"

    def test_an_unknown_vision_provider_is_still_rejected(self) -> None:
        from pydantic import ValidationError

        from app.config import Settings

        with pytest.raises(ValidationError):
            Settings(_env_file=None, vision_provider="not-a-provider")
