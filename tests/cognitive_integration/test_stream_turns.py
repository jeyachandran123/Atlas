"""The conversation reaches the model as real turns, so it replies like it is mid-conversation."""

from __future__ import annotations

from app.cognitive_integration.pipeline import (
    _HISTORY_CHARS,
    _HISTORY_MESSAGES,
    _STREAM_SYSTEM,
    _STYLE_REMINDER,
    _as_turns,
    _stream_history,
)


def test_history_becomes_alternating_user_and_assistant_turns():
    history = [
        {"role": "user", "content": "Hey Hi", "agent_mode": "auto"},
        {"role": "assistant", "content": "Hi! What's on your mind?"},
        {"role": "user", "content": "i just feel something da"},
        {"role": "assistant", "content": "Tell me more."},
    ]
    assert _as_turns(history) == (
        {"role": "user", "content": "Hey Hi"},
        {"role": "assistant", "content": "Hi! What's on your mind?"},
        {"role": "user", "content": "i just feel something da"},
        {"role": "assistant", "content": "Tell me more."},
    )


def test_two_messages_from_one_side_are_joined():
    # A reply that failed leaves two user messages in a row.
    turns = _as_turns([
        {"role": "user", "content": "first try"},
        {"role": "user", "content": "second try"},
        {"role": "assistant", "content": "answer"},
    ])
    assert turns == (
        {"role": "user", "content": "first try\n\nsecond try"},
        {"role": "assistant", "content": "answer"},
    )


def test_the_window_opens_with_the_user_and_skips_other_roles_and_blanks():
    turns = _as_turns([
        {"role": "assistant", "content": "the tail of an earlier reply"},
        {"role": "system", "content": "not a turn"},
        {"role": "user", "content": "   "},
        {"role": "user", "content": "a real question"},
    ])
    assert turns == ({"role": "user", "content": "a real question"},)


def test_long_histories_are_capped():
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 5000} for i in range(40)]
    turns = _as_turns(history)
    assert len(turns) <= _HISTORY_MESSAGES
    assert all(len(t["content"]) <= _HISTORY_CHARS for t in turns)


def test_nothing_to_carry_over_is_no_turns():
    assert _as_turns(()) == ()
    assert _as_turns(None) == ()


def test_the_voice_reminder_comes_last_before_the_new_message():
    turns = _stream_history([
        {"role": "user", "content": "Hey Hi"},
        {"role": "assistant", "content": "Hey! 👋 How's your day going?"},
    ])
    assert turns[-1] == _STYLE_REMINDER
    assert [t["role"] for t in turns] == ["user", "assistant", "system"]


def test_a_first_message_needs_no_reminder():
    assert _stream_history(()) == ()


def test_the_persona_speaks_like_a_person_mid_conversation():
    assert "Don't greet" in _STREAM_SYSTEM
    assert "Answer what was actually asked" in _STREAM_SYSTEM
