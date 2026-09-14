"""Conversation memory decides what the model reads above the question.

Three separate defects lived in this one window, and each of them reached the
user as the workspace being wrong rather than as an error:

* A refusal is stored exactly the way an answer is, so the window fed the model
  its own "I don't have enough information in the knowledge base to answer
  that". One refusal made every later turn more likely to refuse.
* Turn rows record the document scope they were asked under; the window ignored
  it, so selecting a different document left the previous document's answers in
  the prompt and the model answered from them.
* Source numbers are minted per turn, so a ``[S5]`` carried in from an older
  answer names whatever happens to be fifth this time - or nothing, in which
  case the validator throws away an otherwise good answer as an invented
  citation.

These tests exercise ``ConversationMemory`` against a recording fake of the
repository, so what is asserted is the filter it asks for and the text it hands
back, not the SQL dialect underneath.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.document_platform.conversation.memory import ConversationMemory


@dataclass
class FakeTurn:
    question: str
    answer: str | None


class RecordingRepo:
    """Captures the arguments the memory window asks the repository for."""

    def __init__(self, *turns: FakeTurn) -> None:
        self._turns = list(turns)
        self.calls: list[tuple[str, int, list[str] | None]] = []

    async def completed_turns(
        self, conversation_id: str, limit: int, document_ids: list[str] | None = None,
    ) -> list[FakeTurn]:
        self.calls.append((conversation_id, limit, document_ids))
        return self._turns

    @property
    def last_scope(self) -> list[str] | None:
        return self.calls[-1][2]


def memory(repo: RecordingRepo, max_turns: int = 6) -> ConversationMemory:
    return ConversationMemory(repo, max_turns)


class TestDocumentScope:
    """The scope a question is asked under has to reach the query."""

    async def test_a_single_document_becomes_a_one_document_scope(self) -> None:
        repo = RecordingRepo()
        await memory(repo).window("conv-1", "doc-a")
        assert repo.last_scope == ["doc-a"]

    async def test_a_multi_document_selection_is_passed_through(self) -> None:
        repo = RecordingRepo()
        await memory(repo).window("conv-1", ["doc-a", "doc-b"])
        assert repo.last_scope == ["doc-a", "doc-b"]

    async def test_no_selection_means_no_document_filter(self) -> None:
        """Asked over the whole workspace, every turn is in scope."""
        repo = RecordingRepo()
        await memory(repo).window("conv-1")
        assert repo.last_scope is None

    async def test_an_empty_selection_is_not_a_filter_that_matches_nothing(self) -> None:
        """An empty list must not become ``document_id IN ()``."""
        repo = RecordingRepo()
        await memory(repo).window("conv-1", [])
        assert repo.last_scope is None

    async def test_the_turn_limit_still_reaches_the_repository(self) -> None:
        repo = RecordingRepo()
        await memory(repo, max_turns=3).window("conv-1", "doc-a")
        assert repo.calls[-1][:2] == ("conv-1", 3)


class TestStaleCitationMarkers:
    """Markers are per-turn; carrying one forward invents a citation."""

    async def test_markers_are_stripped_from_remembered_answers(self) -> None:
        repo = RecordingRepo(FakeTurn("How many rows?", "There are 1252 rows [S5]."))
        history = await memory(repo).window("conv-1", "doc-a")
        assert history[0].answer == "There are 1252 rows."

    async def test_every_marker_goes_not_just_the_first(self) -> None:
        repo = RecordingRepo(
            FakeTurn("Columns?", "Id [S1], Code [S2] and Label [S10] are columns.")
        )
        history = await memory(repo).window("conv-1", "doc-a")
        assert "[S" not in history[0].answer

    async def test_the_answer_still_reads_as_a_sentence(self) -> None:
        """Stripping takes the space before the marker so no double space is left."""
        repo = RecordingRepo(FakeTurn("Q", "The total is 1252 [S5] for this sheet."))
        history = await memory(repo).window("conv-1", "doc-a")
        assert history[0].answer == "The total is 1252 for this sheet."

    async def test_text_without_markers_is_untouched(self) -> None:
        repo = RecordingRepo(FakeTurn("Q", "A plain answer with no citations."))
        history = await memory(repo).window("conv-1", "doc-a")
        assert history[0].answer == "A plain answer with no citations."

    async def test_a_missing_answer_becomes_empty_not_none(self) -> None:
        repo = RecordingRepo(FakeTurn("Q", None))
        history = await memory(repo).window("conv-1", "doc-a")
        assert history[0].answer == ""

    async def test_the_question_is_carried_through_unchanged(self) -> None:
        repo = RecordingRepo(FakeTurn("How many rows [S1]?", "1252."))
        history = await memory(repo).window("conv-1", "doc-a")
        assert history[0].question == "How many rows [S1]?"


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("Value is 12 [S1].", "Value is 12."),
        ("[S1] leads the sentence.", "leads the sentence."),
        ("Multiple [S1][S2] together.", "Multiple together."),
        ("Not a marker: [Section 1].", "Not a marker: [Section 1]."),
        ("Lowercase [s1] is not a marker.", "Lowercase [s1] is not a marker."),
    ],
)
async def test_marker_stripping_cases(answer: str, expected: str) -> None:
    repo = RecordingRepo(FakeTurn("Q", answer))
    history = await memory(repo).window("conv-1", "doc-a")
    assert history[0].answer == expected
