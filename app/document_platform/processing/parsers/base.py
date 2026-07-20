"""
Parser contract — one dedicated parser per document family.

A parser ONLY extracts the raw, type-specific structure into a preliminary
node tree + tables + images + source metadata. It never normalizes, never
cleans, never chunks, never OCRs — those are separate pipeline stages.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.document_platform.processing.capabilities import ParserCapabilities
from app.document_platform.processing.models import ParsedDocument
from app.document_platform.processing.versioning import DEFAULT_PARSER_VERSION


class ParserError(Exception):
    """The document could not be parsed by its dedicated parser."""


class AbstractDocumentParser(ABC):
    name: str = "abstract"
    extensions: tuple[str, ...] = ()
    version: str = DEFAULT_PARSER_VERSION
    capabilities: ParserCapabilities = ParserCapabilities()

    @abstractmethod
    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        """Extract raw structure. CPU-bound and synchronous — the background
        worker owns threading concerns, parsers stay simple."""
