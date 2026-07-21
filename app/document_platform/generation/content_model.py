"""
The canonical Content Model — the single contract between the Transformation
Engine and every builder. Pure data, no logic. A builder that consumes this
model and nothing else is automatically independent of every other builder,
of the LLM, and of where the content came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContentTable:
    name: str
    headers: list[str]
    rows: list[list[str]]


@dataclass(frozen=True)
class ContentSection:
    heading: str
    level: int = 1                   # 1..3
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    table: ContentTable | None = None


@dataclass(frozen=True)
class ContentModel:
    title: str
    subtitle: str = ""
    sections: list[ContentSection] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def tables(self) -> list[ContentTable]:
        return [s.table for s in self.sections if s.table is not None]
