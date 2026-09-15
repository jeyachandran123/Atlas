"""TLS to Postgres comes from DB_SSL_MODE — the same rule for the app and its migrations."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize("mode", ["prefer", "require", "verify-ca", "verify-full"])
def test_a_tls_mode_is_handed_to_the_driver(mode):
    assert settings(db_ssl_mode=mode).database_connect_args == {"ssl": mode}


def test_disable_sends_no_tls_option_at_all():
    # The local Docker Postgres has no TLS and refuses an SSL upgrade outright.
    assert settings(db_ssl_mode="disable").database_connect_args == {}


def test_unset_prefers_tls_so_neither_neon_nor_local_breaks():
    assert settings().db_ssl_mode == "prefer"


def test_a_misspelt_mode_is_refused_at_startup():
    with pytest.raises(ValidationError):
        settings(db_ssl_mode="required")
