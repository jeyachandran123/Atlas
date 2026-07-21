"""
Transformation Engine — the LLM's JSON plan in, canonical ContentModel out.
Decides HOW data is shaped: validation, coercion, clamping, sanitization.
Deterministic; a malformed plan raises TransformationError rather than
producing a best-guess artifact.
"""
from __future__ import annotations

import re
from typing import Any

from app.document_platform.generation.content_model import (
    ContentModel,
    ContentSection,
    ContentTable,
)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

MAX_SECTIONS = 50
MAX_ROWS = 2000
MAX_COLUMNS = 50
MAX_TEXT = 20_000


class TransformationError(Exception):
    """The generation spec cannot be shaped into a valid ContentModel."""


def _clean(value: Any, limit: int = MAX_TEXT) -> str:
    return _CONTROL_CHARS.sub("", str(value)).strip()[:limit]


class TransformationEngine:
    def transform(self, spec: dict[str, Any]) -> ContentModel:
        if not isinstance(spec, dict):
            raise TransformationError("Spec must be a JSON object")
        title = _clean(spec.get("title", ""), 300)
        if not title:
            raise TransformationError("Spec is missing a title")

        raw_sections = spec.get("sections", [])
        if not isinstance(raw_sections, list) or not raw_sections:
            raise TransformationError("Spec must contain a non-empty sections list")

        sections: list[ContentSection] = []
        for raw in raw_sections[:MAX_SECTIONS]:
            if not isinstance(raw, dict):
                continue
            heading = _clean(raw.get("heading", ""), 300)
            paragraphs = [
                _clean(p) for p in raw.get("paragraphs", [])
                if isinstance(p, (str, int, float)) and _clean(p)
            ]
            bullets = [
                _clean(b) for b in raw.get("bullets", [])
                if isinstance(b, (str, int, float)) and _clean(b)
            ]
            table = self._table(raw.get("table"))
            if not heading and not paragraphs and not bullets and table is None:
                continue
            try:
                level = max(1, min(3, int(raw.get("level", 1))))
            except (TypeError, ValueError):
                level = 1
            sections.append(ContentSection(
                heading=heading or "Section",
                level=level,
                paragraphs=paragraphs,
                bullets=bullets,
                table=table,
            ))
        if not sections:
            raise TransformationError("Spec produced no usable sections")

        metadata_raw = spec.get("metadata", {})
        metadata = (
            {_clean(k, 100): _clean(v, 500) for k, v in metadata_raw.items()}
            if isinstance(metadata_raw, dict) else {}
        )
        return ContentModel(
            title=title,
            subtitle=_clean(spec.get("subtitle", ""), 500),
            sections=sections,
            metadata=metadata,
        )

    def _table(self, raw: Any) -> ContentTable | None:
        if not isinstance(raw, dict):
            return None
        headers_raw = raw.get("headers", [])
        rows_raw = raw.get("rows", [])
        if not isinstance(headers_raw, list) or not headers_raw:
            return None
        headers = [_clean(h, 200) or f"Column {i+1}"
                   for i, h in enumerate(headers_raw[:MAX_COLUMNS])]
        width = len(headers)
        rows: list[list[str]] = []
        if isinstance(rows_raw, list):
            for row in rows_raw[:MAX_ROWS]:
                if isinstance(row, list):
                    cells = [_clean(c, 2000) for c in row[:width]]
                elif isinstance(row, dict):
                    # Tolerate the common LLM drift of emitting row objects
                    # keyed by header name instead of positional arrays.
                    cells = [_clean(row.get(h, ""), 2000) for h in headers]
                else:
                    continue
                rows.append((cells + [""] * width)[:width])
        return ContentTable(name=_clean(raw.get("name", ""), 100), headers=headers, rows=rows)
