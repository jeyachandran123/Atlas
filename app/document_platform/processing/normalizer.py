"""
Normalizer — converts every parser's output into the canonical DocumentNode
tree. Parsers emit preliminary trees in their own shape; this stage enforces
the invariants downstream stages rely on:

  - root is a DOCUMENT node
  - positions are sequential within each parent
  - empty text nodes are dropped
  - heading levels are sane (1..6)
"""
from __future__ import annotations

from app.document_platform.processing.models import DocumentNode, NodeType, ParsedDocument


class Normalizer:
    def normalize(self, parsed: ParsedDocument) -> DocumentNode:
        root = parsed.root
        if root.type != NodeType.DOCUMENT:
            wrapper = DocumentNode(type=NodeType.DOCUMENT)
            wrapper.add(root)
            root = wrapper

        self._prune_empty(root)
        self._clamp_heading_levels(root)
        self._reindex(root)
        return root

    def _prune_empty(self, node: DocumentNode) -> None:
        kept: list[DocumentNode] = []
        for child in node.children:
            self._prune_empty(child)
            is_container = child.type in (
                NodeType.DOCUMENT, NodeType.SECTION, NodeType.PAGE, NodeType.SLIDE,
                NodeType.SHEET, NodeType.TABLE, NodeType.ROW, NodeType.LIST,
                NodeType.OBJECT, NodeType.ARRAY,
            )
            if child.text.strip() or child.children or (child.type == NodeType.IMAGE) or (is_container and child.children):
                kept.append(child)
        node.children = kept

    def _clamp_heading_levels(self, root: DocumentNode) -> None:
        for n in root.walk():
            if n.type == NodeType.HEADING:
                n.level = min(max(n.level or 1, 1), 6)

    def _reindex(self, node: DocumentNode) -> None:
        for i, child in enumerate(node.children):
            child.position = i
            self._reindex(child)
