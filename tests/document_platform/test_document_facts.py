"""Totals must be counted by the platform, never by the model.

Retrieval hands the model eight excerpts and the prompt tells it to answer only
from what it was given. Asked "can you tell me how many rows are there??" about
a 1252-row spreadsheet, a model obeying that instruction counted the excerpts
and answered "There are 20 rows in the provided data." Nothing in the prompt
had told it the excerpts were a sample, so this was a fabrication the prompt
invited rather than a model that misbehaved.

The chunker already recorded ``row_count`` for every table part it wrote, so the
real total is an aggregate, not a re-read of the file. It rides into the prompt
as an ordinary numbered source, which means a total the model quotes carries a
citation exactly like any other claim.
"""

from __future__ import annotations

import pytest

from app.document_platform.conversation.citations import CitationBuilder
from app.document_platform.conversation.context_builder import (
    ContextBuilder,
    DocumentFacts,
)
from app.document_platform.conversation.ranking import RankedChunk
from app.document_platform.conversation.retrieval import RetrievedChunk
from app.document_platform.conversation.validator import ResponseValidator

DISH = "doc-dish"
OTHER = "doc-other"


def chunk(seq: int, text: str, document_id: str = DISH, confidence: float = 0.7) -> RankedChunk:
    return RankedChunk(
        chunk=RetrievedChunk(
            chunk_id=f"{document_id}-c{seq}",
            knowledge_id=f"{document_id}-k",
            document_id=document_id,
            text=text,
            score=confidence,
            seq=seq,
            section_path="Sheet1",
            node_type="table",
        ),
        confidence=confidence,
        signal_scores={},
    )


def dish_facts(**overrides) -> DocumentFacts:
    base = dict(
        document_id=DISH,
        filename="UAT-EMOS-Dish Template 10092026.xlsx",
        doc_type="xlsx",
        title="Sheet1",
        chunk_count=382,
        word_count=80025,
        table_count=1,
        table_rows=1252,
    )
    base.update(overrides)
    return DocumentFacts(**base)


class TestTheFactsBlockReads:
    def test_it_carries_the_real_row_total(self) -> None:
        assert "1252" in dish_facts().as_source_text()

    def test_it_says_the_excerpts_are_not_everything(self) -> None:
        """The sentence that stops the model counting what it was handed."""
        text = dish_facts().as_source_text()
        assert "382" in text
        assert "not all of them" in text

    def test_it_names_the_document(self) -> None:
        assert "UAT-EMOS-Dish Template 10092026.xlsx" in dish_facts().as_source_text()

    def test_absent_numbers_are_left_out_rather_than_reported_as_zero(self) -> None:
        """A total we do not have must not read as a total of none."""
        text = DocumentFacts(document_id=DISH, filename="notes.txt", doc_type="txt").as_source_text()
        assert "rows" not in text
        assert "pages" not in text

    def test_pages_appear_for_paged_documents(self) -> None:
        text = DocumentFacts(
            document_id=DISH, filename="spec.pdf", doc_type="pdf", page_count=14
        ).as_source_text()
        assert "pages: 14" in text


class TestTheBundleCarriesIt:
    def test_facts_become_a_citable_source(self) -> None:
        bundle = ContextBuilder(4000).build([chunk(0, "Id | Code")], [dish_facts()])
        facts_source = bundle.sources[-1]
        assert facts_source.source_id == "S2"
        assert "1252" in facts_source.text

    def test_it_goes_last_so_excerpt_numbering_is_unchanged(self) -> None:
        """S1 must stay the top-ranked excerpt whether or not facts are present."""
        ranked = [chunk(0, "Id | Code"), chunk(5, "Label | Dish Type")]
        without = ContextBuilder(4000).build(ranked)
        with_facts = ContextBuilder(4000).build(ranked, [dish_facts()])
        assert [s.text for s in without.sources] == [
            s.text for s in with_facts.sources[:-1]
        ]

    def test_no_facts_means_no_extra_source(self) -> None:
        bundle = ContextBuilder(4000).build([chunk(0, "Id | Code")], None)
        assert len(bundle.sources) == 1

    def test_facts_for_a_document_not_in_the_bundle_are_dropped(self) -> None:
        """Only documents whose content actually made it in get described."""
        bundle = ContextBuilder(4000).build(
            [chunk(0, "Id | Code")],
            [dish_facts(), DocumentFacts(document_id=OTHER, filename="other.xlsx")],
        )
        assert [s.document_id for s in bundle.sources] == [DISH, DISH]

    def test_facts_survive_a_tight_token_budget(self) -> None:
        """Dropping the block is exactly what lets the model invent a total."""
        # Non-adjacent seqs so each stays its own source and the budget bites;
        # consecutive ones would merge into a single group and never truncate.
        ranked = [chunk(i * 10, "row text " * 200) for i in range(6)]
        bundle = ContextBuilder(120).build(ranked, [dish_facts()])
        assert bundle.truncated
        assert "1252" in bundle.sources[-1].text

    def test_facts_do_not_lift_the_confidence_gate(self) -> None:
        """best_confidence is measured from retrieved chunks, not from facts."""
        ranked = [chunk(0, "Id | Code", confidence=0.2)]
        bundle = ContextBuilder(4000).build(ranked, [dish_facts()])
        assert bundle.best_confidence == pytest.approx(0.2)


class TestCitingTheFacts:
    def test_a_total_quoted_from_facts_resolves_to_a_citation(self) -> None:
        bundle = ContextBuilder(4000).build([chunk(0, "Id | Code")], [dish_facts()])
        outcome = CitationBuilder().build("There are 1252 rows [S2].", bundle, {})
        assert [c.source_id for c in outcome.citations] == ["S2"]
        assert outcome.unresolved_markers == []

    def test_the_facts_citation_has_no_chunk_or_page(self) -> None:
        """It was measured over the document, so it points at no single chunk."""
        bundle = ContextBuilder(4000).build([chunk(0, "Id | Code")], [dish_facts()])
        outcome = CitationBuilder().build("1252 rows [S2].", bundle, {})
        assert outcome.citations[0].chunk_ids == []
        assert outcome.citations[0].page is None

    def test_such_an_answer_passes_validation(self) -> None:
        """The end of the bug: the row count reaches the user instead of a refusal."""
        bundle = ContextBuilder(4000).build([chunk(0, "Id | Code")], [dish_facts()])
        outcome = CitationBuilder().build("There are 1252 rows [S2].", bundle, {})
        result = ResponseValidator(0.35).validate("There are 1252 rows [S2].", outcome, bundle)
        assert result.valid and result.grounded


class TestThePromptSaysWhyItIsThere:
    def test_the_rules_forbid_counting_the_excerpts(self) -> None:
        from app.document_platform.conversation.prompts import GroundedAnswerStrategy

        rules = GroundedAnswerStrategy._SYSTEM.lower()
        assert "excerpts, not the whole document" in rules
        assert "document facts" in rules
