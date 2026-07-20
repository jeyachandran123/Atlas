"""
ContentCleaner — normalizes text artifacts while preserving semantics.

Applied to every text node in the tree: encoding repair, invalid characters,
duplicate whitespace, broken-paragraph rejoining, page artifacts.
"""
from __future__ import annotations

import re

from app.document_platform.processing.models import DocumentNode

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_MULTI_NEWLINE = re.compile(r"\n{3,}")
_SOFT_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")          # hyphenated line break
_MID_SENTENCE_BREAK = re.compile(r"(?<![.!?:;\n])\n(?=[a-zà-ÿ])")  # broken paragraph
_PAGE_ARTIFACT = re.compile(r"^\s*(page\s+\d+(\s+of\s+\d+)?|\d+\s*/\s*\d+|[-—_]{4,})\s*$", re.IGNORECASE | re.MULTILINE)


class ContentCleaner:
    def clean_text(self, text: str) -> str:
        if not text:
            return ""
        t = text.replace("\r\n", "\n").replace("\r", "\n")
        t = t.replace("﻿", "").replace("­", "")     # BOM, soft hyphen
        t = _CONTROL.sub("", t)
        t = _PAGE_ARTIFACT.sub("", t)
        t = _SOFT_HYPHEN_BREAK.sub(r"\1\2", t)                # rejoin hyphen-split words
        t = _MID_SENTENCE_BREAK.sub(" ", t)                   # rejoin broken paragraphs
        t = _MULTI_SPACE.sub(" ", t)
        t = _MULTI_NEWLINE.sub("\n\n", t)
        return t.strip()

    def clean_tree(self, root: DocumentNode) -> DocumentNode:
        for node in root.walk():
            if node.text:
                node.text = self.clean_text(node.text)
        return root
