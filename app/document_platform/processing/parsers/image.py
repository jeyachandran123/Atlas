"""
Image parser — metadata + dimensions; text extraction is OCR's job, which the
pipeline invokes separately (needs_ocr=True is always set for images).
"""
from __future__ import annotations

import struct

from app.document_platform.processing.capabilities import ParserCapabilities
from app.document_platform.processing.models import (
    DocumentNode, ImageRef, NodeType, ParsedDocument, RawMetadata,
)
from app.document_platform.processing.parsers.base import AbstractDocumentParser


def _image_dimensions(content: bytes, ext: str) -> tuple[int | None, int | None]:
    """Header-only dimension read — no imaging library required."""
    try:
        if ext == ".png" and len(content) > 24:
            w, h = struct.unpack(">II", content[16:24])
            return int(w), int(h)
        if ext == ".gif" and len(content) > 10:
            w, h = struct.unpack("<HH", content[6:10])
            return int(w), int(h)
        if ext in (".jpg", ".jpeg"):
            i = 2
            while i + 9 < len(content):
                if content[i] != 0xFF:
                    break
                marker = content[i + 1]
                seg_len = struct.unpack(">H", content[i + 2:i + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3):  # SOF frames
                    h, w = struct.unpack(">HH", content[i + 5:i + 9])
                    return int(w), int(h)
                i += 2 + seg_len
        if ext == ".webp" and len(content) > 30 and content[12:16] == b"VP8 ":
            w = struct.unpack("<H", content[26:28])[0] & 0x3FFF
            h = struct.unpack("<H", content[28:30])[0] & 0x3FFF
            return int(w), int(h)
    except Exception:
        pass
    return None, None


class ImageParser(AbstractDocumentParser):
    name = "image"
    extensions = (".png", ".jpg", ".jpeg", ".gif", ".webp")
    version = "1.0.0"
    capabilities = ParserCapabilities(
        supports_tables=False,
        supports_images=True,
        supports_ocr_trigger=True,
        supports_structure=False,
        supports_language_detection=False,  # no text exists until OCR runs
    )

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".png"
        width, height = _image_dimensions(content, ext)

        root = DocumentNode(type=NodeType.DOCUMENT)
        root.add(DocumentNode(
            type=NodeType.IMAGE,
            text=filename,
            meta={"width": width, "height": height, "format": ext.lstrip(".")},
        ))
        return ParsedDocument(
            root=root,
            images=[ImageRef(
                name=filename, content=content, page=1,
                width=width, height=height, format=ext.lstrip("."),
            )],
            raw_metadata=RawMetadata(custom={"width": width, "height": height}),
            needs_ocr=True,  # OCR trigger: image uploads always qualify
            parser_name=self.name,
        )
