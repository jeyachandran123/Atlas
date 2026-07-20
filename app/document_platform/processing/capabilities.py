"""
Parser Capability System (Objective 8).

Every parser describes what it can produce instead of the orchestrator
branching on parser type. Adding a new parser never requires editing the
orchestrator — it just declares its own capabilities honestly.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParserCapabilities:
    supports_tables: bool = False
    supports_images: bool = False          # can extract image BINARIES (not just references)
    supports_ocr_trigger: bool = False     # can this parser ever flag needs_ocr?
    supports_metadata: bool = True         # virtually every format has some source metadata
    supports_structure: bool = True        # can it produce a heading/section hierarchy?
    supports_language_detection: bool = True
    supports_embedded_images: bool = False  # images referenced but binary not extractable
