"""Unit tests for authentication utilities."""

from __future__ import annotations

import time

import pytest

from app.auth import (
    constant_time_compare,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
)
from app.shared.exceptions import UnauthorizedError


# ── Password hashing ──────────────────────────────────────────────────────────

def test_hash_password_returns_bcrypt_hash():
    h = hash_password("mysecret")
    assert h.startswith("$2b$")


def test_verify_password_correct():
    h = hash_password("mysecret")
    assert verify_password("mysecret", h) is True


def test_verify_password_wrong():
    h = hash_password("mysecret")
    assert verify_password("wrongpassword", h) is False


def test_hash_password_different_hashes():
    """Bcrypt salts each hash — same password produces different hashes."""
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2
    assert verify_password("same", h1)
    assert verify_password("same", h2)


# ── API key handling ──────────────────────────────────────────────────────────

def test_generate_api_key_returns_tuple():
    raw, hashed = generate_api_key()
    assert raw.startswith("aic-")
    assert len(hashed) == 64


def test_api_key_hash_is_sha256():
    _, hashed = generate_api_key()
    assert all(c in "0123456789abcdef" for c in hashed)
    assert len(hashed) == 64


def test_api_key_hash_deterministic():
    raw, h1 = generate_api_key()
    h2 = hash_api_key(raw)
    assert h1 == h2


def test_constant_time_compare_equal():
    assert constant_time_compare("abc", "abc") is True


def test_constant_time_compare_unequal():
    assert constant_time_compare("abc", "xyz") is False


# ── JWT tokens ────────────────────────────────────────────────────────────────

def test_create_and_decode_access_token():
    token = create_access_token("user-123", "org-456", "developer")
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["org"] == "org-456"
    assert payload["role"] == "developer"
    assert payload["type"] == "access"


def test_decode_token_raises_on_invalid():
    with pytest.raises(UnauthorizedError):
        decode_token("not.a.valid.token")


def test_decode_token_raises_on_tampered():
    token = create_access_token("user-1", "org-1", "admin")
    # Tamper with the payload segment
    parts = token.split(".")
    tampered = parts[0] + ".TAMPERED" + parts[2]
    with pytest.raises(UnauthorizedError):
        decode_token(tampered)


def test_access_token_has_expiry():
    token = create_access_token("u", "o", "viewer")
    payload = decode_token(token)
    assert "exp" in payload
    assert payload["exp"] > time.time()


def test_refresh_token_has_refresh_type():
    token = create_refresh_token("user-123")
    payload = decode_token(token)
    assert payload["type"] == "refresh"
    assert payload["sub"] == "user-123"
