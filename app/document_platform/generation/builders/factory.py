"""File Builder Factory — format name → builder instance. A future
PowerPoint/Email/Google-Docs builder is one class + one entry here."""
from __future__ import annotations

from app.document_platform.generation.builders.base import AbstractFileBuilder
from app.document_platform.generation.builders.csv_builder import CsvBuilder
from app.document_platform.generation.builders.excel import ExcelBuilder
from app.document_platform.generation.builders.html_builder import HtmlBuilder
from app.document_platform.generation.builders.json_builder import JsonBuilder
from app.document_platform.generation.builders.markdown import MarkdownBuilder
from app.document_platform.generation.builders.pdf import PdfBuilder
from app.document_platform.generation.builders.word import WordBuilder


class UnknownFormatError(ValueError):
    """Requested output format has no registered builder."""


class FileBuilderFactory:
    def __init__(self) -> None:
        self._builders: dict[str, AbstractFileBuilder] = {}
        for builder in (
            ExcelBuilder(), PdfBuilder(), WordBuilder(), CsvBuilder(),
            JsonBuilder(), MarkdownBuilder(), HtmlBuilder(),
        ):
            self.register(builder)

    def register(self, builder: AbstractFileBuilder) -> None:
        self._builders[builder.format_name] = builder

    def get(self, format_name: str) -> AbstractFileBuilder:
        builder = self._builders.get(format_name)
        if builder is None:
            raise UnknownFormatError(
                f"No builder for format '{format_name}'. "
                f"Supported: {', '.join(sorted(self._builders))}"
            )
        return builder

    def supported_formats(self) -> list[str]:
        return sorted(self._builders)

    def all(self) -> list[AbstractFileBuilder]:
        return [self._builders[k] for k in sorted(self._builders)]


_factory: FileBuilderFactory | None = None


def get_builder_factory() -> FileBuilderFactory:
    global _factory
    if _factory is None:
        _factory = FileBuilderFactory()
    return _factory
