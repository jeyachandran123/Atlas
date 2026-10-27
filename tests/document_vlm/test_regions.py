"""Receipt splitting: each receipt on a scanned page is read on its own.

A narrow receipt on a landscape scan, read as part of the whole page, came back
20.0 for a printed 20.80 in every fast run. Cut out, it read 20.80 and the
invoice number exactly. These tests hold the guard rails that make cutting safe:
a page is never lost, a full-page document is never cut, and consecutive whole
pages stay together so a multi-page invoice is still one invoice.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass

from app.document_platform.processing.ocr import OcrService
from app.document_platform.vlm.errors import DocumentVLMUnavailableError
from app.document_platform.vlm.payload import DocumentPayloadBuilder
from app.document_platform.vlm.pipeline import DocumentExtractionPipeline
from app.document_platform.vlm.ports import (
    DocumentImage,
    DocumentPayload,
    VLMExtractionRequest,
    VLMExtractionResult,
)
from app.document_platform.vlm.regions import LOCATE_PROMPT_ID, RegionLocator, _boxes

from .conftest import ScriptedDocumentVLM
from .test_payload import StubOcr


def page_image(page: int = 1, size: tuple[int, int] = (600, 850)) -> DocumentImage:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="JPEG")
    return DocumentImage(data=buffer.getvalue(), media_type="image/jpeg", page=page)


@dataclass
class LocatingVLM(ScriptedDocumentVLM):
    """Answers locate calls with ``boxes``; every other call with an invoice
    numbered by the order the extraction calls arrived in."""

    boxes: list | None = None
    locate_error: bool = False

    async def extract_document(self, request: VLMExtractionRequest) -> VLMExtractionResult:
        if request.prompt.prompt_id != LOCATE_PROMPT_ID:
            extractions = [c for c in self.calls if c.prompt.prompt_id != LOCATE_PROMPT_ID]
            self.structured = {
                "invoice_number": f"INV-{len(extractions) + 1}",
                "totals": {"grand_total": 10.0},
            }
            return await super().extract_document(request)
        self.calls.append(request)
        if self.locate_error:
            raise DocumentVLMUnavailableError("down", provider="scripted", model="m")
        structured = {"receipts": [{"box": box} for box in (self.boxes or [])]}
        return VLMExtractionResult(
            structured=structured,
            raw_text=json.dumps(structured),
            provider=self.provider,
            model=self.model,
            latency_ms=1.0,
            request_id=request.request_id,
            prompt_id=request.prompt.prompt_id,
            prompt_version=request.prompt.version,
        )


class TestBoxes:
    def test_boxes_are_read_as_fractions_in_reading_order(self) -> None:
        found = _boxes({"receipts": [{"box": [600, 100, 900, 500]}, {"box": [100, 100, 400, 900]}]})
        assert found == [(0.1, 0.1, 0.4, 0.9), (0.6, 0.1, 0.9, 0.5)]

    def test_unusable_boxes_are_dropped(self) -> None:
        found = _boxes(
            {
                "receipts": [
                    {"box": [0, 0, 5, 5]},  # a speck, not a receipt
                    {"box": [500, 500, 400, 600]},  # inverted
                    {"box": "top left"},
                    {"box": [100, 100, 400, 900]},
                ]
            }
        )
        assert found == [(0.1, 0.1, 0.4, 0.9)]

    def test_a_box_inside_another_is_the_same_receipt(self) -> None:
        found = _boxes({"receipts": [{"box": [100, 100, 400, 900]}, {"box": [120, 150, 380, 850]}]})
        assert len(found) == 1

    def test_an_answer_without_receipts_is_no_boxes(self) -> None:
        assert _boxes({"invoice_number": "X"}) == []
        assert _boxes("not a dict") == []


class TestUnits:
    async def test_each_receipt_becomes_its_own_enlarged_unit(self) -> None:
        vlm = LocatingVLM(boxes=[[100, 100, 400, 900], [600, 100, 900, 500]])
        units = await RegionLocator(vlm).units(DocumentPayload(images=(page_image(),)), "r")
        assert [unit.cropped for unit in units] == [True, True]
        from PIL import Image

        sides = [max(Image.open(io.BytesIO(u.images[0].data)).size) for u in units]
        # The tall receipt (~714 px on the page) reaches the 1800 px floor; the
        # short one (~374 px) is enlarged by the 3x cap rather than to the floor.
        assert sides[0] >= 1800
        assert 374 < sides[1] <= 374 * 3 + 3

    async def test_a_full_page_document_is_not_cut(self) -> None:
        vlm = LocatingVLM(boxes=[[20, 20, 980, 980]])
        units = await RegionLocator(vlm).units(DocumentPayload(images=(page_image(),)), "r")
        assert len(units) == 1 and not units[0].cropped

    async def test_a_failed_location_keeps_the_page_whole(self) -> None:
        vlm = LocatingVLM(locate_error=True)
        units = await RegionLocator(vlm).units(DocumentPayload(images=(page_image(),)), "r")
        assert len(units) == 1 and not units[0].cropped

    async def test_consecutive_whole_pages_stay_together(self) -> None:
        """A two-page invoice must reach the model as one document."""
        vlm = LocatingVLM(boxes=[])
        payload = DocumentPayload(images=(page_image(1), page_image(2)))
        units = await RegionLocator(vlm).units(payload, "r")
        assert len(units) == 1 and [i.page for i in units[0].images] == [1, 2]


class TestPipeline:
    async def test_every_receipt_is_extracted_and_merged_in_order(self) -> None:
        vlm = LocatingVLM(boxes=[[100, 100, 400, 900], [600, 100, 900, 500]])
        pipeline = DocumentExtractionPipeline(vlm, locator=RegionLocator(vlm))
        outcome = await pipeline.extract_invoice(
            filename="receipts.jpg", content=page_image().data
        )
        assert sorted(d["invoice_number"] for d in outcome.data) == ["INV-1", "INV-2"]
        assert "locate" in outcome.stages
        assert outcome.document["images_sent"] == 2
        assert outcome.usage.total_tokens == 300, "usage is summed across calls"

    async def test_without_a_locator_the_document_goes_whole(self) -> None:
        vlm = LocatingVLM(boxes=[[100, 100, 400, 900], [600, 100, 900, 500]])
        outcome = await DocumentExtractionPipeline(vlm).extract_invoice(
            filename="receipts.jpg", content=page_image().data
        )
        assert len(outcome.data) == 1
        assert "locate" not in outcome.stages

    async def test_a_document_with_text_is_not_split(self) -> None:
        """Text describes whole pages; it cannot be divided between crops."""
        vlm = LocatingVLM(boxes=[[100, 100, 400, 900], [600, 100, 900, 500]])
        pipeline = DocumentExtractionPipeline(
            vlm,
            locator=RegionLocator(vlm),
            payload_builder=DocumentPayloadBuilder(ocr=OcrService(StubOcr())),
        )
        outcome = await pipeline.extract_invoice(
            filename="receipts.jpg", content=page_image().data
        )
        assert len(outcome.data) == 1
        assert not any(c.prompt.prompt_id == LOCATE_PROMPT_ID for c in vlm.calls)
