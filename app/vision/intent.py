"""
Vision Intent Detector.

Extends the existing IntentDetector to classify vision-specific intents
when images are present in the conversation.
"""
from __future__ import annotations

import re

from app.vision.schemas import VisionIntent


# Keyword/pattern rules for vision intent classification
_VISION_RULES: list[tuple[VisionIntent, list[str], list[str]]] = [
    (VisionIntent.OCR, [
        "text in", "read the text", "extract text", "ocr", "what does it say",
        "transcribe", "words in", "invoice", "receipt", "bill", "document",
    ], [r"\bread\b.*\btext\b", r"\bextract\b", r"\btranscri"]),

    (VisionIntent.CODE_SCREENSHOT, [
        "code", "function", "bug", "error in code", "syntax", "programming",
        "what language", "fix this code", "improve this code", "refactor",
    ], [r"\bcode\b", r"\bfunction\b", r"\bsyntax\b", r"\bbug\b"]),

    (VisionIntent.ERROR_SCREENSHOT, [
        "error", "exception", "stack trace", "traceback", "crash", "failed",
        "fix this error", "what went wrong", "debug",
    ], [r"\berror\b", r"\bexception\b", r"\bstack\s*trace\b", r"\btraceback\b"]),

    (VisionIntent.UI_ANALYSIS, [
        "ui", "interface", "layout", "design", "website", "app screenshot",
        "ux", "component", "button", "form", "page", "screen",
        "improve the design", "react", "html", "css",
    ], [r"\bui\b", r"\blayout\b", r"\bdesign\b", r"\bwebsite\b", r"\bscreen\b"]),

    (VisionIntent.DIAGRAM_ANALYSIS, [
        "diagram", "architecture", "flowchart", "flow chart", "system design",
        "uml", "sequence diagram", "er diagram", "data flow",
    ], [r"\bdiagram\b", r"\barchitect\w*\b", r"\bflowchart\b", r"\buml\b"]),

    (VisionIntent.CHART_ANALYSIS, [
        "chart", "graph", "dashboard", "metrics", "trend", "data",
        "bar chart", "pie chart", "line graph", "visualization",
    ], [r"\bchart\b", r"\bgraph\b", r"\bdashboard\b", r"\btrend\b"]),

    (VisionIntent.DOCUMENT_ANALYSIS, [
        "document", "pdf", "form", "id card", "passport", "license",
        "certificate", "letter", "report", "summarize this",
    ], [r"\bdocument\b", r"\bpdf\b", r"\bform\b", r"\bsummariz"]),

    (VisionIntent.OBJECT_DETECTION, [
        "what is this", "identify", "what object", "what item", "what product",
        "what phone", "what car", "what flower", "what food", "what brand",
        "recognize", "what model",
    ], [r"\bwhat\s+(is|are)\s+th", r"\bidentify\b", r"\brecognize\b"]),

    (VisionIntent.IMAGE_DESCRIPTION, [
        "describe", "what do you see", "tell me about", "explain this image",
        "what's in this", "what is happening", "what's going on",
    ], [r"\bdescribe\b", r"\bwhat.{0,10}see\b", r"\bwhat.{0,10}happening\b"]),
]


def detect_vision_intent(message: str, has_images: bool) -> tuple[VisionIntent, float]:
    """
    Detect the vision-specific intent from the user message.

    Returns (intent, confidence).
    Only called when images are present in the request.
    """
    if not has_images:
        return VisionIntent.GENERAL_VISION, 0.0

    lower = message.lower()
    best_intent = VisionIntent.GENERAL_VISION
    best_score = 0.0

    for intent, keywords, patterns in _VISION_RULES:
        hits = sum(1 for kw in keywords if kw in lower)
        hits += sum(1 for pat in patterns if re.search(pat, lower))
        if hits > 0:
            score = min(0.3 + (hits - 1) * 0.15, 1.0)
            if score > best_score:
                best_score = score
                best_intent = intent

    # If no specific intent matched but images are present, default to general vision
    if best_score == 0.0:
        # Check for very generic questions
        if re.search(r"\bwhat\b|\bdescribe\b|\btell\b|\bexplain\b", lower):
            return VisionIntent.IMAGE_DESCRIPTION, 0.4
        return VisionIntent.GENERAL_VISION, 0.3

    return best_intent, best_score
