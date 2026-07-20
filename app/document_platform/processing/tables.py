"""TableExtractor — collects structured tables; tables never become plain text."""
from __future__ import annotations

from app.document_platform.processing.models import (
    DocumentNode,
    NodeType,
    ParsedDocument,
    TableData,
)


class TableExtractor:
    def extract(self, parsed: ParsedDocument, tree: DocumentNode) -> list[TableData]:
        """
        Union of parser-reported tables and TABLE nodes found in the tree
        (deduplicated by identity of content).
        """
        tables: list[TableData] = list(parsed.tables)
        seen = {self._fingerprint(t) for t in tables}

        for node in tree.walk():
            if node.type != NodeType.TABLE:
                continue
            t = self._from_node(node)
            fp = self._fingerprint(t)
            if fp not in seen and (t.rows or t.headers):
                seen.add(fp)
                tables.append(t)
        return tables

    @staticmethod
    def _from_node(node: DocumentNode) -> TableData:
        headers: list[str] = list(node.meta.get("headers", []))
        rows: list[list[str]] = []
        for row in node.children:
            if row.type != NodeType.ROW:
                continue
            cells = [c.text for c in row.children if c.type == NodeType.CELL]
            if row.meta.get("is_header") and not headers:
                headers = cells
            else:
                rows.append(cells)
        return TableData(
            headers=headers,
            rows=rows,
            page=node.page,
            caption=node.meta.get("caption", ""),
            merged_cells=list(node.meta.get("merged_cells", [])),
        )

    @staticmethod
    def _fingerprint(t: TableData) -> str:
        head = "|".join(t.headers)
        first = "|".join(t.rows[0]) if t.rows else ""
        return f"{head}#{first}#{t.row_count}x{t.col_count}"
