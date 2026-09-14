"""Brevo: what is sent, and what happens when it is refused."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.mailer.brevo import BREVO_SEND_URL, BrevoMailer, EmailSendError, mask_email
from app.mailer.templates import signup_code


def mailer_with(handler) -> BrevoMailer:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return BrevoMailer("key-123", "no-reply@unityworks.test", "UnityWorks", client=client)


class TestSend:
    def test_the_request_brevo_receives(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["key"] = request.headers.get("api-key")
            seen["body"] = json.loads(request.content)
            return httpx.Response(201, json={"messageId": "<abc@smtp-relay>"})

        message = signup_code("person@example.sg", "Tan Wei", "482913", 10)
        message_id = asyncio.run(mailer_with(handler).send(message))

        assert message_id == "<abc@smtp-relay>"
        assert seen["url"] == BREVO_SEND_URL and seen["key"] == "key-123"
        body = seen["body"]
        assert body["sender"] == {"email": "no-reply@unityworks.test", "name": "UnityWorks"}
        assert body["to"] == [{"email": "person@example.sg", "name": "Tan"}]
        assert "482913" in body["subject"] and "482913" in body["textContent"]

    def test_a_refusal_is_an_error_with_brevos_reason(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"code": "unauthorized", "message": "Key not found"})

        with pytest.raises(EmailSendError) as e:
            asyncio.run(mailer_with(handler).send(signup_code("a@b.co", None, "111111", 10)))
        assert "401" in str(e.value) and "Key not found" in str(e.value)

    def test_an_unreachable_brevo_is_an_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route")

        with pytest.raises(EmailSendError) as e:
            asyncio.run(mailer_with(handler).send(signup_code("a@b.co", None, "111111", 10)))
        assert "Could not reach Brevo" in str(e.value)


class TestTemplate:
    def test_the_code_is_in_every_part(self):
        m = signup_code("a@b.co", "Jane Smith", "904512", 10)
        assert "904512" in m.subject and "904512" in m.text and "9 0 4 5 1 2" in m.html
        assert "10 minutes" in m.text and m.to_name == "Jane"

    def test_a_name_cannot_inject_html(self):
        m = signup_code("a@b.co", "<script>x</script>", "123456", 10)
        assert "<script>" not in m.html


def test_logs_show_only_a_masked_address():
    assert mask_email("chandru@gmail.com") == "c***@gmail.com"
