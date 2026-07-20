"""Parser registry — extension → dedicated parser. Adding a type = one class + one line."""
from __future__ import annotations

from app.document_platform.processing.parsers.base import AbstractDocumentParser
from app.document_platform.processing.parsers.csv_ import CsvParser
from app.document_platform.processing.parsers.excel import ExcelParser
from app.document_platform.processing.parsers.image import ImageParser
from app.document_platform.processing.parsers.json_ import JsonParser
from app.document_platform.processing.parsers.markdown import MarkdownParser
from app.document_platform.processing.parsers.pdf import PdfParser
from app.document_platform.processing.parsers.powerpoint import PowerPointParser
from app.document_platform.processing.parsers.text import TextParser
from app.document_platform.processing.parsers.word import WordParser
from app.document_platform.processing.parsers.xml_ import XmlParser


class ParserRegistry:
    def __init__(self) -> None:
        self._by_ext: dict[str, AbstractDocumentParser] = {}
        for parser in (
            PdfParser(), WordParser(), ExcelParser(), CsvParser(),
            PowerPointParser(), JsonParser(), XmlParser(),
            TextParser(), MarkdownParser(), ImageParser(),
        ):
            self.register(parser)
        # .zip intentionally unregistered — archive expansion is a future phase

    def register(self, parser: AbstractDocumentParser) -> None:
        for ext in parser.extensions:
            self._by_ext[ext] = parser

    def get(self, extension: str) -> AbstractDocumentParser | None:
        return self._by_ext.get(extension.lower())

    @property
    def supported_extensions(self) -> list[str]:
        return sorted(self._by_ext.keys())


_registry: ParserRegistry | None = None


def get_parser_registry() -> ParserRegistry:
    global _registry
    if _registry is None:
        _registry = ParserRegistry()
    return _registry
