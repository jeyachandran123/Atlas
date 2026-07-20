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
        """A table is one chunk: readable text rendering + structured meta."""
        headers: list[str] = list(node.meta.get("headers", []))
        rows: list[list[str]] = []
        for row in node.children:
            if row.type == NodeType.ROW:
                cells = [c.text for c in row.children if c.type == NodeType.CELL]
                if row.meta.get("is_header") and not headers:
                    headers = cells
                else:
                    rows.append(cells)

        lines: list[str] = []
        if headers:
            lines.append(" | ".join(headers))
        lines.extend(" | ".join(r) for r in rows[:100])
        text = "\n".join(lines).strip() or "(empty table)"

        chunks.append(
            Chunk(
                seq=len(chunks),
                content=text,
                token_count=estimate_tokens(text),
                node_type="table",
                section_path=" > ".join(path),
                page=node.page,
                meta={"headers": headers, "rows": rows, "row_count": len(rows)},
            )
        )
