"""Making files from chat — orchestration over platforms that already exist.

Nothing here builds a file. ``GenerationGateway`` plans and renders PDFs, Word
documents and spreadsheets; ``DocumentTaskGateway`` writes and runs code over an
uploaded spreadsheet; both store the result in blob storage as an artifact that
``/generations/{id}/download`` serves. This module decides which of them a chat
turn needs, hands it the right source, and turns what it reports into chat
events.

Replies that are not prose — a set of questions, a file — are stored on the
assistant message as JSON with a distinct ``agent_used``, so the chat renders
them as cards and they come back intact after a reload.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, AsyncIterator

from loguru import logger
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat_artifacts.decision import (
    DECIDE_SYSTEM,
    SPREADSHEET_EXTS,
    FilePlan,
    build_user,
    parse,
    worth_deciding,
)
from app.chat_artifacts.digest import describe
from app.chat_artifacts.review import make_table_review
from app.db.models import Message, MessageDocument

CLARIFIER = "clarifier"
FILE_ARTIFACT = "file_artifact"
DATA_AGENT = "data_agent"

_CONTEXT_CHARS = 24_000
_HISTORY_TURNS = 12

_KNOWLEDGE_RULE = (
    "\n\nThere is no source document: use general knowledge only. Every entry "
    "must be real — never invent a title, name, date or number to fill a table. "
    "When the request asks for a number of entries (\"top 50\"), deliver that "
    "many: a well-known subject — dishes, places, films, companies — has far "
    "more real entries than that, so stopping short is a failure, not caution. "
    "If one value in a row is uncertain, write 'Unknown' in that cell rather "
    "than dropping the row. Give fewer rows only when the subject truly does "
    "not have that many real entries, and then say so in the subtitle. "
    "Every row must be different: never repeat an entry. A list written from "
    "memory is a selection, not a complete record — say so plainly in the "
    "subtitle, and if your knowledge does not reach the end of the requested "
    "period, say that too instead of filling the gap."
)

_SOURCE_RULE = (
    "\n\nThe SOURCES are the user's material. Cover every part of it — each "
    "section, phase, theory or item, in its order. When the user asks for it to "
    "be explained, do not copy it: explain each part in your own words — what "
    "it says, what it means, why it matters and how it connects to the other "
    "parts — so the file teaches more than the source does. Every claim, name "
    "and number must still come from the SOURCES; add no new ones."
)

_TASK_FORMATS = {"excel": "xlsx", "csv": "csv", "pdf": "pdf", "word": "docx", "markdown": "md"}

OVERVIEW_SYSTEM = """You write the short note delivered together with a file you just created for the user. It is the first thing they read, so it should make the file's value obvious at a glance.

Use ONLY facts found in FILE CONTENTS — names, counts, columns, sections, ranges. Never invent or estimate a fact, and never describe what the file "should" contain.

FILE CONTENTS is a description prepared for you by reading the saved file — it is not the file itself. Its wording, punctuation and layout are not in the file, so never comment on headers, delimiters, encoding or formatting.

Write Markdown in exactly this shape, under 170 words, with no preamble and no sign-off:

**<one sentence: what the file is and what it lets the user do>**

**What's inside**
- 2 to 4 bullets with concrete specifics: sheet or section names, row counts, columns, the range the data covers

**Good to know**
- one bullet, ONLY when SOURCE is general knowledge (say the entries come from general knowledge and key facts are worth checking) or when the contents themselves state a limitation. Otherwise leave this whole section out.

**Take it further**
- 2 or 3 short, specific follow-ups you can actually do for them in this chat: change this file (add or remove columns, filter, sort), turn it into another format (PDF, Excel, CSV or Word), or explain something in it. Never suggest charts, images, dashboards or anything else. Write them as requests, e.g. "Add a column for …", "Turn this into a PDF report\""""


def _polish(summary: str) -> str:
    """The saved overview, with its one-line headline made bold if the model left it plain."""
    lines = summary.strip().splitlines()
    if lines and lines[0].strip() and not lines[0].lstrip().startswith(("**", "#", "-")):
        lines[0] = f"**{lines[0].strip()}**"
    return "\n".join(lines)

_SOURCE_LABEL = {
    "knowledge": "general knowledge (no document was used)",
    "conversation": "this conversation",
    "attachment": "the user's attached file",
}


def session_text(content: str, agent_used: str) -> str:
    """How a structured reply reads in short-term memory and history."""
    if agent_used not in (CLARIFIER, FILE_ARTIFACT):
        return content
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content
    if agent_used == CLARIFIER:
        asked = "; ".join(q.get("question", "") for q in data.get("questions", []))
        return f"(Asked before building the file: {asked})"
    if data.get("status") == "ready":
        return f"(Created the file {data.get('filename')} — {data.get('title')})"
    return f"(Could not create the file: {data.get('error') or 'unknown error'})"


def _history_line(m: Message) -> str:
    role = "User" if m.role == "user" else "Assistant"
    text = " ".join(session_text(m.content or "", m.agent_used or "").split())
    return f"{role}: {text[:700]}"


def _parse_frame(frame: str) -> tuple[str, dict[str, Any]]:
    event, data = "", {}
    for line in frame.split("\n"):
        if line.startswith("event: "):
            event = line[7:].strip()
        elif line.startswith("data: "):
            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                pass
    return event, data


def _final(content: str, agent_used: str) -> dict[str, Any]:
    return {"type": "_final", "content": content, "agent_used": agent_used}


def _text_reply(text: str) -> list[dict[str, Any]]:
    chunks = [{"type": "token", "content": text[i:i + 48]} for i in range(0, len(text), 48)]
    return [*chunks, _final(text, DATA_AGENT)]


class ChatFileService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── context ───────────────────────────────────────────────────────────────

    async def _history(self, conversation_id: str, limit: int = _HISTORY_TURNS) -> list[Message]:
        rows = (await self._db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(desc(Message.created_at))
            .limit(limit + 1)
        )).scalars().all()
        return list(reversed(rows))

    async def _attachments(self, conversation_id: str) -> list[MessageDocument]:
        return list((await self._db.execute(
            select(MessageDocument)
            .where(MessageDocument.conversation_id == conversation_id)
            .order_by(MessageDocument.created_at)
        )).scalars().all())

    async def _attachment_text(self, conversation_id: str) -> str | None:
        from app.documents.service import get_document_service

        try:
            block = await get_document_service().build_document_block(
                conversation_id, max_chars=_CONTEXT_CHARS,
            )
        except Exception as e:  # noqa: BLE001 - fall back to no source
            logger.warning(f"Could not read attachments for a file request: {e}")
            return None
        if isinstance(block, (tuple, list)):
            block = next((b for b in block if isinstance(b, str) and b.strip()), "")
        text = block if isinstance(block, str) else ""
        return text.strip() or None

    async def _conversation_text(self, conversation_id: str) -> str | None:
        """What was discussed in this chat, or None when nothing was.

        A request and the answers to our own questions are not a source: they
        say what to build, not what goes in it. Treating them as one would
        ground the file on nothing — and skip the checks a file written from
        general knowledge gets.
        """
        history = [m for m in await self._history(conversation_id, limit=40)
                   if m.agent_used not in (CLARIFIER, FILE_ARTIFACT)]
        if not any(m.role == "assistant" and (m.content or "").strip() for m in history):
            return None
        lines = []
        for m in history:
            role = "User" if m.role == "user" else "Assistant"
            lines.append(f"{role}: {(m.content or '').strip()[:4000]}")
        text = "\n\n".join(lines)
        return text[-_CONTEXT_CHARS:].strip() or None

    # ── decide ────────────────────────────────────────────────────────────────

    async def decide(self, *, conversation_id: str, message: str) -> FilePlan | None:
        history = await self._history(conversation_id)
        # The current message has already been saved as the newest row.
        if history and history[-1].role == "user" and (history[-1].content or "").strip() == message.strip():
            history = history[:-1]
        after_clarifier = (
            bool(history) and history[-1].role == "assistant"
            and history[-1].agent_used == CLARIFIER
        )
        # A file made in the last couple of turns makes a follow-up likely to want the next one.
        after_file = any(
            m.role == "assistant" and m.agent_used == FILE_ARTIFACT for m in history[-4:]
        )
        attachments = await self._attachments(conversation_id)
        has_sheet = any(a.filename.lower().endswith(SPREADSHEET_EXTS) for a in attachments)
        if not worth_deciding(
            message, has_spreadsheet=has_sheet, after_clarifier=after_clarifier, after_file=after_file,
        ):
            return None

        from app.llm import GENERAL, LLMGatewayError, get_chat_gateway

        prompt = build_user(
            message, [_history_line(m) for m in history],
            [a.filename for a in attachments], after_clarifier,
        )
        try:
            result = await get_chat_gateway().complete(
                user=prompt, system=DECIDE_SYSTEM, profile=GENERAL,
                thinking=False, temperature=0.1, max_tokens=1500,
            )
        except LLMGatewayError as e:
            logger.warning(f"File decision unavailable ({e}); answering as chat")
            return None
        plan = parse(result.text, message=message, has_spreadsheet=has_sheet,
                     after_clarifier=after_clarifier)
        if plan is not None:
            logger.info(
                f"Chat file request: action={plan.action} format={plan.format} "
                f"source={plan.source} questions={len(plan.questions)}"
            )
        return plan

    # ── run ───────────────────────────────────────────────────────────────────

    async def run(
        self, plan: FilePlan, *, conversation_id: str, user_id: str, org_id: str, message: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Chat events for this plan, ending with one ``_final`` to persist."""
        if plan.action == "clarify":
            payload = {
                "kind": "clarify",
                "intro": plan.intro or "A few quick choices so the file comes out right:",
                "questions": [{"question": q.question, "options": q.options} for q in plan.questions],
                "format": plan.format,
            }
            yield {"type": "clarify", **payload}
            yield _final(json.dumps(payload), CLARIFIER)
            return

        if plan.action in ("transform", "analyze"):
            async for event in self._run_task(
                plan, conversation_id=conversation_id, user_id=user_id,
                org_id=org_id, message=message,
            ):
                yield event
            return

        async for event in self._run_generation(
            plan, conversation_id=conversation_id, user_id=user_id, org_id=org_id,
        ):
            yield event

    async def _run_generation(
        self, plan: FilePlan, *, conversation_id: str, user_id: str, org_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        from app.document_platform.generation.gateway import GenerationGateway

        context = None
        if plan.source == "attachment":
            context = await self._attachment_text(conversation_id)
        elif plan.source == "conversation":
            context = await self._conversation_text(conversation_id)
        source_used = plan.source if context else "knowledge"

        brief = plan.brief + (_SOURCE_RULE if context else _KNOWLEDGE_RULE)
        if plan.title and plan.title.lower() not in brief.lower():
            brief = f"Title: {plan.title}\n{brief}"
        brief = f"Today's date: {date.today().isoformat()}.\n{brief}"

        # A table written from memory gets checked against its own brief; one
        # built from the user's material is already bound to that material.
        review = make_table_review(brief) if not context and plan.format in ("excel", "csv") else None

        yield {"type": "file_stage", "stage": "planning", "format": plan.format}
        done: dict[str, Any] = {}
        artifact_id = None
        async for frame in GenerationGateway(self._db).generate_stream(
            user_id, org_id, brief, plan.format, None, context_text=context,
            spec_review=review,
        ):
            event, data = _parse_frame(frame)
            if event == "meta":
                artifact_id = data.get("artifact_id", artifact_id)
            elif event == "stage":
                yield {"type": "file_stage", "stage": data.get("stage"), "format": plan.format}
            elif event == "done":
                done = data
            elif event == "error":
                done = {"status": "failed", "error": data.get("message")}

        card = {
            "kind": "file",
            "artifact_id": done.get("artifact_id") or artifact_id,
            "title": done.get("title") or plan.title,
            "filename": done.get("filename"),
            "format": done.get("format") or plan.format,
            "size_bytes": done.get("size_bytes") or 0,
            "status": done.get("status") or "failed",
            "error": done.get("error"),
            "source": source_used,
        }
        async for event in self._deliver(card, user_id=user_id, request=plan.brief):
            yield event

    # ── delivering a file ─────────────────────────────────────────────────────

    async def _deliver(
        self, card: dict[str, Any], *, user_id: str, request: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """The file card at once, then its overview as it is written, then the message to save."""
        yield {"type": "file", **card}
        if card.get("status") == "ready" and card.get("artifact_id"):
            parts: list[str] = []
            async for chunk in self._overview(card, user_id=user_id, request=request):
                parts.append(chunk)
                yield {"type": "token", "content": chunk}
            card["summary"] = _polish("".join(parts)) or None
        yield _final(json.dumps(card), FILE_ARTIFACT)

    async def _overview(
        self, card: dict[str, Any], *, user_id: str, request: str,
    ) -> AsyncIterator[str]:
        """A short note on what the file holds, written from the file read back.

        Best effort by design: the file is already made and saved, so a note
        that cannot be written is simply left out — it never costs the file.
        """
        from app.document_platform.generation.gateway import STORAGE_PREFIX
        from app.document_platform.generation.repository import GenerationRepository
        from app.llm import GENERAL, get_chat_gateway
        from app.storage import get_blob_storage

        try:
            artifact = await GenerationRepository(self._db).get_artifact(card["artifact_id"], user_id)
            if artifact is None:
                return
            data = await get_blob_storage(STORAGE_PREFIX).get(artifact.storage_key)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"File overview skipped — could not read the file back: {e}")
            return

        source = _SOURCE_LABEL.get(str(card.get("source") or ""), "general knowledge")
        if card.get("based_on"):
            source = f"the user's attached file {card['based_on']}"
        user = (
            f"# FILE\nTitle: {card.get('title') or artifact.title}\n"
            f"Format: {card.get('format')}\nFile name: {artifact.filename}\n"
            f"SOURCE: {source}\nRequest it was made for: {' '.join(request.split())[:800]}\n\n"
            f"# FILE CONTENTS (read back from the saved file)\n{describe(data, str(card.get('format') or ''))}"
        )
        call = dict(user=user, system=OVERVIEW_SYSTEM, profile=GENERAL,
                    thinking=False, temperature=0.3, max_tokens=600)
        gateway = get_chat_gateway()
        streamed = False
        try:
            async for event in gateway.stream(**call):
                if event.kind == "content" and event.text:
                    streamed = True
                    yield event.text
        except Exception as e:  # noqa: BLE001
            if streamed:
                # Half a note is already on screen; a second one would repeat it.
                logger.warning(f"File overview cut short: {e}")
                return
            logger.warning(f"File overview stream unavailable ({e}); trying once without streaming")
        if streamed:
            return
        # A provider can refuse a stream it would answer whole ("temporarily
        # overloaded" on the stream alone), so the note gets one plain try.
        try:
            result = await gateway.complete(**call)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"File overview unavailable: {e}")
            return
        if result.text:
            yield result.text

    async def _run_task(
        self, plan: FilePlan, *, conversation_id: str, user_id: str, org_id: str, message: str,
    ) -> AsyncIterator[dict[str, Any]]:
        from app.document_platform.execution.gateway import DocumentTaskGateway
        from app.document_platform.generation.repository import GenerationRepository
        from app.documents.storage import get_document_storage

        sheets = [a for a in await self._attachments(conversation_id)
                  if a.filename.lower().endswith(SPREADSHEET_EXTS)]
        if not sheets:
            for event in _text_reply("I can't find a spreadsheet in this chat to work on."):
                yield event
            return
        sheet = sheets[-1]
        try:
            data = await get_document_storage().get_bytes(sheet.storage_path)
        except Exception as e:  # noqa: BLE001
            for event in _text_reply(f"I couldn't open {sheet.filename} ({type(e).__name__})."):
                yield event
            return

        if plan.action == "analyze":
            request = (
                f"{message}\n\nAnswer this question about the file. Compute the answer "
                "over every row and print() it as a short, readable sentence. "
                "Do NOT write any output file."
            )
            requested_format = None
        else:
            # The task names its file after the request's first line.
            request = f"{plan.title}\n{plan.brief}" if plan.title else plan.brief
            requested_format = _TASK_FORMATS.get(plan.format, "xlsx")

        yield {"type": "file_stage", "stage": "inspecting_document", "format": plan.format}
        artifact_id = None
        async for kind, payload in DocumentTaskGateway(self._db).run_stream(
            user_id=user_id, org_id=org_id, document_id=None, filename=sheet.filename,
            data=data, request=request, requested_format=requested_format,
        ):
            if kind == "meta":
                artifact_id = payload.get("artifact_id")
            elif kind == "stage":
                yield {"type": "file_stage", "stage": payload.get("stage"), "format": plan.format}
            elif kind == "error":
                await self._db.commit()
                for event in _text_reply(
                    f"I couldn't complete that on {sheet.filename}: {payload.get('message')}"
                ):
                    yield event
                return
            elif kind == "done":
                await self._db.commit()
                if payload.get("kind") == "answer":
                    answer = (payload.get("answer") or "").strip() or (
                        "The computation finished but printed nothing."
                    )
                    for event in _text_reply(answer):
                        yield event
                    return
                artifact = None
                if artifact_id:
                    artifact = await GenerationRepository(self._db).get_artifact(artifact_id, user_id)
                card = {
                    "kind": "file",
                    "artifact_id": artifact_id,
                    "title": (artifact.title if artifact else None) or plan.title or "Result",
                    "filename": (artifact.filename if artifact else None) or payload.get("filename"),
                    "format": plan.format,
                    "size_bytes": (artifact.size_bytes if artifact else None) or payload.get("size_bytes") or 0,
                    "status": (artifact.status if artifact else None) or "ready",
                    "error": None,
                    "source": "attachment",
                    "based_on": sheet.filename,
                }
                async for event in self._deliver(card, user_id=user_id, request=request):
                    yield event
                return
        for event in _text_reply("The task ended without a result."):
            yield event
