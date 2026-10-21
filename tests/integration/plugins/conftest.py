"""Plugin integration tests share the skills fixtures: an in-memory database, fake
auth, and an app wired to a fake LLM. Nothing here reaches the network."""

from tests.integration.skills.conftest import *  # noqa: F401,F403
