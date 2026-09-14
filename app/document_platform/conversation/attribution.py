"""Which source an answer actually came from, decided by evidence.

The grounding contract wants every claim tied to a source, and the usual way
to establish that is to make the model write ``[S1]`` after it. That works
until the model declines to. Measured against the deployed model on a
"summarise this document" question, half of all answers came back factually
perfect and completely unmarked, and the repair pass - handing the draft back
and asking for markers - returned the draft byte-for-byte unchanged three
times out of three. The answer was right, the sources supported it, and the
user was shown "I could not tie this back to the sources" every other try.

So this module establishes the link the other way round: instead of trusting
a marker the model typed, it checks whether the sources actually contain what
the answer says. That is a *stronger* test, not a weaker one - a model can
type ``[S1]`` after a sentence it invented, and that passes a marker check
while failing this one.

Nothing here relaxes the contract. An answer that no source supports stays
rejected, an invented citation is still an invented citation, and the
grounding score still has to clear its floor afterwards. What it removes is
the case where a correct, sourced answer is thrown away over punctuation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.document_platform.conversation.context_builder import ContextBundle

_WORD = re.compile(r"[a-z0-9][a-z0-9\-/:.]*")

_MIN_CONTENT_WORDS = 8
"""Below this a paragraph is a heading or a lead-in, not a claim.

Attaching a citation to "**Journey Details**" would be noise, and worse, a
two-word line trivially scores 1.0 against any source that happens to contain
both words - a high score on almost no evidence.
"""

_STOP = frozenset({
    "the", "and", "for", "from", "with", "that", "this", "have", "has", "was",
    "are", "were", "which", "also", "here", "there", "based", "provided",
    "sources", "source", "analysis", "document", "documents", "including",
    "includes", "into", "onto", "its", "his", "her", "their", "they", "you",
    "not", "but", "all", "any", "can", "will", "would", "been", "being",
    "following", "these", "those", "each", "such", "then", "than", "when",
    "what", "where", "does", "about", "some", "more", "most", "other",
})
"""Words that carry no evidence. Left in, they inflate every score equally and
flatten the difference between an answer drawn from the source and one drawn
from the model - which is the only thing being measured."""


@dataclass(frozen=True)
class Attribution:
    text: str
    """The answer with markers attached, or unchanged if nothing qualified."""

    attached: int
    """How many markers were added. Zero means nothing could be attributed."""

    best_support: float
    """The strongest paragraph-level support found, for logging."""


def _content_words(text: str) -> list[str]:
    words = []
    for raw in _WORD.findall(text.lower()):
        word = raw.strip(".:/-")
        if len(word) >= 4 and word not in _STOP:
            words.append(word)
    return words


def _figures(text: str) -> set[str]:
    """Every token carrying a digit: amounts, codes, times, dates, berths.

    These are what a fabricated answer gets wrong, and the only part of an
    answer that can be checked exactly rather than approximately. Word overlap
    is a judgement about whether a passage was drawn from a source; a number
    that is not in the source is simply not in the source.
    """
    figures = set()
    for raw in _WORD.findall(text.lower()):
        token = raw.strip(".:/-")
        if any(character.isdigit() for character in token):
            figures.add(token)
    return figures


def support(text: str, source_text: str) -> float:
    """The fraction of a passage's content words that appear in a source.

    Deliberately crude - set membership, no stemming, no embeddings. It is
    measuring whether an answer was *drawn from* a text, and for that the
    names, numbers and nouns are the whole signal: a summary of a train ticket
    repeats the passenger, the stations, the train and the fare, and an
    invented one cannot. Measured on real answers, a grounded summary scored
    0.84 against its source while the same summary with fabricated personal
    details scored 0.29 and an answer from outside knowledge scored 0.0.
    """
    haystack = set(_content_words(source_text))
    words = _content_words(text)
    if not words:
        return 0.0
    return sum(1 for word in words if word in haystack) / len(words)


def attribute(answer: str, bundle: ContextBundle, minimum: float) -> Attribution:
    """Attach ``[S#]`` to each paragraph a source demonstrably supports.

    Paragraph by paragraph rather than whole-answer, so a summary whose facts
    come from two sources is marked with both, and a paragraph nothing
    supports stays unmarked - which leaves it visible to the validator rather
    than laundering it under a citation earned by its neighbours.
    """
    if not answer.strip() or not bundle.sources:
        return Attribution(answer, 0, 0.0)

    haystacks = [
        (s, set(_content_words(s.text)), _figures(s.text)) for s in bundle.sources
    ]

    out: list[str] = []
    attached = 0
    best = 0.0
    for paragraph in answer.split("\n\n"):
        stripped = paragraph.strip()
        words = _content_words(stripped)
        if len(words) < _MIN_CONTENT_WORDS:
            out.append(paragraph)
            continue

        figures = _figures(stripped)
        ranked = sorted(
            (
                (
                    sum(1 for w in words if w in vocabulary) / len(words),
                    figures <= source_figures,
                    s,
                )
                for s, vocabulary, source_figures in haystacks
            ),
            key=lambda triple: (triple[1], triple[0]),
            reverse=True,
        )
        score, figures_check, source = ranked[0]
        best = max(best, score)
        # Both tests, because they catch different lies. Word overlap says the
        # passage was drawn from this source rather than written from
        # elsewhere; the figures test says every amount, code and time in it is
        # one the source actually contains. An answer about the right document
        # that quotes a fare nobody wrote down fails the second while passing
        # the first, and it is the one that would do real damage.
        if score >= minimum and figures_check:
            out.append(f"{paragraph.rstrip()} [{source.source_id}]")
            attached += 1
        else:
            out.append(paragraph)

    return Attribution("\n\n".join(out), attached, round(best, 3))
