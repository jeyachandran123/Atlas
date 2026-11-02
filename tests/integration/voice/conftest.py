"""The voice API runs on the skills suite's app, database and people."""

from tests.integration.skills.conftest import (  # noqa: F401
    auth,
    fake_llm,
    sk_client,
    sk_people,
    sk_session,
)
