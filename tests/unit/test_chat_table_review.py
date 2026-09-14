"""The second look at a table written from memory: drop and reorder, never rewrite."""

from __future__ import annotations

from app.chat_artifacts.review import apply_review, parse_verdict

HEADERS = ["Title", "Year", "Type"]
ROWS = [
    ["Frieren", "2023", "Series"],
    ["Your Name", "2016", "Movie"],
    ["Suzume", "2022", "Movie"],
    ["Oshi no Ko", "2023", "Series"],
]


class TestApply:
    def test_rows_outside_the_request_are_dropped(self):
        kept = apply_review(ROWS, HEADERS, {"drop": [2]})
        assert ["Your Name", "2016", "Movie"] not in kept and len(kept) == 3

    def test_kept_rows_are_never_changed(self):
        kept = apply_review(ROWS, HEADERS, {"drop": [2], "sort": []})
        assert all(r in ROWS for r in kept)

    def test_sorting_is_numeric_for_numbers(self):
        rows = [["a", "9"], ["b", "10"], ["c", "2"]]
        kept = apply_review(rows, ["T", "N"], {"sort": [{"column": "N", "descending": False}]})
        assert [r[1] for r in kept] == ["2", "9", "10"]

    def test_multi_key_sort(self):
        kept = apply_review(ROWS, HEADERS, {"sort": [
            {"column": "year", "descending": True}, {"column": "Title", "descending": False},
        ]})
        assert [r[0] for r in kept] == ["Frieren", "Oshi no Ko", "Suzume", "Your Name"]

    def test_a_single_sort_object_is_accepted(self):
        kept = apply_review(ROWS, HEADERS, {"sort": {"column": "Year", "descending": False}})
        assert kept[0][1] == "2016"

    def test_an_unknown_sort_column_leaves_the_order(self):
        assert apply_review(ROWS, HEADERS, {"sort": [{"column": "Studio"}]}) == ROWS

    def test_empty_cells_sort_last(self):
        rows = [["a", ""], ["b", "2020"], ["c", "2024"]]
        kept = apply_review(rows, ["T", "Year"], {"sort": [{"column": "Year", "descending": True}]})
        assert [r[0] for r in kept] == ["c", "b", "a"]

    def test_a_verdict_that_drops_everything_is_ignored(self):
        assert apply_review(ROWS, HEADERS, {"drop": [1, 2, 3, 4]}) == ROWS

    def test_nonsense_row_numbers_are_ignored(self):
        assert apply_review(ROWS, HEADERS, {"drop": ["x", None, 99]}) == ROWS


class TestParse:
    def test_fenced_json(self):
        assert parse_verdict('```json\n{"drop": [1]}\n```') == {"drop": [1]}

    def test_garbage_is_no_verdict(self):
        assert parse_verdict("I think row 2 is wrong") is None
