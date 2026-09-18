"""The production risk scan: asking how something works is not asking the assistant to do it.

A substring match on "delete" / "format " held "How do I format a date in Python?" and
"explain step by step how to delete a git branch" for review — the model was never
called and the user got a canned hold message, the most bot-like reply the app gives.
"""

from __future__ import annotations

import pytest

from app.cognitive_integration.adapters_prod import IntentDetectorAdapter


class _Detector:
    def detect(self, message, history):
        return None


def _scan(message: str):
    return IntentDetectorAdapter(detector=_Detector()).detect(message, [])


@pytest.mark.parametrize("message", [
    "How do I format a date in Python?",
    "explain step by step how to delete a git branch",
    "What's the difference between DELETE and TRUNCATE in SQL?",
    "why does git refuse to force push to main?",
    "Walk me through how rm -rf works, I want to understand it",
    "the formatter keeps reformatting my file",
    "I deleted a file by mistake, can I get it back?",
    "Can you teach me how to wipe an SSD securely?",
])
def test_questions_about_risky_things_are_answered_not_held(message):
    result = _scan(message)
    assert not result.safety_relevant
    assert result.stakes < 0.5


@pytest.mark.parametrize("message", [
    "delete all my repositories",
    "drop table users",
    "rm -rf the whole project folder now",
    "Please wipe the production database",
    "force push this branch to main",
    "can you delete every conversation I have?",
    "deploy to prod right now",
])
def test_requests_to_act_irreversibly_are_still_escalated(message):
    result = _scan(message)
    assert result.safety_relevant
    assert result.irreversible
    assert result.stakes >= 0.9
