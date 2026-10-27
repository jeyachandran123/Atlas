"""The payload stage: what actually reaches the model, and what is refused.

This is where the platform's existing OCR service is reused, and where the most
dangerous input — an empty document — is stopped. A VLM given nothing does not
return nothing; it returns a fluent invention, and no downstream validation can
tell that apart from a real extraction.
"""

from __future__ import annotations

import io
import os

import pytest

from app.document_platform.processing.ocr import AbstractOcrProvider, OcrResult, OcrService
from app.document_platform.vlm.errors import (
    DocumentTooLargeError,
    EmptyDocumentError,
    UnsupportedDocumentError,
)
from app.document_platform.vlm.payload import DocumentPayloadBuilder

from .conftest import JPEG_BYTES, PNG_BYTES


class StubOcr(AbstractOcrProvider):
    """OCR that always finds the same text. Deterministic and free."""

    name = "stub"

    def __init__(self, text: str = "OCR TEXT INV-1", *, fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.calls = 0

    async def extract_text(self, image_bytes: bytes, image_format: str) -> OcrResult:
        self.calls += 1
        if self.fail:
            raise RuntimeError("tesseract binary missing")
        return OcrResult(text=self.text, performed=True, provider=self.name)


def pdf_bytes(text: str = "INVOICE INV-2026-0042\nTotal 305.20") -> bytes:
    """A real, minimal PDF with a text layer, built with the platform's own
    PDF library so the test exercises the same extraction path production does."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for line_number, line in enumerate(text.splitlines()):
        pdf.drawString(72, 800 - line_number * 20, line)
    pdf.save()
    return buffer.getvalue()


def blank_pdf_bytes(pages: int = 1) -> bytes:
    """A PDF with no text layer at all — a scan, as far as the pipeline can tell."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for _ in range(pages):
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


class TestImages:
    async def test_an_image_becomes_a_single_page_payload(self) -> None:
        report = await DocumentPayloadBuilder().build(filename="a.png", content=PNG_BYTES)
        assert len(report.payload.images) == 1
        assert report.payload.images[0].media_type == "image/png"
        assert report.payload.page_count == 1

    async def test_ocr_text_is_attached_when_a_provider_is_configured(self) -> None:
        ocr = StubOcr()
        report = await DocumentPayloadBuilder(ocr=OcrService(ocr)).build(
            filename="a.png", content=PNG_BYTES
        )
        assert ocr.calls == 1
        assert report.payload.ocr_text == "OCR TEXT INV-1"
        assert report.payload.text_source == "ocr"
        assert report.ocr_performed

    async def test_the_default_null_ocr_provider_is_not_a_failure(self) -> None:
        """The platform ships with OCR unconfigured; the pixels still carry the
        document."""
        report = await DocumentPayloadBuilder().build(filename="a.png", content=PNG_BYTES)
        assert report.payload.has_images
        assert report.payload.text_source == "none"
        assert report.ocr_provider == "null"

    async def test_a_broken_ocr_provider_degrades_rather_than_fails(self) -> None:
        report = await DocumentPayloadBuilder(ocr=OcrService(StubOcr(fail=True))).build(
            filename="a.png", content=PNG_BYTES
        )
        assert report.payload.has_images and not report.payload.has_text

    async def test_the_type_is_taken_from_the_bytes_not_the_name(self) -> None:
        """A client's filename and Content-Type are both things a client chose."""
        report = await DocumentPayloadBuilder().build(
            filename="invoice.pdf", content=JPEG_BYTES, declared_mime="application/pdf"
        )
        assert report.extension == ".jpg"

    async def test_an_extension_is_used_when_the_bytes_are_unrecognised(self) -> None:
        report = await DocumentPayloadBuilder().build(
            filename="scan.tiff", content=b"II*\x00 not really"
        )
        assert report.payload.media_type == "image/tiff"


class TestPdfs:
    async def test_a_text_layer_is_extracted_and_marked_as_such(self) -> None:
        report = await DocumentPayloadBuilder().build(
            filename="invoice.pdf", content=pdf_bytes()
        )
        assert "INV-2026-0042" in report.payload.ocr_text
        assert report.payload.text_source == "pdf_text_layer"
        assert report.payload.media_type == "application/pdf"

    async def test_a_born_digital_pdf_does_not_call_ocr(self) -> None:
        """OCR on a PDF that already knows its own text is money for nothing."""
        ocr = StubOcr()
        await DocumentPayloadBuilder(ocr=OcrService(ocr)).build(
            filename="invoice.pdf", content=pdf_bytes()
        )
        assert ocr.calls == 0

    async def test_page_count_is_reported(self) -> None:
        report = await DocumentPayloadBuilder().build(
            filename="invoice.pdf", content=pdf_bytes("Page one text")
        )
        assert report.payload.page_count == 1

    async def test_a_pdf_with_neither_text_nor_images_is_refused(self) -> None:
        """The empty-document trap, closed with a typed error that names the
        real problem."""
        with pytest.raises(EmptyDocumentError, match="neither text nor page images"):
            await DocumentPayloadBuilder().build(
                filename="scan.pdf", content=blank_pdf_bytes()
            )


class TestRejection:
    async def test_zero_bytes_is_refused(self) -> None:
        with pytest.raises(EmptyDocumentError):
            await DocumentPayloadBuilder().build(filename="a.png", content=b"")

    async def test_an_oversized_document_is_refused_before_any_work(self) -> None:
        builder = DocumentPayloadBuilder(max_bytes=1024)
        with pytest.raises(DocumentTooLargeError) as caught:
            await builder.build(filename="a.png", content=PNG_BYTES + b"0" * 4096)
        assert caught.value.http_status == 413

    async def test_an_unsupported_type_is_refused_with_the_supported_list(self) -> None:
        with pytest.raises(UnsupportedDocumentError) as caught:
            await DocumentPayloadBuilder().build(
                filename="notes.docx", content=b"PK\x03\x04 zip"
            )
        assert ".pdf" in caught.value.message
        assert caught.value.http_status == 415

    async def test_a_text_file_is_refused_rather_than_silently_accepted(self) -> None:
        """This pipeline is for documents a VLM reads. A .txt has no pixels and
        belongs in the text pipeline."""
        with pytest.raises(UnsupportedDocumentError):
            await DocumentPayloadBuilder().build(
                filename="invoice.txt", content=b"INVOICE 1", declared_mime="text/plain"
            )


class TestLimits:
    async def test_the_page_limit_is_configurable(self) -> None:
        builder = DocumentPayloadBuilder(max_pages=2)
        report = await builder.build(filename="a.png", content=PNG_BYTES)
        assert len(report.payload.images) <= 2

    async def test_the_size_limit_is_configurable(self) -> None:
        big = PNG_BYTES + b"0" * 2048
        assert await DocumentPayloadBuilder(max_bytes=10_000).build(
            filename="a.png", content=big
        )
        with pytest.raises(DocumentTooLargeError):
            await DocumentPayloadBuilder(max_bytes=100).build(filename="a.png", content=big)


def _image_bytes(fmt: str, size: tuple[int, int], noise: bool = False) -> bytes:
    from PIL import Image

    image = Image.new("RGB", size, "white")
    if noise:
        # Incompressible pixels, so the "scan" is reliably the largest image.
        image = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def scanned_pdf_bytes(pages: int = 2) -> bytes:
    """A scanner-app PDF: per page, one large scan plus a small overlay image."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for _ in range(pages):
        scan = ImageReader(io.BytesIO(_image_bytes("JPEG", (400, 560), noise=True)))
        overlay = ImageReader(io.BytesIO(_image_bytes("PNG", (20, 20))))
        pdf.drawImage(scan, 0, 0, width=400, height=560)
        pdf.drawImage(overlay, 500, 800, width=20, height=20)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


class TestImagesAProviderAccepts:
    async def test_a_tiff_upload_is_sent_as_png(self) -> None:
        """NVIDIA answers HTTP 415 to an image/tiff data URL."""
        report = await DocumentPayloadBuilder().build(
            filename="scan.tiff", content=_image_bytes("TIFF", (40, 40))
        )
        image = report.payload.images[0]
        assert image.media_type == "image/png"
        assert image.data.startswith(b"\x89PNG")
        assert report.payload.media_type == "image/tiff", "provenance keeps the upload's type"

    async def test_a_bmp_upload_is_sent_as_png(self) -> None:
        report = await DocumentPayloadBuilder().build(
            filename="scan.bmp", content=_image_bytes("BMP", (40, 40))
        )
        assert report.payload.images[0].media_type == "image/png"

    async def test_an_undecodable_upload_is_still_sent_as_it_is(self) -> None:
        """The upload is the whole document; dropping it would send nothing."""
        report = await DocumentPayloadBuilder().build(
            filename="scan.tiff", content=b"II*\x00 not really"
        )
        assert report.payload.images[0].media_type == "image/tiff"

    async def test_a_scanned_pdf_sends_each_page_rendered_not_its_layers(self) -> None:
        """Sending the embedded layers sent a blank background, refused TIFFs,
        and — with the image cap filled by page 1 — never page 2."""
        report = await DocumentPayloadBuilder(ocr=OcrService(StubOcr())).build(
            filename="receipts.pdf", content=scanned_pdf_bytes(pages=2)
        )
        images = report.payload.images
        assert [image.page for image in images] == [1, 2]
        assert all(image.media_type == "image/jpeg" for image in images)

    async def test_rendered_pages_fit_the_configured_image_budget(self) -> None:
        budget = 400_000  # the fixture's scan is incompressible noise
        report = await DocumentPayloadBuilder(
            ocr=OcrService(StubOcr()), max_image_bytes=budget
        ).build(filename="receipts.pdf", content=scanned_pdf_bytes(pages=1))
        assert report.payload.images[0].size_bytes <= budget

    async def test_a_larger_budget_buys_a_sharper_page(self) -> None:
        """Resolution decides accuracy: a dense page read right only at ~1 MB."""
        from PIL import Image

        def width(budget: int) -> int:
            return Image.open(io.BytesIO(images[budget][0].data)).width

        images = {}
        for budget in (400_000, 4_000_000):
            report = await DocumentPayloadBuilder(
                ocr=OcrService(StubOcr()), max_image_bytes=budget
            ).build(filename="receipts.pdf", content=scanned_pdf_bytes(pages=1))
            images[budget] = report.payload.images
        assert width(4_000_000) > width(400_000)

    async def test_without_a_renderer_the_embedded_images_are_sent(self, monkeypatch) -> None:
        monkeypatch.setattr(DocumentPayloadBuilder, "_render_pages", staticmethod(lambda *args: []))
        report = await DocumentPayloadBuilder(ocr=OcrService(StubOcr())).build(
            filename="receipts.pdf", content=scanned_pdf_bytes(pages=1)
        )
        assert len(report.payload.images) == 2, "the scan and its overlay"
