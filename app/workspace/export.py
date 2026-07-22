"""Conversation export (Objective 14) — Markdown directly; PDF/Word through
the existing deterministic builders (the Generation Platform's ContentModel
is the reuse seam — no LLM involved, no new rendering logic)."""
from __future__ import annotations

import json

from app.db.models import DipConversationTurn
from app.document_platform.generation.builders.factory import get_builder_factory
from app.document_platform.generation.content_model import ContentModel, ContentSection

EXPORT_FORMATS = {"markdown", "pdf", "word"}


def conversation_markdown(title: str, turns: list[DipConversationTurn]) -> str:
    lines = [f"# {title}", ""]
    for turn in turns:
        lines += [f"## Q{turn.seq}: {turn.question}", ""]
        if turn.answer:
            lines += [turn.answer, ""]
        if turn.citations_json:
            try:
                citations = json.loads(turn.citations_json)
                if citations:
                    refs = ", ".join(
                        f"{c.get('source_id', '?')} (doc {str(c.get('document_id', ''))[:8]}…"
                        + (f", p.{c['page']}" if c.get("page") is not None else "") + ")"
                        for c in citations
                    )
                    lines += [f"*Sources: {refs}*", ""]
            except (json.JSONDecodeError, TypeError):
                pass
    return "\n".join(lines)


def conversation_content_model(title: str, turns: list[DipConversationTurn]) -> ContentModel:
    sections = []
    for turn in turns:
        paragraphs = [p for p in (turn.answer or "").split("\n\n") if p.strip()]
        sections.append(ContentSection(
            heading=f"Q{turn.seq}: {turn.question[:280]}",
            level=2,
            paragraphs=paragraphs or ["(no answer)"],
        ))
    return ContentModel(
        title=title, subtitle="Conversation export",
        sections=sections or [ContentSection(heading="Empty conversation", level=2)],
        metadata={"Turns": str(len(turns))},
    )


def export_conversation(
    title: str, turns: list[DipConversationTurn], fmt: str,
) -> tuple[bytes, str, str]:
    """Returns (bytes, content_type, filename_extension)."""
    if fmt == "markdown":
        return conversation_markdown(title, turns).encode("utf-8"), "text/markdown", "md"
    builder = get_builder_factory().get({"pdf": "pdf", "word": "word"}[fmt])
    model = conversation_content_model(title, turns)
    return builder.build(model), builder.content_type, builder.extension
