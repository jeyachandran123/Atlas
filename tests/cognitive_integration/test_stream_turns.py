"""The conversation reaches the model as real turns, so it replies like it is mid-conversation."""

from __future__ import annotations

from app.cognitive_integration.pipeline import (
    _HISTORY_CHARS,
    _HISTORY_MESSAGES,
    _LAST_REPLY_CHARS,
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
    *earlier, last = turns
    assert all(len(t["content"]) <= _HISTORY_CHARS for t in earlier)
    assert len(last["content"]) <= _LAST_REPLY_CHARS


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


def test_a_first_message_still_gets_the_reminder():
    """It used to get none, and it is the reply a new user judges the app by."""
    assert _stream_history(()) == (_STYLE_REMINDER,)
    assert _stream_history(None) == (_STYLE_REMINDER,)


def test_the_persona_speaks_like_a_person_mid_conversation():
    assert "Don't greet" in _STREAM_SYSTEM
    assert "Answer what was actually asked" in _STREAM_SYSTEM


def test_the_persona_asks_for_the_moves_that_make_a_reply_worth_reading():
    """The mechanics taken from a conversation the user singled out as feeling human:
    pin where they are, commit to a claim, name the unnamed distinction, block the
    wrong reading, and land on a statement."""
    for rule in (
        "Open by pinning down where they are",
        "Commit to a claim within the first few lines",
        "Find the distinction they have not put into words",
        "block it before they get there",
        "End with one question you actually want answered",
    ):
        assert rule in _STREAM_SYSTEM


def test_long_answers_are_told_to_use_the_markdown_the_renderer_styles():
    """.assistant-content already styles h1-h4, strong, blockquote, hr and ol. The
    persona used to forbid headings outright, so every explanation came out as a flat
    run of single lines with nothing for the eye to land on."""
    for rule in ("this interface renders real markdown", "**bold**", "> blockquote",
                 "--- rule", "Group sentences into paragraphs"):
        assert rule in _STREAM_SYSTEM
    assert "never report headings" not in _STREAM_SYSTEM


def test_the_persona_states_moves_rather_than_quoting_failures():
    """A quoted bad example becomes a template on this model: banning one stock phrase
    made it the most common opening, and quoting a too-short reply reproduced it 5/5.
    So the persona names no phrase it does not want to see."""
    assert "I hear you" not in _STREAM_SYSTEM
    assert "I'm here." not in _STREAM_SYSTEM
    assert "Great question" not in _STREAM_SYSTEM


def test_the_first_sentence_rule_is_about_substance_not_grammar():
    """Banning "you" from the opening worked (6/6 to 2/6) but would forbid a good
    concrete opening too. The fault was empty restatement, not second person."""
    assert "It must carry something specific" in _STREAM_SYSTEM
    assert "write a different one." in _STREAM_SYSTEM


def test_structure_is_a_threshold_rule_at_the_end_not_advice_in_a_bullet():
    """Describing headings inside a prose bullet produced them 0 times in 4 samples.
    Hard format rules stated last are the only kind this model follows, so the
    requirement is a countable threshold and it lives at the bottom."""
    assert "Long answers — a further hard format rule" in _STREAM_SYSTEM
    assert "at least two ## headings" in _STREAM_SYSTEM
    assert _STREAM_SYSTEM.rstrip().endswith("stays plain prose.")


def test_a_bare_acknowledgement_does_not_earn_an_essay():
    """Dropping this rule in the rewrite let "ok da got it" produce 1054 characters
    with a closing question attached."""
    assert "Length follows the message" in _STREAM_SYSTEM
    assert "gets one or two sentences and no question at all" in _STREAM_SYSTEM


def test_no_domain_leaks_into_the_voice():
    """Naming shops, venues and distances in the honesty rule taught the model it was a
    travel assistant: asked what it could do, it offered to plan trips."""
    for word in ("venues", "shops", "distances", "verify locally"):
        assert word not in _STREAM_SYSTEM


def test_the_latest_reply_is_kept_whole_so_follow_ups_can_refer_to_it():
    """Trimmed to 2000 characters, "go deeper on step 4" lost step 4."""
    long_reply = "\n".join(f"{i}. step {i} " + "detail " * 60 for i in range(1, 9)).strip()
    assert len(long_reply) > _HISTORY_CHARS
    turns = _as_turns([
        {"role": "user", "content": "explain it step by step"},
        {"role": "assistant", "content": long_reply},
    ])
    assert turns[-1]["content"] == long_reply
    assert len(turns[-1]["content"]) <= _LAST_REPLY_CHARS


def test_a_how_or_why_question_earns_a_full_walkthrough_however_short():
    """"A one-line question gets a short answer" gave "how does DNS work?" the same
    instruction as "ok"."""
    assert "A one-line question gets a short answer" not in _STREAM_SYSTEM
    assert "earns a full, patient explanation, however short the question was" in _STREAM_SYSTEM


def test_explanations_go_inch_by_inch():
    for rule in ("Teach it inch by inch", "what happens, why it happens",
                 "Don't skip a step because it feels obvious", "Define a term the first time"):
        assert rule in _STREAM_SYSTEM


def test_the_walkthrough_is_a_hard_rule_in_the_tail_where_this_model_listens():
    tail = _STREAM_SYSTEM[_STREAM_SYSTEM.index("First sentence — a hard format rule"):]
    assert "Explanations — a hard format rule" in tail
    assert "numbered steps" in tail


def test_warmth_is_asked_for_positively_rather_than_pushed_out():
    """"not a therapist", "not reassurance" and "Don't read distress" told the model
    to stay cold and said nothing about what warmth should look like."""
    for removed in ("not a therapist", "not reassurance", "Don't read distress"):
        assert removed not in _STREAM_SYSTEM
    assert "warm" in _STREAM_SYSTEM
    assert "If they sound stuck, frustrated or unsure" in _STREAM_SYSTEM


def test_the_reminder_after_history_carries_warmth_and_walkthroughs_too():
    content = _STYLE_REMINDER["content"]
    assert "step by step" in content
    assert "warm" in content
