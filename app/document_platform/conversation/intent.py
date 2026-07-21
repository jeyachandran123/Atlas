"""
Intent Engine (Objective 2). Rule-based first implementation — deterministic,
zero added latency, fully testable. An LLM-backed classifier is one new
subclass of AbstractIntentClassifier; nothing downstream changes.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from enum import Enum


class IntentType(str, Enum):
    QUESTION_ANSWERING = "question_answering"
    SUMMARIZATION = "summarization"
    COMPARISON = "comparison"
    EXTRACTION = "extraction"
    FILTERING = "filtering"
    ANALYTICS = "analytics"
    EXPLANATION = "explanation"
    DOCUMENT_LOOKUP = "document_lookup"
    METADATA_LOOKUP = "metadata_lookup"
    CALCULATION = "calculation"
    UNSUPPORTED = "unsupported"


class AbstractIntentClassifier(ABC):
    name: str = "abstract"

    @abstractmethod
    def classify(self, question: str) -> IntentType: ...


class RuleBasedIntentClassifier(AbstractIntentClassifier):
    """
    Ordered pattern rules; first match wins; default is QUESTION_ANSWERING.
    UNSUPPORTED deliberately catches generation-style requests — those are
    future-phase features and must fail gracefully, not hallucinate output.
    """

    name = "rule_based"

    _UNSUPPORTED = re.compile(
        r"\b(generate|create|make|produce|build|write)\b.{0,40}\b"
        r"(pdf|excel|spreadsheet|word document|docx|xlsx|powerpoint|pptx|"
        r"report file|json file|csv file|code|script|program|app)\b"
        r"|\b(draw|paint|render)\b.{0,30}\b(image|picture|diagram|chart)\b",
        re.IGNORECASE,
    )
    _RULES: list[tuple[IntentType, re.Pattern]] = [
        (IntentType.SUMMARIZATION, re.compile(
            r"\b(summari[sz]e|summary|overview|tl;?dr|key points|main points|gist)\b", re.I)),
        (IntentType.COMPARISON, re.compile(
            r"\b(compare|comparison|versus|vs\.?|difference between|differences|contrast)\b", re.I)),
        (IntentType.EXTRACTION, re.compile(
            r"\b(extract|list all|pull out|find all|enumerate)\b", re.I)),
        (IntentType.FILTERING, re.compile(
            r"\b(filter|only show|show only|which .{0,40}(match|contain|include))\b", re.I)),
        (IntentType.ANALYTICS, re.compile(
            r"\b(how many|count of|total number|average|trend|statistics|distribution)\b", re.I)),
        (IntentType.CALCULATION, re.compile(
            r"\b(calculate|compute|sum of|multiply|percentage of)\b", re.I)),
        (IntentType.METADATA_LOOKUP, re.compile(
            r"\b(author|who wrote|when was .{0,30}(created|modified|uploaded)|"
            r"file (size|type|format)|page count|how many pages)\b", re.I)),
        (IntentType.DOCUMENT_LOOKUP, re.compile(
            r"\b(which document|what documents|find the document|locate the (file|document))\b", re.I)),
        (IntentType.EXPLANATION, re.compile(
            r"\b(explain|why does|why is|how does|how do|what causes|walk me through)\b", re.I)),
    ]

    def classify(self, question: str) -> IntentType:
        if self._UNSUPPORTED.search(question):
            return IntentType.UNSUPPORTED
        for intent, pattern in self._RULES:
            if pattern.search(question):
                return intent
        return IntentType.QUESTION_ANSWERING


def get_intent_classifier() -> AbstractIntentClassifier:
    return RuleBasedIntentClassifier()
