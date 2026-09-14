"""Errors a provider sends inside a stream are classified by the code they carry."""

from __future__ import annotations

import httpx
import openai

from app.llm.gateway import ChatGateway

REQUEST = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")


def in_stream(body: object) -> openai.APIError:
    return openai.APIError("Service temporarily overloaded", REQUEST, body=body)


def test_an_overloaded_stream_is_worth_another_try():
    error = ChatGateway._classify(in_stream(
        {"message": "Service temporarily overloaded", "type": "service_unavailable", "code": 503}
    ))
    assert (error.retryable, error.status) == (True, 503)
    assert str(error) == "The chat model is temporarily overloaded."


def test_service_unavailable_without_a_code_is_still_a_503():
    error = ChatGateway._classify(in_stream({"type": "service_unavailable"}))
    assert (error.retryable, error.status) == (True, 503)


def test_a_client_error_in_a_stream_is_not_retried():
    error = ChatGateway._classify(in_stream({"message": "bad request", "code": 400}))
    assert (error.retryable, error.status) == (False, 400)


def test_an_unexplained_stream_error_is_not_retried():
    error = ChatGateway._classify(in_stream(None))
    assert not error.retryable
    assert str(error) == "The chat call failed (APIError)."


def test_the_provider_message_never_reaches_the_error():
    # Bodies can echo the request; only the code may survive.
    error = ChatGateway._classify(in_stream({"message": "echo nvapi-SECRET", "code": 503}))
    assert "SECRET" not in str(error)
