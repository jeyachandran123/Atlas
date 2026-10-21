"""Encrypt stored plugin credentials. Fernet (AES-128-CBC + HMAC), authenticated."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class CredentialError(Exception):
    """A stored credential can't be decrypted (wrong key). The user must reconnect."""


def _fernet() -> Fernet:
    cfg = get_settings()
    explicit = cfg.plugin_encryption_key.get_secret_value().strip()
    if explicit:
        return Fernet(explicit.encode())
    # No dedicated key: derive one from SECRET_KEY, namespaced so it is not the key
    # that signs login tokens.
    seed = ("plugin-credentials:" + cfg.secret_key.get_secret_value()).encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(seed).digest()))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError) as e:
        raise CredentialError("Stored credential can't be read; reconnect the plugin") from e
