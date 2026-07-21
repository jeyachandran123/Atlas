"""PDF builder (ReportLab platypus). Deterministic: invariant document
metadata, fixed styles."""
from __future__ import annotations

import io

from app.document_platform.generation.builders.base import AbstractFileBuilder, BuildError
from app.document_platform.generation.content_model import ContentModel


class PdfBuilder(AbstractFileBuilder):
    format_name = "pdf"
    extension = "pdf"
    content_type = "application/pdf"
    features = frozenset({"sections", "tables", "styling", "paginated"})

    def build(self, model: ContentModel) -> bytes:
        try:
            from reportlab import rl_config
            rl_config.invariant = 1  # fixed CreationDate/ID — deterministic bytes
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )

            buf = io.BytesIO()
            doc = SimpleDocTemplate(
                buf, pagesize=A4,
                leftMargin=20 * mm, rightMargin=20 * mm,
                topMargin=20 * mm, bottomMargin=20 * mm,
                title=model.title, author="UnityWorks Generation Platform",
            )
            styles = getSampleStyleSheet()
            story = [Paragraph(model.title, styles["Title"])]
            if model.subtitle:
                story.append(Paragraph(model.subtitle, styles["Heading3"]))
            if model.metadata:
                meta = " · ".join(f"{k}: {v}" for k, v in model.metadata.items())
                story.append(Paragraph(meta, styles["Italic"]))
            story.append(Spacer(1, 8 * mm))

            heading_styles = {1: "Heading1", 2: "Heading2", 3: "Heading3"}
            for section in model.sections:
                style = heading_styles.get(max(1, min(3, section.level)), "Heading2")
                story.append(Paragraph(section.heading, styles[style]))
                for para in section.paragraphs:
                    story.append(Paragraph(para, styles["BodyText"]))
                for bullet in section.bullets:
                    story.append(Paragraph(f"• {bullet}", styles["BodyText"]))
                if section.table is not None:
                    data = [section.table.headers] + section.table.rows
                    table = Table(data, hAlign="LEFT")
                    table.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d3748")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]))
                    story.append(Spacer(1, 3 * mm))
                    story.append(table)
                story.append(Spacer(1, 5 * mm))

            # Invariant metadata date → identical content, identical bytes.
            doc.build(story)
            buf.seek(0)
            data = buf.getvalue()
            return data
        except BuildError:
            raise
        except Exception as e:
            raise BuildError(f"PDF build failed: {e}") from e
