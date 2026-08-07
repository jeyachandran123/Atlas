"""JSON recovery — the layer that must never crash and must never invent.

Each case below is something a real VLM does. The assertions are as much about
what is *not* recovered as what is: a repairer that eventually parses anything
is one that has started making things up.
"""

from __future__ import annotations

import json

import pytest

from app.document_platform.vlm.json_repair import MAX_REPAIR_INPUT_CHARS, parse_model_json


class TestCleanOutput:
    def test_plain_json_parses_directly(self) -> None:
        outcome = parse_model_json('{"invoice_number": "INV-1"}')
        assert outcome.ok and outcome.strategy == "direct"
        assert outcome.repaired is False
        assert outcome.value == {"invoice_number": "INV-1"}

    def test_whitespace_is_not_a_repair(self) -> None:
        assert parse_model_json('\n\n  {"a": 1}\n').strategy == "direct"


class TestRecovery:
    def test_code_fences_are_stripped(self) -> None:
        outcome = parse_model_json('```json\n{"a": 1}\n```')
        assert outcome.value == {"a": 1}
        assert "code_fence_stripped" in outcome.repairs

    def test_json_embedded_in_prose_is_found_and_the_prose_is_kept(self) -> None:
        text = 'Here is the invoice: {"a": 1}. Let me know if you need more.'
        outcome = parse_model_json(text)
        assert outcome.value == {"a": 1}
        assert "Here is the invoice" in outcome.unparsed, "prose is evidence, not noise"

    def test_trailing_commas_are_removed(self) -> None:
        outcome = parse_model_json('{"a": 1, "b": [1, 2,],}')
        assert outcome.value == {"a": 1, "b": [1, 2]}
        assert "trailing_commas_removed" in outcome.repairs

    def test_comments_are_removed(self) -> None:
        outcome = parse_model_json('{"a": 1, // the total\n "b": /* also */ 2}')
        assert outcome.value == {"a": 1, "b": 2}

    def test_a_url_inside_a_string_is_not_mistaken_for_a_comment(self) -> None:
        """The naive comment strip corrupts ``https://`` and calls it a fix."""
        outcome = parse_model_json('{"site": "https://acme.example/x", "a": 1,}')
        assert outcome.value == {"site": "https://acme.example/x", "a": 1}

    def test_python_literals_are_converted(self) -> None:
        outcome = parse_model_json('{"paid": True, "note": None, "void": False}')
        assert outcome.value == {"paid": True, "note": None, "void": False}

    def test_a_python_repr_with_single_quotes_is_converted(self) -> None:
        outcome = parse_model_json("{'invoice_number': 'INV-1'}")
        assert outcome.value == {"invoice_number": "INV-1"}

    def test_single_quotes_are_left_alone_when_double_quotes_exist(self) -> None:
        """An apostrophe in a supplier's name must survive. Corrupting data to
        make it parse is worse than failing to parse."""
        outcome = parse_model_json('{"supplier": "O\'Brien Ltd"}')
        assert outcome.value == {"supplier": "O'Brien Ltd"}

    def test_smart_quotes_are_normalised(self) -> None:
        outcome = parse_model_json('{“a”: “b”}')
        assert outcome.value == {"a": "b"}

    def test_a_truncated_response_keeps_every_complete_field(self) -> None:
        """A model that hit its token ceiling still found the fields it emitted;
        discarding them all would be throwing away a paid-for answer."""
        outcome = parse_model_json(
            '{"invoice_number": "INV-1", "line_items": [{"amount": 10}, {"amount": 2'
        )
        assert outcome.ok
        assert outcome.value["invoice_number"] == "INV-1"
        assert outcome.value["line_items"][0] == {"amount": 10}
        assert outcome.repaired

    def test_a_single_element_array_is_reported_as_an_array(self) -> None:
        """Unwrapping is the adapter's decision, not the parser's."""
        outcome = parse_model_json('[{"a": 1}]')
        assert outcome.value == [{"a": 1}]
        assert outcome.is_object is False


class TestRefusalToInvent:
    def test_text_with_no_json_fails_explicitly(self) -> None:
        outcome = parse_model_json("I cannot read this document.")
        assert not outcome.ok
        assert outcome.value is None
        assert outcome.error
        assert "I cannot read this document." in outcome.unparsed

    def test_empty_output_fails_explicitly(self) -> None:
        outcome = parse_model_json("")
        assert not outcome.ok and "empty" in outcome.error

    def test_none_is_tolerated(self) -> None:
        assert parse_model_json(None).ok is False

    def test_a_runaway_generation_is_refused_rather_than_scanned(self) -> None:
        outcome = parse_model_json("x" * (MAX_REPAIR_INPUT_CHARS + 1))
        assert not outcome.ok and "repair limit" in outcome.error

    @pytest.mark.parametrize(
        "text",
        [
            "{",
            "}{",
            '{"a": }',
            "[[[[",
            '{"a": "unterminated',
            "null and more text",
        ],
    )
    def test_malformed_input_never_raises(self, text: str) -> None:
        outcome = parse_model_json(text)
        assert isinstance(outcome.telemetry(), dict)

    def test_as_dict_is_safe_when_the_model_returned_a_list(self) -> None:
        assert parse_model_json("[1, 2]").as_dict() == {}


class TestDeterminism:
    def test_identical_text_yields_identical_parses(self) -> None:
        text = 'Result: ```json\n{"a": 1, "b": [2,],}\n```'
        first, second = parse_model_json(text), parse_model_json(text)
        assert first.value == second.value
        assert first.strategy == second.strategy
        assert first.repairs == second.repairs

    def test_a_recovered_value_round_trips_through_json(self) -> None:
        outcome = parse_model_json('```json\n{"a": [1, 2, {"b": null}]}\n```')
        assert json.loads(json.dumps(outcome.value)) == outcome.value
