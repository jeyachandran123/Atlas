"""
Vision Intelligence Tests.

Covers:
- Image storage (upload, retrieve, delete)
- Vision intent detection
- Vision context (conversation image tracking)
- Vision service orchestration
- API endpoint (multipart upload)
"""
import hashlib
import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.vision.image_storage import ImageStorage, ImageStorageError, ALLOWED_MIME_TYPES
from app.vision.intent import detect_vision_intent, VisionIntent
from app.vision.schemas import ImageAttachment
from app.vision.vision_context import VisionContext
from app.vision.service import VisionService


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_storage(tmp_path):
    return ImageStorage(storage_dir=tmp_path)


@pytest.fixture
def sample_png():
    """Minimal valid PNG (1x1 pixel, red)."""
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
        b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
        b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


# ── Image Storage Tests ───────────────────────────────────────────────────────

class TestImageStorage:

    @pytest.mark.asyncio
    async def test_store_valid_image(self, tmp_storage, sample_png):
        att = await tmp_storage.store(
            file_bytes=sample_png,
            filename="test.png",
            mime_type="image/png",
            conversation_id="conv-123",
        )
        assert att.id
        assert att.conversation_id == "conv-123"
        assert att.filename == "test.png"
        assert att.mime_type == "image/png"
        assert att.size_bytes == len(sample_png)
        assert att.image_hash == hashlib.sha256(sample_png).hexdigest()

    @pytest.mark.asyncio
    async def test_store_rejects_invalid_mime(self, tmp_storage):
        with pytest.raises(ImageStorageError, match="Unsupported"):
            await tmp_storage.store(b"data", "test.exe", "application/exe", "conv-1")

    @pytest.mark.asyncio
    async def test_store_rejects_oversized(self, tmp_storage):
        huge = b"x" * (21 * 1024 * 1024)
        with pytest.raises(ImageStorageError, match="too large"):
            await tmp_storage.store(huge, "big.png", "image/png", "conv-1")

    @pytest.mark.asyncio
    async def test_get_bytes(self, tmp_storage, sample_png):
        att = await tmp_storage.store(sample_png, "test.png", "image/png", "conv-1")
        retrieved = tmp_storage.get_bytes(att)
        assert retrieved == sample_png

    @pytest.mark.asyncio
    async def test_delete(self, tmp_storage, sample_png):
        att = await tmp_storage.store(sample_png, "test.png", "image/png", "conv-1")
        tmp_storage.delete(att)
        with pytest.raises(ImageStorageError):
            tmp_storage.get_bytes(att)

    def test_png_dimensions(self, tmp_storage, sample_png):
        w, h = tmp_storage._get_dimensions(sample_png)
        assert w == 1
        assert h == 1


# ── Vision Intent Detection Tests ─────────────────────────────────────────────

class TestVisionIntent:

    def test_ocr_intent(self):
        intent, conf = detect_vision_intent("extract text from this image", True)
        assert intent == VisionIntent.OCR
        assert conf > 0.3

    def test_code_screenshot_intent(self):
        intent, conf = detect_vision_intent("what's wrong with this code?", True)
        assert intent == VisionIntent.CODE_SCREENSHOT

    def test_error_screenshot_intent(self):
        intent, conf = detect_vision_intent("fix this error please", True)
        assert intent == VisionIntent.ERROR_SCREENSHOT

    def test_ui_analysis_intent(self):
        intent, conf = detect_vision_intent("analyze this website layout", True)
        assert intent == VisionIntent.UI_ANALYSIS

    def test_diagram_intent(self):
        intent, conf = detect_vision_intent("explain this architecture diagram", True)
        assert intent == VisionIntent.DIAGRAM_ANALYSIS

    def test_chart_intent(self):
        intent, conf = detect_vision_intent("what does this chart show?", True)
        assert intent == VisionIntent.CHART_ANALYSIS

    def test_object_detection_intent(self):
        intent, conf = detect_vision_intent("what phone is this?", True)
        assert intent == VisionIntent.OBJECT_DETECTION

    def test_description_intent(self):
        intent, conf = detect_vision_intent("describe this image", True)
        assert intent == VisionIntent.IMAGE_DESCRIPTION

    def test_general_vision_fallback(self):
        intent, conf = detect_vision_intent("hello", True)
        assert intent == VisionIntent.GENERAL_VISION

    def test_no_images_returns_zero_confidence(self):
        intent, conf = detect_vision_intent("describe this", False)
        assert conf == 0.0


# ── Vision Context Tests ──────────────────────────────────────────────────────

class TestVisionContext:

    @pytest.mark.asyncio
    async def test_add_and_get_images(self):
        ctx = VisionContext()
        att = ImageAttachment(
            id="img-1", conversation_id="conv-1", filename="test.png",
            mime_type="image/png", size_bytes=100, storage_path="conv-1/img-1.png",
            image_hash="abc123",
        )
        await ctx.add_images("conv-1", [att])
        images = await ctx.get_images("conv-1")
        assert len(images) == 1
        assert images[0].id == "img-1"

    @pytest.mark.asyncio
    async def test_has_images(self):
        ctx = VisionContext()
        assert not await ctx.has_images("conv-empty")
        att = ImageAttachment(
            id="img-2", conversation_id="conv-2", filename="x.png",
            mime_type="image/png", size_bytes=50, storage_path="conv-2/img-2.png",
            image_hash="def456",
        )
        await ctx.add_images("conv-2", [att])
        assert await ctx.has_images("conv-2")

    @pytest.mark.asyncio
    async def test_get_latest_images_limit(self):
        ctx = VisionContext()
        atts = [
            ImageAttachment(
                id=f"img-{i}", conversation_id="conv-3", filename=f"{i}.png",
                mime_type="image/png", size_bytes=10, storage_path=f"conv-3/{i}.png",
                image_hash=f"hash{i}",
            )
            for i in range(10)
        ]
        await ctx.add_images("conv-3", atts)
        latest = await ctx.get_latest_images("conv-3", limit=3)
        assert len(latest) == 3
        assert latest[0].id == "img-7"


# ── Vision Service Tests ──────────────────────────────────────────────────────

class TestVisionService:

    @pytest.mark.asyncio
    async def test_process_upload(self, tmp_path, sample_png):
        storage = ImageStorage(storage_dir=tmp_path)
        ctx = VisionContext()
        model = MagicMock()
        svc = VisionService(storage=storage, context=ctx, model=model)

        att = await svc.process_upload(sample_png, "test.png", "image/png", "conv-1")
        assert att.id
        assert await ctx.has_images("conv-1")

    @pytest.mark.asyncio
    async def test_should_use_vision_with_new_images(self, tmp_path):
        svc = VisionService(
            storage=ImageStorage(storage_dir=tmp_path),
            context=VisionContext(),
            model=MagicMock(),
        )
        assert svc.should_use_vision(has_new_images=True, conversation_id="any")

    @pytest.mark.asyncio
    async def test_should_use_vision_with_prior_images(self, tmp_path, sample_png):
        storage = ImageStorage(storage_dir=tmp_path)
        ctx = VisionContext()
        svc = VisionService(storage=storage, context=ctx, model=MagicMock())

        await svc.process_upload(sample_png, "x.png", "image/png", "conv-1")
        assert svc.should_use_vision(has_new_images=False, conversation_id="conv-1")

    @pytest.mark.asyncio
    async def test_should_not_use_vision_without_images(self, tmp_path):
        svc = VisionService(
            storage=ImageStorage(storage_dir=tmp_path),
            context=VisionContext(),
            model=MagicMock(),
        )
        assert not svc.should_use_vision(has_new_images=False, conversation_id="conv-empty")

    @pytest.mark.asyncio
    async def test_build_vision_prompt_includes_intent(self, tmp_path, sample_png):
        storage = ImageStorage(storage_dir=tmp_path)
        ctx = VisionContext()
        svc = VisionService(storage=storage, context=ctx, model=MagicMock())

        await svc.process_upload(sample_png, "code.png", "image/png", "conv-1")
        sys_prompt, user_prompt, intent = await svc.build_vision_prompt(
            "what's wrong with this code?", "conv-1"
        )
        assert intent == VisionIntent.CODE_SCREENSHOT
        assert "code screenshot" in sys_prompt.lower()
