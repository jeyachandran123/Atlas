"""Markdown builder — plain string assembly, GitHub-flavored tables."""
from __future__ import annotations

from app.document_platform.generation.builders.base import AbstractFileBuilder, BuildError
from app.document_platform.generation.content_model import ContentModel


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


class MarkdownBuilder(AbstractFileBuilder):
    format_name = "markdown"
    extension = "md"
    content_type = "text/markdown"
    features = frozenset({"sections", "tables", "plain_text"})

    def build(self, model: ContentModel) -> bytes:
        try:
            lines: list[str] = [f"# {model.title}", ""]
            if model.subtitle:
                lines += [f"*{model.subtitle}*", ""]
            if model.metadata:
                lines += [" · ".join(f"**{k}**: {v}" for k, v in model.metadata.items()), ""]
            for section in model.sections:
                lines += [f"{'#' * (max(1, min(3, section.level)) + 1)} {section.heading}", ""]
                for para in section.paragraphs:
                    lines += [para, ""]
                for bullet in section.bullets:
                    lines.append(f"- {bullet}")
                if section.bullets:
                    lines.append("")
                if section.table is not None:
                    t = section.table
                    lines.append("| " + " | ".join(_escape_cell(h) for h in t.headers) + " |")
                    lines.append("|" + "---|" * len(t.headers))
                    for row in t.rows:
                        padded = (row + [""] * len(t.headers))[:len(t.headers)]
                        lines.append("| " + " | ".join(_escape_cell(v) for v in padded) + " |")
                    lines.append("")
            return "\n".join(lines).encode("utf-8")
        except Exception as e:
            raise BuildError(f"Markdown build failed: {e}") from e
