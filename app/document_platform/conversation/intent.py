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
    CONVERSATIONAL = "conversational"
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

    _PLEASANTRIES = frozenset({
        "hi", "hey", "hello", "yo", "hiya", "howdy", "sup", "greetings",
        "morning", "afternoon", "evening", "night", "good", "day",
        "thanks", "thank", "thankyou", "thx", "ty", "cheers",
        "ok", "okay", "k", "cool", "nice", "great", "awesome", "got", "it",
        "bye", "goodbye", "see", "you", "later", "please", "sorry", "welcome",
        "there", "up", "and", "a", "im", "i", "am", "hai",
        "how", "are", "is", "doing", "your", "u", "r", "hru", "wassup",
        "yes", "no", "yeah", "yep", "nope", "sure", "alright", "fine", "well",
    })
    """Words a message can be built entirely out of and still say nothing.

    Matching on the *whole* message rather than its opening is what makes
    "hey hi" and "thanks, great" work without letting "hi, how many rows are
    in the sheet?" escape the grounded path - that one carries "rows" and
    "sheet", so it is not small talk and never reaches this set.
    """

    _ABOUT_THE_ASSISTANT = re.compile(
        r"^\s*(who|what)\s+(are|is|r)\s+(you|u|this)"
        r"|^\s*(what|which)\s+(can|do)\s+you\s+(do|know)"
        r"|^\s*how\s+(are|r)\s+(you|u)"
        r"|^\s*(introduce|tell\s+me\s+about)\s+your(self)?"
        r"|^\s*(are|r)\s+(you|u)\s+(there|ok|real|an?\s+(ai|bot|robot))",
        re.IGNORECASE,
    )
    """Questions addressed to the assistant rather than to the documents."""

    _WORDS = re.compile(r"[A-Za-z']+")

    def _is_conversational(self, question: str) -> bool:
        """Is this talk directed at the assistant, not at the knowledge base?

        A greeting has no answer in a set of documents, and searching for one
        produces the single worst thing this product does: replying "I don't
        have enough information in the knowledge base to answer that" to "hey
        hi". That is not grounding working, it is the assistant failing to
        notice it was being spoken to.

        Narrow on purpose. A message carrying any word that is not small talk
        stays on the grounded path, because routing a real question away from
        the documents that answer it is the more expensive mistake.
        """
        if self._ABOUT_THE_ASSISTANT.search(question):
            return True
        words = [w.lower() for w in self._WORDS.findall(question)]
        if not words or len(words) > 6:
            return False
        return all(word in self._PLEASANTRIES for word in words)

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
        if self._is_conversational(question):
            return IntentType.CONVERSATIONAL
        if self._UNSUPPORTED.search(question):
            return IntentType.UNSUPPORTED
        for intent, pattern in self._RULES:
            if pattern.search(question):
                return intent
        return IntentType.QUESTION_ANSWERING


def get_intent_classifier() -> AbstractIntentClassifier:
    return RuleBasedIntentClassifier()
