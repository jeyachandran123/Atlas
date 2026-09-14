"""Spreadsheets must produce embeddable chunks.

These tests exist because of a specific production failure: a six-row grocery
list produced a **62,207-character** chunk, Ollama refused it with "the input
length exceeds the context length", the embedding job dead-lettered after three
attempts, and every question about that document was answered with "I don't
have enough information in the knowledge base to answer that."

Nothing in the stack reported a problem. The upload succeeded, processing
succeeded, the document was marked `knowledge_ready`, and the UI listed it as a
ready source. The only visible symptom was a refusal that looks identical to
asking about a document nobody uploaded.

Two independent defects produced it, and each gets its own test, because either
one alone is enough to break ingestion again:

1. `ExcelParser` padded every row out to `_MAX_COLS` columns, so a 4-column
   sheet emitted 200 cells per row — 196 of them empty.
2. `ChunkingEngine._emit_table` emitted a whole table as one chunk regardless
   of the token budget the engine was constructed with.
"""

from __future__ import annotations

import io

import pytest

from app.document_platform.processing.chunker import ChunkingEngine, estimate_tokens
from app.document_platform.processing.models import DocumentNode, NodeType
from app.document_platform.processing.parsers.excel import ExcelParser

openpyxl = pytest.importorskip("openpyxl")


def _workbook(rows: list[list[object]], title: str = "Shopping List") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


GROCERY = [
    ["Item", "Quantity", "Category", "Price"],
    ["Milk", 2, "Dairy", 3.50],
    ["Bread", 1, "Bakery", 2.25],
    ["Eggs", 12, "Dairy", 4.99],
    ["Apples", 6, "Produce", 5.40],
    ["Chicken Breast", 2, "Meat", 12.00],
]


# ── defect 1: the parser padded every row to 200 columns ─────────────────────


def test_a_narrow_sheet_does_not_emit_phantom_columns() -> None:
    """A 4-column sheet has 4 columns.

    `iter_rows(max_col=200)` returns empty cells out to column 200 whether or
    not the sheet is that wide, and the parser kept every one of them. The row
    then rendered as `Milk | 2 | Dairy | 3.5 |  |  |  | ...` — 196 empty cells
    of separator noise carried into the embedding.
    """
    parsed = ExcelParser().parse(_workbook(GROCERY), "grocery-shopping-list.xlsx")

    rows = [n for n in _walk(parsed.root) if n.type == NodeType.ROW]
    assert rows, "expected the sheet to produce row nodes"
    for row in rows:
        cells = [c for c in row.children if c.type == NodeType.CELL]
        assert len(cells) == 4, f"expected 4 cells, got {len(cells)}"


def test_a_narrow_sheet_chunk_is_mostly_content_not_separators() -> None:
    """The regression stated as the thing a reader would notice.

    The failing chunk was ~97% `|` and whitespace. A chunk that is mostly
    punctuation embeds to a vector that means nothing, so even when it fits it
    retrieves badly — this asserts the *quality*, not just the size.
    """
    parsed = ExcelParser().parse(_workbook(GROCERY), "grocery-shopping-list.xlsx")
    chunks = ChunkingEngine().chunk(parsed.root)
    assert chunks

    text = "\n".join(c.content for c in chunks)
    separators = text.count("|") + text.count(" ")
    assert separators < len(text) * 0.5, (
        f"chunk is {separators}/{len(text)} separators — the padding is back"
    )
    assert "Chicken Breast" in text
    assert "Produce" in text


# ── defect 2: the chunker ignored its own token budget for tables ────────────


def test_a_large_table_is_split_to_respect_the_token_budget() -> None:
    """`ChunkingEngine(max_tokens=N)` must mean N for tables too.

    This is the defect that actually broke ingestion, and it is independent of
    the parser: any wide or long table — from Excel, CSV, Word or a PDF — became
    one unbounded chunk. Fixing only the Excel padding would leave a genuinely
    large spreadsheet failing in exactly the same way, with the same silent
    refusal.
    """
    wide = [[f"col{c}" for c in range(12)]]
    wide += [[f"r{r}c{c}" for c in range(12)] for r in range(400)]

    parsed = ExcelParser().parse(_workbook(wide, title="Big"), "big.xlsx")
    engine = ChunkingEngine(target_tokens=400, max_tokens=600)
    chunks = engine.chunk(parsed.root)

    assert len(chunks) > 1, "a 400-row table must not be a single chunk"
    for chunk in chunks:
        assert chunk.token_count <= 600, (
            f"chunk {chunk.seq} is {chunk.token_count} tokens, over the 600 budget"
        )


def test_every_row_survives_a_split_table() -> None:
    """Splitting must not lose data. A chunker that drops rows to fit the
    budget would answer questions confidently and wrongly, which is worse than
    the refusal this whole fix exists to remove."""
    rows = [["Item", "Qty"]] + [[f"item-{i}", i] for i in range(300)]
    parsed = ExcelParser().parse(_workbook(rows, title="Long"), "long.xlsx")
    chunks = ChunkingEngine(target_tokens=200, max_tokens=300).chunk(parsed.root)

    combined = "\n".join(c.content for c in chunks)
    for i in (0, 42, 199, 299):
        assert f"item-{i}" in combined, f"row item-{i} was lost when splitting"


def test_a_split_table_repeats_its_header_in_every_chunk() -> None:
    """Each chunk is retrieved on its own, so each one has to be readable on
    its own. A chunk of bare values with the header left behind in chunk 1 is
    a table nobody — model or person — can interpret."""
    rows = [["Item", "Qty", "Category"]] + [[f"item-{i}", i, "Food"] for i in range(300)]
    parsed = ExcelParser().parse(_workbook(rows, title="Long"), "long.xlsx")
    chunks = ChunkingEngine(target_tokens=200, max_tokens=300).chunk(parsed.root)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.content.startswith("Item | Qty | Category"), (
            f"chunk {chunk.seq} has no header row"
        )


# ── the end-to-end property the incident was actually about ──────────────────


def test_a_grocery_list_produces_chunks_an_embedder_will_accept() -> None:
    """The regression, stated as the production symptom.

    nomic-embed-text's context is 2048 tokens. The chunk that broke the demo
    estimated at 15,551. This asserts the property that actually matters: every
    chunk this pipeline emits must be small enough to embed, because a chunk
    that cannot be embedded is a document that cannot be found, reported to the
    user as though the knowledge base were empty.
    """
    parsed = ExcelParser().parse(_workbook(GROCERY), "grocery-shopping-list.xlsx")
    chunks = ChunkingEngine().chunk(parsed.root)

    assert chunks, "the spreadsheet produced no chunks at all"
    for chunk in chunks:
        assert estimate_tokens(chunk.content) < 2048, (
            f"chunk {chunk.seq} is {estimate_tokens(chunk.content)} tokens — "
            f"an embedder with a 2048-token context will refuse it"
        )


def _walk(node: DocumentNode):
    yield node
    for child in node.children:
        yield from _walk(child)
