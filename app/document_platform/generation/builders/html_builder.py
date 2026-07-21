"""HTML builder — self-contained page, inline CSS, all content escaped."""
from __future__ import annotations

import html as _html

from app.document_platform.generation.builders.base import AbstractFileBuilder, BuildError
from app.document_platform.generation.content_model import ContentModel

_CSS = (
    "body{font-family:Segoe UI,Arial,sans-serif;max-width:860px;margin:2rem auto;"
    "padding:0 1rem;color:#1a202c;line-height:1.6}"
    "h1{border-bottom:2px solid #2d3748;padding-bottom:.3rem}"
    "table{border-collapse:collapse;width:100%;margin:1rem 0}"
    "th{background:#2d3748;color:#fff;text-align:left}"
    "th,td{border:1px solid #cbd5e0;padding:.45rem .6rem;font-size:.92rem}"
    ".meta{color:#4a5568;font-size:.9rem}"
)


class HtmlBuilder(AbstractFileBuilder):
    format_name = "html"
    extension = "html"
    content_type = "text/html"
    features = frozenset({"sections", "tables", "styling", "self_contained"})

    def build(self, model: ContentModel) -> bytes:
        try:
            e = _html.escape
            parts = [
                "<!DOCTYPE html>", "<html lang=\"en\"><head><meta charset=\"utf-8\">",
                f"<title>{e(model.title)}</title>",
                f"<style>{_CSS}</style></head><body>",
                f"<h1>{e(model.title)}</h1>",
            ]
            if model.subtitle:
                parts.append(f"<p><em>{e(model.subtitle)}</em></p>")
            if model.metadata:
                meta = " · ".join(f"<strong>{e(k)}</strong>: {e(v)}"
                                  for k, v in model.metadata.items())
                parts.append(f"<p class=\"meta\">{meta}</p>")
            for section in model.sections:
                level = max(1, min(3, section.level)) + 1
                parts.append(f"<h{level}>{e(section.heading)}</h{level}>")
                for para in section.paragraphs:
                    parts.append(f"<p>{e(para)}</p>")
                if section.bullets:
                    parts.append("<ul>")
                    parts.extend(f"<li>{e(b)}</li>" for b in section.bullets)
                    parts.append("</ul>")
                if section.table is not None:
                    t = section.table
                    parts.append("<table><thead><tr>")
                    parts.extend(f"<th>{e(h)}</th>" for h in t.headers)
                    parts.append("</tr></thead><tbody>")
                    for row in t.rows:
                        padded = (row + [""] * len(t.headers))[:len(t.headers)]
                        parts.append(
                            "<tr>" + "".join(f"<td>{e(v)}</td>" for v in padded) + "</tr>"
                        )
                    parts.append("</tbody></table>")
            parts.append("</body></html>")
            return "\n".join(parts).encode("utf-8")
        except Exception as e2:
            raise BuildError(f"HTML build failed: {e2}") from e2
