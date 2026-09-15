"""Does a chat message want a file made — and is there enough to make it well?

Two steps, cheapest first. A pattern gate decides whether the question is worth
asking at all, so ordinary chat never pays for an extra model call. When it
passes, the chat model decides what to do and whether it must ask first.

Asking first is the point of the second step. "Make an Excel of the anime from
the last five years" has a dozen defensible readings — Japanese only? films,
series or both? which genres? — and a model that picks one silently hands back
a confident file built on a guess. Up to three questions, each with a
recommended default, cost the user one click and remove the guess.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

FORMATS = ("pdf", "excel", "csv", "word", "markdown")
SPREADSHEET_EXTS = (".xlsx", ".xlsm", ".xls", ".csv", ".tsv")

_FILE_NOUNS = re.compile(
    r"\b(pdf|excel|xlsx|xls|csv|spreadsheet|work\s*sheet|workbook|sheet|"
    r"word\s+(?:doc|document|file)|docx|markdown|report|file|document)\b",
    re.IGNORECASE,
)
# "generate" also as it gets typed in a hurry: genarate, genearate, genrate…
_MAKE_VERBS = re.compile(
    r"\b(gen[aeiou]*r[aeiou]*t(?:e[ds]?|ing)|create|make|build|prepare|produce|export|convert|"
    r"compile|draft|write|put|turn|save|download|give|send|share|provide)\b",
    re.IGNORECASE,
)
# "…as an Excel file", "in PDF", "into a spreadsheet": a format named as the
# shape of the answer asks for a file, whatever the verb.
_AS_FORMAT = re.compile(
    r"\b(?:as|in|into|to)\s+(?:an?\s+|the\s+)?"
    r"(?:pdf|excel|xlsx|xls|csv|spreadsheet|workbook|docx|word)\b",
    re.IGNORECASE,
)
_DATA_ASK = re.compile(
    r"\?|\b(how\s+many|count|total|sum|average|mean|max(?:imum)?|min(?:imum)?|"
    r"list|filter|sort|group|which|show|find|compare|top|rows?|columns?|"
    r"unique|distinct|duplicates?|percentage|pivot|split|merge|categori[sz]e)\b",
    re.IGNORECASE,
)


# Right after a file was made, "now write phase 3", "same for chapter 2" or
# "do the next one" asks for another — with no file word in it at all.
_FOLLOW_UP = re.compile(
    r"\b(write|do|make|next|continue|same|another|again|redo|update|phase|part|chapter|section|version)\b",
    re.IGNORECASE,
)


def worth_deciding(
    message: str, *, has_spreadsheet: bool, after_clarifier: bool, after_file: bool = False,
) -> bool:
    """Should this message be looked at as a possible file request?

    Deliberately loose — a false positive costs one short model call and then
    falls back to ordinary chat; a false negative means the user asked for a
    file and got prose, or worse: a chat model that remembers making files
    but has no way to, and improvises one as JSON in the reply.
    """
    if after_clarifier:
        return True
    if after_file and _FOLLOW_UP.search(message):
        return True
    if _FILE_NOUNS.search(message) and _MAKE_VERBS.search(message):
        return True
    if _AS_FORMAT.search(message):
        return True
    return has_spreadsheet and bool(_DATA_ASK.search(message))


DECIDE_SYSTEM = """You decide whether a chat message asks for a FILE to be produced, and whether there is enough information to produce it well. Reply with ONE JSON object and nothing else.

Schema:
{
  "action": "none" | "create" | "transform" | "analyze",
  "format": "pdf" | "excel" | "csv" | "word" | "markdown",
  "source": "attachment" | "conversation" | "knowledge",
  "ready": true | false,
  "title": "short file title",
  "brief": "complete instruction for building the file (only when ready)",
  "intro": "one friendly sentence shown above the questions (only when not ready)",
  "questions": [
    {"question": "...", "options": [{"label": "...", "description": "..."}]}
  ]
}

Actions:
- none: ordinary conversation, or a question answerable in chat. No file.
- create: produce a NEW file (a PDF report, an Excel or CSV table, a Word document).
- transform: produce a new file FROM the attached spreadsheet (filter, reshape, add columns, split, summarise into a sheet). Any Excel or CSV whose rows come from an attached spreadsheet is a transform, never a create.
- analyze: answer a question by computing over the attached spreadsheet (counts, totals, lists). No file.

Source (for create):
- attachment: the content comes from the uploaded document(s).
- conversation: the content is what earlier ASSISTANT replies in this chat already said (an explanation, a plan, a list). The user's request and their answers to your questions are NOT a source — they say what to build, not what goes in it.
- knowledge: general knowledge; nothing uploaded or discussed covers it. A request answered only through your questions is still knowledge.

Format: use the one the user names. If none is named: excel for tabular data, pdf for reports and explanations.

Dates: resolve relative time ("the last five years", "this year", "recent") against TODAY'S DATE given in the message, never against what you remember as the present. Any year range you offer or write into the brief must be counted back from today's date.

Asking first:
- Set ready=false ONLY when a choice the user has not made would materially change the file: scope, filters, time range, which columns, level of detail, grouping.
- Ask about WHAT goes into the file before how it looks: inclusion criteria, origin or region, categories or sub-types, time range. Columns, layout and styling you can choose sensibly yourself — ask about them only if nothing about the content is unclear.
- Never ask about things you can reasonably infer, and never ask more than 3 questions.
- Each question has 2 or 3 options. Put the option you recommend FIRST. Do not add an "Other" option; the interface adds one.
- If the previous assistant turn asked questions and the user has now answered, you MUST set ready=true and build the brief from the original request plus their answers.

The brief (when ready=true) must stand alone: what the file is, its sections or its columns in order, filters, sorting, and every choice the user made. Write it as an instruction to the builder."""


@dataclass
class Question:
    question: str
    options: list[dict[str, str]]


@dataclass
class FilePlan:
    action: str                     # create | transform | analyze | clarify
    format: str = "pdf"
    source: str = "knowledge"       # attachment | conversation | knowledge
    title: str = ""
    brief: str = ""
    intro: str = ""
    questions: list[Question] = field(default_factory=list)


def build_user(
    message: str, history: list[str], attachments: list[str], after_clarifier: bool,
    today: str | None = None,
) -> str:
    # The model's sense of "now" is its training cutoff; without the real date,
    # "the last five years" silently becomes the wrong five years.
    parts = [f"# Today's date\n{today or date.today().isoformat()}"]
    if history:
        parts.append("# Conversation so far (oldest first)\n" + "\n".join(history))
    parts.append(
        "# Files attached in this chat\n"
        + ("\n".join(f"- {name}" for name in attachments) if attachments else "(none)")
    )
    if after_clarifier:
        parts.append("# Note\nThe user is answering the questions you asked. ready must be true.")
    parts.append(f"# Current message\n{message}")
    return "\n\n".join(parts)


_JSON = re.compile(r"\{.*\}", re.DOTALL)
_FORMAT_ALIASES = {
    "xlsx": "excel", "xls": "excel", "spreadsheet": "excel", "sheet": "excel",
    "docx": "word", "doc": "word", "md": "markdown",
}
_OTHER = re.compile(r"^\s*(other|something else|custom)\b", re.IGNORECASE)
# The interface badges the first option itself; a tag in the label would show twice.
_RECOMMENDED_TAG = re.compile(
    r"\s*[\(\[]\s*recommended\s*[\)\]]|^\s*recommended\s*[:\-–—]\s*", re.IGNORECASE,
)


def _questions(raw: Any) -> list[Question]:
    out: list[Question] = []
    if not isinstance(raw, list):
        return out
    for item in raw[:3]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question") or "").strip()
        options = []
        for opt in item.get("options") or []:
            if isinstance(opt, str):
                opt = {"label": opt}
            if not isinstance(opt, dict):
                continue
            label = _RECOMMENDED_TAG.sub("", str(opt.get("label") or "")).strip()
            if not label or _OTHER.match(label):
                continue  # the interface supplies "Other"
            options.append({
                "label": label[:80],
                "description": _RECOMMENDED_TAG.sub("", str(opt.get("description") or "")).strip()[:160],
            })
        if text and len(options) >= 2:
            out.append(Question(question=text[:200], options=options[:3]))
    return out


def parse(
    text: str, *, message: str, has_spreadsheet: bool, after_clarifier: bool,
) -> FilePlan | None:
    """The model's decision as a plan, or None to answer as ordinary chat.

    Every malformed or doubtful case resolves to None: making files is an
    addition to chat and must never be the reason a reply is lost.
    """
    raw = re.sub(r"```(?:json)?", "", text or "")
    match = _JSON.search(raw)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    action = str(data.get("action") or "none").strip().lower()
    if action not in ("create", "transform", "analyze"):
        return None
    if action in ("transform", "analyze") and not has_spreadsheet:
        if action == "analyze":
            return None
        action = "create"

    fmt = str(data.get("format") or "").strip().lower()
    fmt = _FORMAT_ALIASES.get(fmt, fmt)
    if fmt not in FORMATS:
        fmt = "excel" if action == "transform" else "pdf"

    source = str(data.get("source") or "knowledge").strip().lower()
    if source not in ("attachment", "conversation", "knowledge"):
        source = "knowledge"

    # A table made from an uploaded sheet is copied by code, never retyped by
    # the model: retyping is where rows get dropped, merged or invented.
    if action == "create" and has_spreadsheet and source == "attachment" and fmt in ("excel", "csv"):
        action = "transform"

    title = str(data.get("title") or "").strip()[:120]
    brief = str(data.get("brief") or "").strip() or message.strip()
    questions = _questions(data.get("questions"))
    ready = bool(data.get("ready", True))

    # One round of questions, never two in a row: after the user has answered,
    # a model that asks again is a loop, and the answers are enough to build.
    if not ready and questions and not after_clarifier and action != "analyze":
        return FilePlan(
            action="clarify", format=fmt, source=source, title=title,
            intro=str(data.get("intro") or "").strip()[:240], questions=questions,
        )
    return FilePlan(action=action, format=fmt, source=source, title=title, brief=brief)
