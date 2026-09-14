"""
ChunkingEngine — structure-aware semantic chunking. Not string splitting.

Walks the section hierarchy. Text nodes accumulate into a chunk until the
token budget is reached, never crossing a section boundary. Tables become
their own chunks with the structured data preserved in meta. Every chunk
records its section path, page, position, and token count.
"""
from __future__ import annotations

from app.document_platform.processing.models import Chunk, DocumentNode, NodeType

_TEXT_TYPES = {
    NodeType.PARAGRAPH, NodeType.HEADING, NodeType.LIST_ITEM,
    NodeType.CODE_BLOCK, NodeType.VALUE, NodeType.NOTE, NodeType.CELL,
}
_CONTAINER_TYPES = {
    NodeType.DOCUMENT, NodeType.SECTION, NodeType.PAGE, NodeType.SLIDE,
    NodeType.SHEET, NodeType.LIST, NodeType.OBJECT, NodeType.ARRAY,
}


def estimate_tokens(text: str) -> int:
    """~4 chars/token — the convention already used across this codebase."""
    return max(1, len(text) // 4)


class ChunkingEngine:
    def __init__(self, target_tokens: int = 400, max_tokens: int = 600) -> None:
        self._target = target_tokens
        self._max = max_tokens

    def chunk(self, root: DocumentNode) -> list[Chunk]:
        chunks: list[Chunk] = []
        buffer: list[str] = []
        buffer_tokens = 0
        buffer_page: int | None = None
        current_path: list[str] = []

        def flush(node_type: str = "paragraph") -> None:
            nonlocal buffer, buffer_tokens, buffer_page
            text = "\n".join(buffer).strip()
            if text:
                chunks.append(
                    Chunk(
                        seq=len(chunks),
                        content=text,
                        token_count=estimate_tokens(text),
                        node_type=node_type,
                        section_path=" > ".join(current_path),
                        page=buffer_page,
                    )
                )
            buffer, buffer_tokens, buffer_page = [], 0, None

        def visit(node: DocumentNode) -> None:
            nonlocal buffer_tokens, buffer_page

            if node.type == NodeType.SECTION:
                flush()  # never cross a section boundary
                current_path.append(node.text.strip() or "Untitled section")
                for c in node.children:
                    visit(c)
                flush()
                current_path.pop()
                return

            if node.type == NodeType.TABLE:
                flush()
                self._emit_table(node, chunks, current_path)
                return

            if node.type in _TEXT_TYPES:
                text = node.text.strip()
                if text:
                    t = estimate_tokens(text)
                    if buffer_tokens + t > self._max and buffer:
                        flush()
                    buffer.append(text)
                    buffer_tokens += t
                    if buffer_page is None:
                        buffer_page = node.page
                    if buffer_tokens >= self._target:
                        flush()
                # fallthrough: text nodes may still carry children (e.g. list items)

            if node.type in _CONTAINER_TYPES or node.children:
                for c in node.children:
                    visit(c)

        visit(root)
        flush()
        return chunks

    def _emit_table(
        self, node: DocumentNode, chunks: list[Chunk], path: list[str]
    ) -> None:
        """A table becomes as many chunks as its token budget requires.

        ### It used to be exactly one chunk, and that broke ingestion

        A table was emitted whole, no matter how large, while every other node
        type in this engine respected `max_tokens`. Embedding models have a
        context limit — nomic-embed-text's is 2048 tokens — so a large table
        produced a chunk the embedder rejected with a 500. The embedding job
        then failed, retried twice, dead-lettered, and the document sat marked
        `knowledge_ready` with no vectors behind it. Every question about it was
        refused as though the knowledge base were empty.

        Nothing in that chain reported a fault to anyone, which is why this is
        enforced here rather than left to the embedding provider to survive.

        ### Two rules make a split table still readable

        **The header repeats in every chunk.** Each chunk is retrieved on its
        own, so each has to be interpretable on its own; a chunk of bare values
        whose header stayed behind in chunk one is a table nobody can read.

        **No row is dropped.** The previous implementation rendered `rows[:100]`
        and silently discarded the rest — a 300-row sheet answered questions
        about its first hundred rows and denied all knowledge of the others,
        confidently. Truncation that quiet is worse than a refusal.
        """
        headers: list[str] = list(node.meta.get("headers", []))
        rows: list[list[str]] = []
        for row in node.children:
            if row.type == NodeType.ROW:
                cells = [c.text for c in row.children if c.type == NodeType.CELL]
                if row.meta.get("is_header") and not headers:
                    headers = cells
                else:
                    rows.append(cells)

        header_line = " | ".join(headers) if headers else ""
        header_tokens = estimate_tokens(header_line) if header_line else 0

        def emit(batch: list[list[str]], part: int, total_parts: int) -> None:
            lines = [header_line] if header_line else []
            lines.extend(" | ".join(r) for r in batch)
            text = "\n".join(lines).strip() or "(empty table)"
            meta: dict = {
                "headers": headers,
                "rows": batch,
                "row_count": len(batch),
            }
            if total_parts > 1:
                # Stated in the chunk's own metadata so a reader (or a citation)
                # can tell a partial table from a whole one.
                meta["table_part"] = part
                meta["table_parts"] = total_parts
            chunks.append(
                Chunk(
                    seq=len(chunks),
                    content=text,
                    token_count=estimate_tokens(text),
                    node_type="table",
                    section_path=" > ".join(path),
                    page=node.page,
                    meta=meta,
                )
            )

        if not rows:
            emit([], 1, 1)
            return

        # Pack rows into batches that fit the budget, header included — the
        # header is repeated in each, so it is charged against each.
        #
        # The budget is measured in characters and converted once, exactly as
        # `emit` does. Summing a per-row `estimate_tokens` instead looks
        # equivalent and is not: `len(text) // 4` floors, so every row discards
        # up to three characters from the count, and the newlines `emit` joins
        # with are never counted at all. Those omissions accumulate — 26 rows
        # were enough to land an 11-token overshoot on a 600-token budget — and
        # an overshoot here is not a rounding error, it is the embedding call
        # failing and the document silently never being indexed.
        batches: list[list[list[str]]] = []
        current: list[list[str]] = []
        current_chars = len(header_line)

        def _added_chars(line: str, has_preceding_line: bool) -> int:
            """Characters `line` costs, counting the newline `emit` inserts."""
            return len(line) + (1 if has_preceding_line else 0)

        for row in rows:
            row_line = " | ".join(row)
            added = _added_chars(row_line, bool(header_line or current))
            if current and (current_chars + added) // 4 > self._max:
                batches.append(current)
                current = []
                current_chars = len(header_line)
                added = _added_chars(row_line, bool(header_line))
            current.append(row)
            current_chars += added
            # A single row wider than the whole budget cannot be split further
            # without destroying its meaning. It is emitted alone rather than
            # dropped: an over-budget chunk degrades retrieval, a missing one
            # loses the data outright.
        if current:
            batches.append(current)

        for index, batch in enumerate(batches, start=1):
            emit(batch, index, len(batches))
