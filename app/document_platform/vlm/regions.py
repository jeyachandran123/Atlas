"""Find each receipt on a scanned page, so each can be read on its own.

A model reading a whole page spends its resolution on the page. A narrow
thermal receipt on a landscape A3 scan occupies 12% of the width, and read
that way its total came back 20.0 for a printed 20.80 in every fast run — at
every resolution tried, because the receipt stayed a sliver of the image. Cut
out and sent alone, the same receipt fills the image.

So a scanned page is first *located*: one short model call returns a box per
receipt, measured at 1.4-2.1s a page. Each box becomes its own image. A page
that is one document filling most of the page is kept whole, so a multi-page
invoice still reaches the model as consecutive whole pages.

Nothing here can lose a page: a failed or empty location keeps the page whole,
exactly as it was sent before this stage existed.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from loguru import logger

from app.document_platform.vlm.errors import DocumentVLMError
from app.document_platform.vlm.ports import (
    DocumentImage,
    DocumentPayload,
    DocumentVLMPort,
    ExtractionPrompt,
    VLMExtractionRequest,
)

LOCATE_PROMPT_ID = "invoice.locate"
LOCATE_PROMPT_VERSION = "1.0.0"

_LOCATE_PROMPT = (
    "This is a scanned page. Find every separate receipt or invoice on it. "
    "For each, give its bounding box as [x_min, y_min, x_max, y_max] in "
    "coordinates normalised to 0-1000 of the image width and height, covering "
    "the whole receipt from its header to its last printed line. Return only "
    'JSON: {"receipts": [{"box": [x_min, y_min, x_max, y_max]}]}'
)

#: The page is shrunk to this before locating: boxes need layout, not print.
_LOCATE_MAX_SIDE = 1600

#: One box covering at least this share of the page is a full-page document,
#: kept whole rather than cropped.
_FULL_PAGE_AREA = 0.6

#: Boxes smaller than this share of the page are a stamp or a QR code, not a
#: receipt; an unusable answer keeps the page whole.
_MIN_REGION_AREA = 0.01

#: Padding added on every side of a box, as a share of the page, so a box drawn
#: a line short does not cut off the header or the total.
_PAD = 0.02

#: A crop smaller than this on its longest side is enlarged to it. The model
#: tiles its input; an enlarged receipt gets more tiles per printed character.
_CROP_MIN_SIDE = 1800


@dataclass(frozen=True, slots=True)
class Unit:
    """One extraction call's worth of input: a receipt cut from a page, or a run
    of consecutive whole pages that may together be one document."""

    images: tuple[DocumentImage, ...]
    cropped: bool


class RegionLocator:
    """Splits a scanned payload into units, one per receipt. Never raises."""

    def __init__(self, vlm: DocumentVLMPort, *, max_image_bytes: int = 1_400_000) -> None:
        self._vlm = vlm
        self._max_image_bytes = max_image_bytes

    async def units(self, payload: DocumentPayload, request_id: str) -> list[Unit]:
        import asyncio

        boxes = await asyncio.gather(
            *(self._locate(image, request_id) for image in payload.images)
        )
        units: list[Unit] = []
        whole: list[DocumentImage] = []
        for image, page_boxes in zip(payload.images, boxes, strict=True):
            crops = self._crops(image, page_boxes) if page_boxes else []
            if not crops:
                whole.append(image)
                continue
            if whole:
                units.append(Unit(images=tuple(whole), cropped=False))
                whole = []
            units.extend(Unit(images=(crop,), cropped=True) for crop in crops)
        if whole:
            units.append(Unit(images=tuple(whole), cropped=False))
        return units

    # ── locating ─────────────────────────────────────────────────────────────

    async def _locate(
        self, image: DocumentImage, request_id: str
    ) -> list[tuple[float, float, float, float]]:
        """Receipt boxes on one page as fractions of its size, or ``[]`` to keep
        the page whole."""
        try:
            thumbnail = _shrink(image, _LOCATE_MAX_SIDE)
            result = await self._vlm.extract_document(
                VLMExtractionRequest(
                    payload=DocumentPayload(
                        images=(thumbnail,), media_type=image.media_type, page_count=1
                    ),
                    prompt=ExtractionPrompt(
                        system="",
                        user=_LOCATE_PROMPT,
                        prompt_id=LOCATE_PROMPT_ID,
                        version=LOCATE_PROMPT_VERSION,
                        max_output_tokens=600,
                        temperature=0.0,
                    ),
                    request_id=request_id,
                )
            )
        except DocumentVLMError as exc:
            logger.warning(f"locating receipts on page {image.page} failed ({exc.code}); kept whole")
            return []
        except Exception as exc:  # noqa: BLE001 - a bad page image keeps the page whole
            logger.warning(f"locating receipts on page {image.page} failed: {exc}; kept whole")
            return []
        return _boxes(result.structured)

    # ── cropping ─────────────────────────────────────────────────────────────

    def _crops(
        self, image: DocumentImage, boxes: list[tuple[float, float, float, float]]
    ) -> list[DocumentImage]:
        if len(boxes) == 1 and _area(boxes[0]) >= _FULL_PAGE_AREA:
            return []
        try:
            from PIL import Image

            page = Image.open(io.BytesIO(image.data)).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"page {image.page} could not be decoded for cropping: {exc}")
            return []

        crops: list[DocumentImage] = []
        width, height = page.size
        for x0, y0, x1, y1 in boxes:
            region = page.crop(
                (
                    int(max(0.0, x0 - _PAD) * width),
                    int(max(0.0, y0 - _PAD) * height),
                    int(min(1.0, x1 + _PAD) * width),
                    int(min(1.0, y1 + _PAD) * height),
                )
            )
            crops.append(self._encode(region, image.page))
        return crops

    def _encode(self, region, page: int | None) -> DocumentImage:
        from PIL import Image

        longest = max(region.size)
        if longest < _CROP_MIN_SIDE:
            factor = min(3.0, _CROP_MIN_SIDE / longest)
            region = region.resize(
                (int(region.width * factor), int(region.height * factor)), Image.LANCZOS
            )
        data = b""
        for quality in (90, 80, 70, 60):
            buffer = io.BytesIO()
            region.save(buffer, format="JPEG", quality=quality, optimize=True)
            data = buffer.getvalue()
            if len(data) <= self._max_image_bytes:
                break
        return DocumentImage(data=data, media_type="image/jpeg", page=page)


# ── helpers ──────────────────────────────────────────────────────────────────


def _boxes(structured: object) -> list[tuple[float, float, float, float]]:
    """Valid boxes in reading order, as fractions; ``[]`` if none are usable."""
    if not isinstance(structured, dict):
        return []
    items = structured.get("receipts")
    if not isinstance(items, list):
        return []

    boxes: list[tuple[float, float, float, float]] = []
    for item in items:
        raw = item.get("box") if isinstance(item, dict) else item
        if not isinstance(raw, list | tuple) or len(raw) != 4:
            continue
        try:
            x0, y0, x1, y1 = (min(1.0, max(0.0, float(v) / 1000.0)) for v in raw)
        except (TypeError, ValueError):
            continue
        if x1 <= x0 or y1 <= y0 or _area((x0, y0, x1, y1)) < _MIN_REGION_AREA:
            continue
        boxes.append((x0, y0, x1, y1))

    kept: list[tuple[float, float, float, float]] = []
    for box in sorted(boxes, key=_area, reverse=True):
        if all(_overlap(box, other) < 0.5 for other in kept):
            kept.append(box)
    # Reading order: columns left to right, top to bottom within a column.
    return sorted(kept, key=lambda b: (round(b[0], 1), b[1]))


def _area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _overlap(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Intersection over the smaller box: a duplicate of a box, or a box inside
    another, is the same receipt."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min(_area(a), _area(b)) or 1.0
    return (ix * iy) / smaller


def _shrink(image: DocumentImage, max_side: int) -> DocumentImage:
    from PIL import Image

    with Image.open(io.BytesIO(image.data)) as opened:
        page = opened.convert("RGB")
    page.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    page.save(buffer, format="JPEG", quality=85)
    return DocumentImage(data=buffer.getvalue(), media_type="image/jpeg", page=image.page)


__all__ = ["LOCATE_PROMPT_ID", "LOCATE_PROMPT_VERSION", "RegionLocator", "Unit"]
