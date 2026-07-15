"""
Topic Detection and Similarity.

Detects the active topic from a message and compares it against
the current conversation topic to determine relationship.
"""

from __future__ import annotations

import re
from collections import Counter

from app.intelligence.context.state import TopicRelation

# Words that carry no topical weight
_STOP_WORDS = frozenset(
    "i me my we our you your he she it they them this that these those "
    "a an the is am are was were be been being have has had do does did "
    "will would shall should can could may might must need dare "
    "and but or nor for yet so if then else when while until after before "
    "to of in on at by from with about between through during "
    "not no very much more most also just only even still already "
    "what how why where who which whom whose "
    "please thanks thank okay ok yes yeah sure hi hello hey "
    "good morning afternoon evening night".split()
)

# Short messages that signal a context reset (greeting/acknowledgment)
_RESET_PATTERNS = [
    r"^(hi|hello|hey|good\s*(morning|afternoon|evening|night))[\s!.]*$",
    r"^(thanks|thank\s*you|thx|ty)[\s!.]*$",
    r"^(bye|goodbye|see\s*you|later)[\s!.]*$",
    r"^(okay|ok|nice|cool|great|got\s*it|understood|alright)[\s!.]*$",
    r"^(yes|no|yep|nope|sure|nah)[\s!.]*$",
]

# Short follow-up patterns that inherit context from active topic
_FOLLOWUP_PATTERNS = [
    r"^why\??$",
    r"^how\??$",
    r"^(what|how)\s+about\s+",
    r"^can\s+i\s+use\s+",
    r"^(explain|tell)\s+(me\s+)?more",
    r"^can\s+(you\s+)?(explain|tell|describe|elaborate)",  # "can explain more..."
    r"^what\s+(is|are)\s+(it|they|that|this)\??$",
    r"^(and|but)\s+",
    r"^is\s+(it|that|this)\s+",
    r"^(really|seriously)\??$",
    r"^(example|examples)\??$",
    r"^(more|tell)\s+(me\s+)?(about|more)",
    r"\b(they|it|that|this|there|those|these)\b.*\?",  # pronoun-referencing questions
]


def extract_topic_keywords(text: str) -> list[str]:
    """Extract meaningful topic keywords from text."""
    words = re.findall(r"[a-z][a-z0-9+#.-]*", text.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 2]


def is_reset_message(message: str) -> bool:
    """Detect messages that should trigger a context reset."""
    clean = message.strip().lower()
    if len(clean) > 30:
        return False
    return any(re.match(p, clean) for p in _RESET_PATTERNS)


def is_followup_message(message: str) -> bool:
    """Detect short follow-up questions that inherit active topic context."""
    clean = message.strip().lower()
    if len(clean) > 60:
        return False
    return any(re.match(p, clean) for p in _FOLLOWUP_PATTERNS)


def compute_topic_similarity(keywords_a: list[str], keywords_b: list[str]) -> float:
    """
    Compute Jaccard-like similarity between two keyword sets.
    Returns 0.0 (no overlap) to 1.0 (identical).
    """
    if not keywords_a or not keywords_b:
        return 0.0
    set_a = set(keywords_a)
    set_b = set(keywords_b)
    intersection = set_a & set_b
    union = set_a | set_b
    if not union:
        return 0.0
    return len(intersection) / len(union)


# Pronouns that signal the message refers to the active topic
_REFERENTIAL_PRONOUNS = frozenset(
    ["they", "it", "that", "this", "there", "those", "these", "their", "its"]
)


def _has_referential_pronoun(message: str) -> bool:
    """Return True if the message uses a pronoun that refers to prior context."""
    words = set(re.findall(r"[a-z]+", message.lower()))
    return bool(words & _REFERENTIAL_PRONOUNS)


def classify_topic_relation(
    new_message: str,
    current_topic_keywords: list[str],
    session_messages: list[dict],
) -> tuple[TopicRelation, float]:
    """
    Classify the relationship between the new message and the current topic.

    Returns:
        (TopicRelation, confidence)
    """
    # Reset messages are always new (but lightweight — no history needed)
    if is_reset_message(new_message):
        return TopicRelation.NEW_TOPIC, 1.0

    # Follow-up messages inherit the active topic
    if is_followup_message(new_message):
        if current_topic_keywords:
            return TopicRelation.CONTINUATION, 0.9
        return TopicRelation.NEW_TOPIC, 0.5

    new_keywords = extract_topic_keywords(new_message)

    # Pronoun-referencing messages ("they have...", "can explain more about that")
    # always continue the active topic when one exists
    if _has_referential_pronoun(new_message) and current_topic_keywords:
        return TopicRelation.CONTINUATION, 0.85

    if not new_keywords:
        # Very short non-followup, non-reset → treat as continuation if topic exists
        if current_topic_keywords:
            return TopicRelation.CONTINUATION, 0.6
        return TopicRelation.NEW_TOPIC, 0.5

    similarity = compute_topic_similarity(new_keywords, current_topic_keywords)

    # Also check against recent user messages for broader context
    if session_messages and similarity < 0.3:
        recent_user_msgs = [
            m["content"] for m in session_messages[-4:]
            if m.get("role") == "user" and m.get("content")
        ]
        recent_keywords = []
        for msg in recent_user_msgs:
            recent_keywords.extend(extract_topic_keywords(msg))
        broader_sim = compute_topic_similarity(new_keywords, recent_keywords)
        similarity = max(similarity, broader_sim * 0.8)

    if similarity >= 0.4:
        return TopicRelation.CONTINUATION, min(similarity + 0.3, 1.0)
    elif similarity >= 0.2:
        return TopicRelation.RELATED_FOLLOWUP, similarity + 0.2
    elif similarity >= 0.1:
        return TopicRelation.SUBTOPIC, similarity + 0.1
    else:
        return TopicRelation.NEW_TOPIC, max(1.0 - similarity, 0.7)
