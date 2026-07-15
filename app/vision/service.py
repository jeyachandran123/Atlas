"""
Vision Service — orchestrates the vision intelligence pipeline.

This is the primary entry point for vision capabilities.
It integrates with the existing Conversation Intelligence Engine:
  - Uses the same intent detection (extended for vision)
  - Uses the same prompt composition
  - Uses the same response review/formatting
  - Routes to vision model instead of text model when images are present
"""
from __future__ import annotations

from typing import AsyncGenerator, Optional

from loguru import logger

from app.vision.image_storage import ImageStorage, get_image_storage
from app.vision.intent import VisionIntent, detect_vision_intent
from app.vision.schemas import ImageAttachment
from app.vision.vision_context import VisionContext, get_vision_context
from app.vision.vision_model import VisionModel, get_vision_model


# Vision-specific system prompt fragments per intent
_VISION_PROMPTS: dict[VisionIntent, str] = {
    VisionIntent.OCR: (
        "You are analyzing an image to extract text. "
        "Transcribe all visible text accurately, preserving formatting where possible. "
        "If the image contains a document, invoice, or form, structure the output clearly."
    ),
    VisionIntent.CODE_SCREENSHOT: (
        "You are analyzing a code screenshot. "
        "Read the code carefully, identify the programming language, explain what it does, "
        "detect any bugs or issues, and suggest improvements. "
        "Provide the corrected code if applicable."
    ),
    VisionIntent.ERROR_SCREENSHOT: (
        "You are analyzing an error/stack trace screenshot. "
        "Read the error message and stack trace carefully. "
        "Explain what caused the error and provide specific steps to fix it."
    ),
    VisionIntent.UI_ANALYSIS: (
        "You are analyzing a UI/website screenshot. "
        "Describe the layout, identify components, note any design issues, "
        "and suggest improvements. If asked, provide React/HTML implementation ideas."
    ),
    VisionIntent.DIAGRAM_ANALYSIS: (
        "You are analyzing a system architecture or diagram. "
        "Identify all components, explain their connections and data flow, "
        "and suggest possible improvements or concerns."
    ),
    VisionIntent.CHART_ANALYSIS: (
        "You are analyzing a chart, graph, or dashboard. "
        "Describe the data being shown, explain trends, "
        "and provide insights from the visualization."
    ),
    VisionIntent.DOCUMENT_ANALYSIS: (
        "You are analyzing a document or form. "
        "Extract key information, summarize the content, "
        "and answer any questions about it."
    ),
    VisionIntent.OBJECT_DETECTION: (
        "You are identifying objects in an image. "
        "Identify the main object(s), provide details about them "
        "(brand, model, type, color, etc.), and answer follow-up questions."
    ),
    VisionIntent.IMAGE_DESCRIPTION: (
        "You are describing an image in detail. "
        "Provide a comprehensive description of what you see, "
        "including objects, people, text, colors, and context."
    ),
    VisionIntent.GENERAL_VISION: (
        "You are analyzing an image provided by the user. "
        "Answer their question about the image accurately and helpfully."
    ),
}


class VisionService:
    """
    Orchestrates vision intelligence.

    Responsibilities:
    - Store uploaded images
    - Detect vision intent
    - Build vision-aware prompts
    - Route to vision model
    - Maintain image context across conversation turns
    """

    def __init__(
        self,
        storage: Optional[ImageStorage] = None,
        context: Optional[VisionContext] = None,
        model: Optional[VisionModel] = None,
    ) -> None:
        self._storage = storage or get_image_storage()
        self._context = context or get_vision_context()
        self._model = model or get_vision_model()

    async def process_upload(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        conversation_id: str,
    ) -> ImageAttachment:
        """Upload and store an image, register it in conversation context."""
        attachment = await self._storage.store(file_bytes, filename, mime_type, conversation_id)
        await self._context.add_images(conversation_id, [attachment])
        return attachment

    async def build_vision_prompt(
        self,
        message: str,
        conversation_id: str,
        system_prompt: str = "",
        session_messages: list[dict] | None = None,
    ) -> tuple[str, str, VisionIntent]:
        """
        Build the vision-aware system prompt and user prompt.

        Returns (system_prompt, user_prompt, detected_vision_intent).
        """
        # Detect vision intent
        has_images = await self._context.has_images(conversation_id)
        vision_intent, confidence = detect_vision_intent(message, has_images)

        # Build system prompt: base intelligence prompt + vision-specific addition
        vision_addition = _VISION_PROMPTS.get(vision_intent, _VISION_PROMPTS[VisionIntent.GENERAL_VISION])
        if system_prompt:
            full_system = f"{system_prompt}\n\n## Vision Analysis\n{vision_addition}"
        else:
            full_system = f"You are Atlas, an AI engineering platform.\n\n{vision_addition}"

        # Build user prompt with conversation context
        user_prompt = message
        if session_messages:
            # Include recent conversation for follow-up context
            context_lines = []
            for msg in session_messages[-6:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")[:200]
                context_lines.append(f"{role}: {content}")
            if context_lines:
                user_prompt = (
                    "Previous conversation:\n"
                    + "\n".join(context_lines)
                    + f"\n\nCurrent question: {message}"
                )

        return full_system, user_prompt, vision_intent

    async def get_image_bytes_for_conversation(
        self,
        conversation_id: str,
        new_image_bytes: list[bytes] | None = None,
    ) -> list[bytes]:
        """
        Get image bytes to send to the vision model.

        If new images are provided, use those.
        Otherwise, use the most recent images from conversation context (for follow-ups).
        """
        if new_image_bytes:
            return new_image_bytes

        # Follow-up: load most recent images from context
        recent = await self._context.get_latest_images(conversation_id, limit=3)
        if not recent:
            return []

        image_bytes = []
        for att in recent:
            try:
                data = self._storage.get_bytes(att)
                image_bytes.append(data)
            except Exception as e:
                logger.warning(f"Failed to load image {att.id}: {e}")
        return image_bytes

    async def chat(
        self,
        message: str,
        conversation_id: str,
        image_bytes: list[bytes] | None = None,
        system_prompt: str = "",
        session_messages: list[dict] | None = None,
    ) -> str:
        """Complete vision chat (non-streaming)."""
        full_system, user_prompt, intent = await self.build_vision_prompt(
            message, conversation_id, system_prompt, session_messages
        )
        images = await self.get_image_bytes_for_conversation(conversation_id, image_bytes)
        if not images:
            # No images available — shouldn't happen, but fallback gracefully
            logger.warning("Vision chat called but no images available")
            return "I don't see any images in our conversation. Please upload an image and ask your question."

        return await self._model.chat(user_prompt, full_system, images)

    async def chat_stream(
        self,
        message: str,
        conversation_id: str,
        image_bytes: list[bytes] | None = None,
        system_prompt: str = "",
        session_messages: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming vision chat."""
        full_system, user_prompt, intent = await self.build_vision_prompt(
            message, conversation_id, system_prompt, session_messages
        )
        images = await self.get_image_bytes_for_conversation(conversation_id, image_bytes)
        if not images:
            yield "I don't see any images in our conversation. Please upload an image and ask your question."
            return

        async for chunk in self._model.chat_stream(user_prompt, full_system, images):
            yield chunk

    def should_use_vision(self, has_new_images: bool, conversation_id: str) -> bool:
        """
        Determine if this request should route to the vision model.

        Called synchronously — uses cached context state.
        """
        if has_new_images:
            return True
        # Check if conversation has prior images (for follow-ups)
        cached = self._context._cache.get(conversation_id, [])
        return len(cached) > 0


# Singleton
_service: VisionService | None = None


def get_vision_service() -> VisionService:
    global _service
    if _service is None:
        _service = VisionService()
    return _service
