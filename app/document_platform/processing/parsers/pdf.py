"""
PDF parser (pypdf) — pages, paragraphs, heading heuristics, images, metadata.
Flags needs_ocr when the text layer is empty/near-empty (scanned document).
"""
from __future__ import annotations

import io
import re

from loguru import logger

from app.document_platform.processing.capabilities import ParserCapabilities
from app.document_platform.processing.models import (
    DocumentNode, ImageRef, NodeType, ParsedDocument, RawMetadata,
)
from app.document_platform.processing.parsers.base import AbstractDocumentParser, ParserError

_SCANNED_CHARS_PER_PAGE = 50
# Short line, no terminal punctuation, mostly title-cased → heading heuristic
_HEADING_LIKE = re.compile(r"^[A-Z0-9][^.!?]{0,79}$")

_RENDER_SCALE = 2
"""Roughly 144 dpi. Enough for the OCR stage to read body text off a scan
without producing images so large that every one has to be thrown away again."""

_MAX_RENDERED_PAGES = 10
"""How much of a scanned document is worth reading.

Each rendered page costs one call to the OCR stage, so this is a time budget
as much as anything: ten pages is tens of seconds, a hundred is minutes of an
upload appearing to hang. A scan longer than this gets its first ten pages
indexed rather than nothing at all.
"""


def _embedded_images(reader) -> list[ImageRef]:
    """Pictures placed on the pages — figures, charts, photographs.

    Best-effort: some encodings are not extractable, and a document whose
    illustrations cannot be decoded is still a document.
    """
    images: list[ImageRef] = []
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            for img in page.images:
                name = img.name or f"page{page_no}-img"
                images.append(ImageRef(
                    name=name,
                    content=img.data,
                    page=page_no,
                    format=name.rsplit(".", 1)[-1].lower() if "." in name else "png",
                ))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"PDF page {page_no} image extraction failed: {e}")
    return images


def _render_pages(content: bytes, limit: int) -> list[ImageRef]:
    """The pages themselves, as images, for a PDF with no text layer.

    ``page.images`` returns the pictures *embedded* in a page - on a scanned
    document those are the letterhead, the logos and the QR code, and handing
    them to the OCR stage produces a knowledge base that knows the document
    contains "a QR code" and "the Indian Railways logo" while the passenger,
    the train and the date go unread. The content of a scan is the page, so
    the page is what has to be rendered.

    Returns nothing at all if no renderer is installed, which leaves the
    previous behaviour exactly as it was: embedded images, and a document that
    parses without failing.
    """
    try:
        import pypdfium2 as pdfium  # type: ignore
    except ImportError:
        logger.info(
            "No PDF renderer installed; a scanned PDF will be indexed from its "
            "embedded images only. Install pypdfium2 to read the pages."
        )
        return []

    rendered: list[ImageRef] = []
    document = None
    try:
        document = pdfium.PdfDocument(content)
        for index in range(min(len(document), limit)):
            page = document[index]
            image = page.render(scale=_RENDER_SCALE).to_pil().convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=80, optimize=True)
            rendered.append(ImageRef(
                name=f"page{index + 1}.jpg",
                content=buffer.getvalue(),
                page=index + 1,
                width=image.width,
                height=image.height,
                format="jpeg",
            ))
    except Exception as e:  # noqa: BLE001 - a scan we cannot render is not fatal
        logger.warning(f"Could not render PDF pages for OCR: {e}")
        return rendered
    finally:
        if document is not None:
            try:
                document.close()
            except Exception:  # noqa: BLE001
                pass
    return rendered


class PdfParser(AbstractDocumentParser):
    name = "pdf"
    extensions = (".pdf",)
    version = "1.0.0"
    capabilities = ParserCapabilities(
        supports_tables=False,   # pypdf does not expose table structure
        supports_images=True,
        supports_ocr_trigger=True,
        supports_structure=True,  # heading heuristic
    )

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(content))
        except Exception as e:
            raise ParserError(f"Cannot open PDF: {e}") from e

        root = DocumentNode(type=NodeType.DOCUMENT)
        images: list[ImageRef] = []
        total_chars = 0

        for page_no, page in enumerate(reader.pages, start=1):
            page_node = root.add(DocumentNode(type=NodeType.PAGE, page=page_no))
            try:
                text = page.extract_text() or ""
            except Exception as e:
                logger.debug(f"PDF page {page_no} text extraction failed: {e}")
                text = ""
            total_chars += len(text.strip())

            for block in re.split(r"\n\s*\n", text):
                block = block.strip()
                if not block:
                    continue
                first_line = block.splitlines()[0].strip()
                if (
                    len(block.splitlines()) == 1
                    and len(first_line) <= 80
                    and _HEADING_LIKE.match(first_line)
                    and first_line == first_line.rstrip(".")
                    and sum(w[:1].isupper() for w in first_line.split()) >= max(1, len(first_line.split()) // 2)
                ):
                    page_node.add(DocumentNode(
                        type=NodeType.HEADING, text=first_line, level=2, page=page_no,
                    ))
                else:
                    page_node.add(DocumentNode(
                        type=NodeType.PARAGRAPH, text=block, page=page_no,
                    ))

        meta = reader.metadata or {}
        page_count = len(reader.pages)
        needs_ocr = page_count > 0 and (total_chars / page_count) < _SCANNED_CHARS_PER_PAGE

        # Which pictures matter depends on whether there was any text, so the
        # decision is made once here rather than page by page above. Decoding
        # every embedded image and then discarding it for a scan is the single
        # slowest thing this parser used to do, and it did it on exactly the
        # documents that could least afford the delay.
        if needs_ocr:
            # No text layer: the page *is* the content. Embedded images on a
            # scan are the letterhead and the QR code - one model call each,
            # and "this is a QR code" indexed next to what somebody searched
            # for.
            images = _render_pages(content, _MAX_RENDERED_PAGES)
            if images:
                logger.info(
                    f"{filename}: no text layer, rendered "
                    f"{len(images)}/{page_count} page(s) for OCR"
                )
            else:
                images = _embedded_images(reader)
        else:
            images = _embedded_images(reader)

        return ParsedDocument(
            root=root,
            images=images,
            raw_metadata=RawMetadata(
                title=str(meta.get("/Title", "") or ""),
                author=str(meta.get("/Author", "") or ""),
                created=str(meta.get("/CreationDate", "") or ""),
                modified=str(meta.get("/ModDate", "") or ""),
                page_count=page_count,
            ),
            needs_ocr=needs_ocr,
            parser_name=self.name,
        )
