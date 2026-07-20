"""
The internal knowledge representation — UnityWorks' single unified format.

Every parser emits a ParsedDocument (type-specific raw structure). The
Normalizer converts it into a DocumentNode tree. Everything downstream
(structure analysis, chunking, the Knowledge Object) speaks DocumentNode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class NodeType(str, Enum):
    DOCUMENT = "document"
    SECTION = "section"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    LIST_ITEM = "list_item"
    TABLE = "table"
    ROW = "row"
    CELL = "cell"
    IMAGE = "image"
    CODE_BLOCK = "code_block"
    PAGE = "page"
    SLIDE = "slide"
    SHEET = "sheet"
    OBJECT = "object"
    ARRAY = "array"
    VALUE = "value"
    NOTE = "note"


@dataclass
class DocumentNode:
    """One node in the unified document tree."""

    type: NodeType
    text: str = ""
    level: int = 0                      # heading level / tree depth
    page: Optional[int] = None          # 1-based page/slide/sheet index
    position: int = 0                   # order within parent
    children: list["DocumentNode"] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def add(self, child: "DocumentNode") -> "DocumentNode":
        child.position = len(self.children)
        self.children.append(child)
        return child

    def walk(self):
        """Depth-first traversal."""
        yield self
        for c in self.children:
            yield from c.walk()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type.value, "position": self.position}
        if self.text:
            d["text"] = self.text
        if self.level:
            d["level"] = self.level
        if self.page is not None:
            d["page"] = self.page
        if self.meta:
            d["meta"] = self.meta
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


@dataclass
class TableData:
    """A structured table — never flattened to text."""

    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    page: Optional[int] = None
    caption: str = ""
    merged_cells: list[str] = field(default_factory=list)  # e.g. ["A1:B2"]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def col_count(self) -> int:
        return max((len(r) for r in self.rows), default=len(self.headers))

    def to_dict(self) -> dict[str, Any]:
        return {
            "headers": self.headers,
            "rows": self.rows,
            "page": self.page,
            "caption": self.caption,
            "merged_cells": self.merged_cells,
            "row_count": self.row_count,
            "col_count": self.col_count,
        }


@dataclass
class ImageRef:
    """An image found inside a document (binary handled by ImageExtractor)."""

    name: str
    content: Optional[bytes] = None     # raw bytes when the parser can extract them
    page: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    format: str = ""                    # png/jpeg/…
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawMetadata:
    """Metadata as reported by the source file (before enrichment)."""

    title: str = ""
    author: str = ""
    created: str = ""
    modified: str = ""
    page_count: Optional[int] = None
    sheet_count: Optional[int] = None
    slide_count: Optional[int] = None
    encoding: str = "utf-8"
    custom: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    """
    Raw output of a type-specific parser. `root` is a preliminary node tree in
    the parser's own shape; the Normalizer owns turning it into the canonical
    tree (merging stray text, wrapping loose nodes into sections, etc.).
    """

    root: DocumentNode
    tables: list[TableData] = field(default_factory=list)
    images: list[ImageRef] = field(default_factory=list)
    raw_metadata: RawMetadata = field(default_factory=RawMetadata)
    needs_ocr: bool = False             # scanned PDF / image with no text layer
    parser_name: str = ""


@dataclass
class Chunk:
    """A retrieval-ready semantic chunk built from the node tree."""

    seq: int
    content: str
    token_count: int
    node_type: str
    section_path: str = ""              # "Introduction > Background"
    page: Optional[int] = None
    meta: dict[str, Any] = field(default_factory=dict)
