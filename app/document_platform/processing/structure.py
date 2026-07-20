"""
StructuralAnalyzer — organizes a flat node tree into a section hierarchy.

Headings open sections at their level; following content nests inside.
The result is the hierarchy future reasoning walks: document → section →
subsection → paragraphs/tables/lists.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.document_platform.processing.models import DocumentNode, NodeType


@dataclass
class StructureStats:
    section_count: int = 0
    heading_count: int = 0
    paragraph_count: int = 0
    table_count: int = 0
    list_count: int = 0
    image_count: int = 0
    max_depth: int = 0


class StructuralAnalyzer:
    def analyze(self, root: DocumentNode) -> tuple[DocumentNode, StructureStats]:
        sectioned = self._build_sections(root)
        stats = self._stats(sectioned)
        return sectioned, stats

    def _build_sections(self, root: DocumentNode) -> DocumentNode:
        """
        Rebuild the top level of the tree so every heading starts a SECTION
        containing everything until the next heading of equal/higher rank.
        Container nodes (pages, slides, sheets) are processed recursively.
        """
        if not any(c.type == NodeType.HEADING for c in root.children):
            for child in root.children:
                if child.type in (NodeType.PAGE, NodeType.SLIDE, NodeType.DOCUMENT):
                    self._build_sections(child)
            return root

        new_children: list[DocumentNode] = []
        stack: list[tuple[int, DocumentNode]] = []  # (heading level, section node)

        def top_container() -> DocumentNode:
            return stack[-1][1] if stack else None  # type: ignore[return-value]

        for child in root.children:
            if child.type == NodeType.HEADING:
                level = child.level or 1
                while stack and stack[-1][0] >= level:
                    stack.pop()
                section = DocumentNode(
                    type=NodeType.SECTION, text=child.text, level=level, page=child.page
                )
                section.add(child)
                parent = top_container()
                if parent is not None:
                    parent.add(section)
                else:
                    new_children.append(section)
                stack.append((level, section))
            else:
                parent = top_container()
                if parent is not None:
                    parent.add(child)
                else:
                    new_children.append(child)

        root.children = []
        for c in new_children:
            root.add(c)
        return root

    def _stats(self, root: DocumentNode) -> StructureStats:
        s = StructureStats()

        def depth(node: DocumentNode, d: int) -> None:
            s.max_depth = max(s.max_depth, d)
            for c in node.children:
                depth(c, d + 1)

        depth(root, 0)
        for n in root.walk():
            if n.type == NodeType.SECTION:
                s.section_count += 1
            elif n.type == NodeType.HEADING:
                s.heading_count += 1
            elif n.type == NodeType.PARAGRAPH:
                s.paragraph_count += 1
            elif n.type == NodeType.TABLE:
                s.table_count += 1
            elif n.type == NodeType.LIST:
                s.list_count += 1
            elif n.type == NodeType.IMAGE:
                s.image_count += 1
        return s
