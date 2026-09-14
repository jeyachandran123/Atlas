"""Table rows in a generation spec: what reaches the file."""

from __future__ import annotations

from app.document_platform.generation.transformer import TransformationEngine


def spec(rows):
    return {"title": "T", "sections": [
        {"heading": "Data", "table": {"name": "t", "headers": ["Title", "Year"], "rows": rows}},
    ]}


def table_rows(rows):
    return TransformationEngine().transform(spec(rows)).sections[0].table.rows


class TestRows:
    def test_a_repeated_block_of_rows_is_written_once(self):
        block = [["Frieren", "2023"], ["Oshi no Ko", "2023"]]
        assert table_rows(block + block) == block

    def test_repeats_differing_only_in_case_are_the_same_row(self):
        assert table_rows([["Belle", "2021"], ["belle", "2021"]]) == [["Belle", "2021"]]

    def test_rows_sharing_one_value_are_kept(self):
        rows = [["Suzume", "2022"], ["Suzume", "2023"]]
        assert table_rows(rows) == rows

    def test_short_rows_are_padded_before_comparing(self):
        assert table_rows([["Arcane"], ["Arcane", ""]]) == [["Arcane", ""]]
