"""
Document Service — orchestrates the document intelligence pipeline.

Primary entry point for document capabilities (PDF / Word / text uploads).
Mirrors app/vision/service.py:
  - Stores uploaded documents and extracts their text at upload time
  - Maintains document context across conversation turns (Redis)
  - Builds document-aware prompts within a character budget
  - Streams answers via the standard text LLM (OllamaClient)
"""
from __future__ import annotations

from typing import AsyncGenerator, Optional

from loguru import logger

from app.config import get_settings
from app.documents.context import DocumentContext, get_document_context
from app.documents.extractor import DocumentExtractionError, extract_text
from app.documents.schemas import DocumentAttachment
from app.documents.storage import DocumentStorage, DocumentStorageError, get_document_storage
from app.ollama_client import OllamaClient, get_ollama_client

_cfg = get_settings()


_DOCUMENT_SYSTEM_ADDITION = (
    "## Document Analysis\n"
    "The user uploaded document(s) and their FULL EXTRACTED TEXT is included in the "
    "user message under '## Uploaded Documents'. You HAVE direct access to this "
    "content — it is right there in the message. NEVER say you cannot access, open, "
    "or read files, and never ask the user to paste the content.\n"
    "- If the user says 'read this', 'open this', 'check this file', or similar, "
    "respond with a clear structured summary of the document's content.\n"
    "- For specific questions, answer from the document text, quoting passages "
    "(and page numbers when available) to support your answers.\n"
    "- If the answer is not present in the provided text, say so clearly instead of guessing.\n"
    "- If a document was truncated, mention that your answer covers the included portion."
)


class DocumentService:
    """
    Orchestrates document upload, extraction, context, and Q&A streaming.
    """

    def __init__(
        self,
        storage: Optional[DocumentStorage] = None,
        context: Optional[DocumentContext] = None,
        ollama: Optional[OllamaClient] = None,
    ) -> None:
        self._storage = storage or get_document_storage()
        self._context = context or get_document_context()
        self._ollama = ollama or get_ollama_client()

    # ── Upload ────────────────────────────────────────────────────────────────

    async def process_upload(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        conversation_id: str,
    ) -> DocumentAttachment:
        """
        Extract text, store the document, and register it in conversation context.

        Raises DocumentExtractionError / DocumentStorageError on failure.
        """
        extracted = extract_text(file_bytes, filename)
        attachment = await self._storage.store(
            file_bytes=file_bytes,
            extracted_text=extracted.text,
            filename=filename,
            mime_type=mime_type,
            conversation_id=conversation_id,
            page_count=extracted.page_count,
        )
        await self._context.add_documents(conversation_id, [attachment])
        logger.info(
            f"Document uploaded: {filename} ({attachment.char_count} chars, "
            f"pages={attachment.page_count}) → conversation {conversation_id}"
        )
        return attachment

    # ── Context ───────────────────────────────────────────────────────────────

    async def has_documents(self, conversation_id: str) -> bool:
        return await self._context.has_documents(conversation_id)

    async def rehydrate(
        self, conversation_id: str, attachments: list[DocumentAttachment]
    ) -> None:
        """
        Re-register documents into the (possibly expired) Redis context —
        used when metadata is loaded back from the database.
        """
        if attachments:
            await self._context.add_documents(conversation_id, attachments)

    async def _get_text_cached(self, doc: DocumentAttachment) -> str:
        """
        Extracted text with a Redis cache (1h TTL).

        The document block is rebuilt on EVERY doc-chat turn — without this,
        a cloud storage backend would re-download each document per message.
        """
        cache_key = f"docs:text:{doc.id}"
        try:
            from app.redis_client import get_redis
            cached = await get_redis().get(cache_key)
            if cached:
                return cached.decode("utf-8") if isinstance(cached, bytes) else cached
        except Exception:
            pass

        text = await self._storage.get_text(doc)

        try:
            from app.redis_client import get_redis
            await get_redis().set(cache_key, text, ex=3600)
        except Exception:
            pass
        return text

    async def build_document_block(
        self,
        conversation_id: str,
        max_chars: Optional[int] = None,
        max_docs: int = 5,
    ) -> str:
        """
        Build the '## Uploaded Documents' prompt block within a character budget.

        The budget is split evenly across the most recent documents; each
        document is truncated to its share with an explicit truncation notice.
        """
        budget = max_chars or _cfg.document_context_max_chars
        docs = await self._context.get_latest_documents(conversation_id, limit=max_docs)
        if not docs:
            return ""

        per_doc_budget = max(budget // len(docs), 1000)
        sections: list[str] = []
        for doc in docs:
            try:
                text = await self._get_text_cached(doc)
            except DocumentStorageError as e:
                logger.warning(f"Failed to load document text {doc.id}: {e}")
                continue

            header = f"### Document: {doc.filename}"
            if doc.page_count:
                header += f" ({doc.page_count} pages)"

            if len(text) > per_doc_budget:
                text = (
                    text[:per_doc_budget]
                    + f"\n\n[... document truncated — showing first "
                    f"{per_doc_budget} of {len(text)} characters ...]"
                )
            sections.append(f"{header}\n{text}")

        if not sections:
            return ""
        return "## Uploaded Documents\n\n" + "\n\n---\n\n".join(sections)

    # ── Prompt building ───────────────────────────────────────────────────────

    async def build_document_prompt(
        self,
        message: str,
        conversation_id: str,
        system_prompt: str = "",
        session_messages: list[dict] | None = None,
    ) -> tuple[str, str]:
        """
        Build the document-aware (system_prompt, user_prompt) pair.
        """
        base = system_prompt or "You are Atlas, an AI engineering platform."
        full_system = f"{base}\n\n{_DOCUMENT_SYSTEM_ADDITION}"

        doc_block = await self.build_document_block(conversation_id)

        parts: list[str] = []
        if doc_block:
            parts.append(doc_block)

        if session_messages:
            context_lines = []
            for msg in session_messages[-6:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")[:300]
                context_lines.append(f"{role}: {content}")
            if context_lines:
                parts.append("## Previous Conversation\n" + "\n".join(context_lines))

        parts.append(
            f"## User Request\n{message}\n\n"
            "(The document text you need is provided above under '## Uploaded Documents'. "
            "Answer directly from it.)"
        )
        return full_system, "\n\n".join(parts)

    # ── Chat ──────────────────────────────────────────────────────────────────

    def _get_model(self, agent_mode: str) -> str:
        """Same mode → model mapping as CodingAgent."""
        return {
            "code":     _cfg.ollama_chat_model,
            "auto":     _cfg.ollama_auto_model,
            "business": _cfg.ollama_business_model,
        }.get(agent_mode, _cfg.ollama_auto_model)

    async def chat_stream(
        self,
        message: str,
        conversation_id: str,
        system_prompt: str = "",
        session_messages: list[dict] | None = None,
        agent_mode: str = "auto",
    ) -> AsyncGenerator[str, None]:
        """Streaming document Q&A via the standard text LLM."""
        full_system, user_prompt = await self.build_document_prompt(
            message, conversation_id, system_prompt, session_messages
        )
        if "## Uploaded Documents" not in user_prompt:
            yield (
                "I don't see any documents in our conversation. "
                "Please upload a PDF, Word, or text file and ask your question."
            )
            return

        async for chunk in self._ollama.chat_stream(
            prompt=user_prompt,
            system_prompt=full_system,
            model=self._get_model(agent_mode),
            temperature=_cfg.ollama_chat_temperature,
        ):
            yield chunk


# Singleton
_service: DocumentService | None = None


def get_document_service() -> DocumentService:
    global _service
    if _service is None:
        _service = DocumentService()
    return _service
