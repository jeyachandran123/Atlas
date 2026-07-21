"""JSON builder (standard library). Emits the ContentModel as a stable,
sorted-key JSON document — the machine-readable artifact format."""
from __future__ import annotations

import json

from app.document_platform.generation.builders.base import AbstractFileBuilder, BuildError
from app.document_platform.generation.content_model import ContentModel


class JsonBuilder(AbstractFileBuilder):
    format_name = "json"
    extension = "json"
    content_type = "application/json"
    features = frozenset({"structured", "machine_readable"})

    def build(self, model: ContentModel) -> bytes:
        try:
            payload = {
                "title": model.title,
                "subtitle": model.subtitle,
                "metadata": model.metadata,
                "sections": [
                    {
                        "heading": s.heading,
                        "level": s.level,
                        "paragraphs": s.paragraphs,
                        "bullets": s.bullets,
                        "table": (
                            {"name": s.table.name, "headers": s.table.headers,
                             "rows": s.table.rows}
                            if s.table is not None else None
                        ),
                    }
                    for s in model.sections
                ],
            }
            return json.dumps(
                payload, indent=2, sort_keys=True, ensure_ascii=False,
            ).encode("utf-8")
        except Exception as e:
            raise BuildError(f"JSON build failed: {e}") from e
