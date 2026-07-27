"""Conversation export (Objective 14) — Markdown directly; PDF/Word through
the existing deterministic builders (the Generation Platform's ContentModel
is the reuse seam — no LLM involved, no new rendering logic)."""
from __future__ import annotations

import json
import re
from xml.sax.saxutils import escape as _xml_escape

from app.db.models import DipConversationTurn
from app.document_platform.generation.builders.factory import get_builder_factory
from app.document_platform.generation.content_model import ContentModel, ContentSection

EXPORT_FORMATS = {"markdown", "pdf", "word"}

# Markdown → readable plain text. Conversation answers are markdown (headings,
# bold, code, angle brackets). The frozen PdfBuilder feeds text straight into
# ReportLab's Paragraph, which parses it as mini-XML — so any `<`, unclosed
# tag, or code sample crashes the PDF build (root cause of "Export PDF fails").
# We render answers to clean plain text here, in the workspace layer, and
# XML-escape only for the PDF target — the frozen builders stay untouched.
_MD_STRIP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"```[^\n]*\n?"), ""),               # code-fence markers
    (re.compile(r"`([^`]*)`"), r"\1"),               # inline code
    (re.compile(r"\*\*([^*]+)\*\*"), r"\1"),         # bold
    (re.compile(r"__([^_]+)__"), r"\1"),             # bold (underscore)
    (re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)"), r"\1"),  # italics
    (re.compile(r"^#{1,6}\s*", re.M), ""),           # headings
    (re.compile(r"^>\s?", re.M), ""),                # blockquotes
    (re.compile(r"^\s*[-*+]\s+", re.M), "• "),       # bullets
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),   # links → text
]


def _plain(text: str | None) -> str:
    if not text:
        return ""
    for pattern, repl in _MD_STRIP:
        text = pattern.sub(repl, text)
    return text.strip()


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


def conversation_content_model(
    title: str, turns: list[DipConversationTurn], xml_safe: bool = False,
) -> ContentModel:
    """Structured, plain-text model of the conversation. When xml_safe is set
    (PDF target), heading/paragraph text is XML-escaped so ReportLab renders
    it verbatim instead of trying to parse it as markup."""
    esc = _xml_escape if xml_safe else (lambda s: s)

    sections = []
    for turn in turns:
        paragraphs = [_plain(p) for p in (turn.answer or "").split("\n\n")]
        paragraphs = [esc(p) for p in paragraphs if p]
        sections.append(ContentSection(
            heading=esc(f"Q{turn.seq}: {_plain(turn.question)[:280]}"),
            level=2,
            paragraphs=paragraphs or ["(no answer)"],
        ))
    return ContentModel(
        title=esc(title), subtitle="Conversation export",
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
    model = conversation_content_model(title, turns, xml_safe=(fmt == "pdf"))
    return builder.build(model), builder.content_type, builder.extension
