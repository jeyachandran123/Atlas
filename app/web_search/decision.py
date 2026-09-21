"""Does this message need the web — and once we have looked, have we seen enough?

Two model calls at most, each guarded by something cheaper. A pattern gate runs
first so ordinary chat ("ok da", "explain this function", "thanks") never pays for
a decision call. After the search, a second call decides whether the snippets
already answer the question or whether a page must be opened in full.

That second step is the difference between a search and an answer. Searching
"You.com API pricing" returns the price; it does not return the endpoint, the
auth header or the caveat that there is no image section. A person reads the
page at that point, so the assistant does too — once, never twice.

Nothing here performs I/O. Every function takes text and returns data, so the
whole decision layer is testable without a network or a model.
"""

from __future__ import annotations

import json
import re
from datetime import date

from app.web_search.schemas import SearchPlan

MAX_QUERIES = 3
MAX_READS = 2
_MAX_QUERY_CHARS = 200

# Anything whose answer changes with time, or that lives outside the model's
# training data. Deliberately loose: a false positive costs one short model
# call, a false negative means the user is told 2024 prices as today's fact.
_TIME_SENSITIVE = re.compile(
    r"\b(latest|newest|current(?:ly)?|now|today|tonight|yesterday|tomorrow|"
    r"recent(?:ly)?|this\s+(?:week|month|year)|last\s+(?:week|month|year|night)|"
    r"up\s?to\s?date|these\s+days|nowadays|so\s+far|still)\b",
    re.IGNORECASE,
)
_NEWS = re.compile(
    r"\b(news|headlines?|announce(?:d|ment)?|launch(?:ed|es)?|release(?:d|s)?|"
    r"updates?|happened|going\s+on|election|match|score|weather|forecast)\b",
    re.IGNORECASE,
)
_MARKET = re.compile(
    r"\b(price|pricing|cost|costs|rates?|fees?|stock|shares?|market\s?cap|"
    r"valuation|funding|revenue|salary|worth|cheapest|discount|offers?)\b",
    re.IGNORECASE,
)
# A lookup about the world, not about this codebase. "best" and "recommend"
# earn their place here: a recommendation the user acts on should not be built
# from a two-year-old memory of what existed.
_LOOKUP = re.compile(
    r"\b(who\s+(?:is|are|was|were)|what\s+is\s+the\s+(?:best|top|difference)|"
    r"where\s+(?:is|can\s+i)|when\s+(?:did|is|was|will)|how\s+much|how\s+many|"
    r"which\s+(?:is|one)\s+(?:better|best)|better\s+than|worse\s+than|"
    r"best\b|top\s+\d+|recommend\w*|suggest\w*|"
    r"compare|vs\.?|versus|alternatives?|options?\s+(?:for|to)|"
    r"reviews?|documentation|docs\b|api\b|changelog|"
    r"versions?\b|release\s+date|supports?\b|compatible)\b",
    re.IGNORECASE,
)
# A year at or after the model's training edge asks about a world it cannot know.
# "What is nasi lemak", "tell me about the taj mahal", "what is a bugatti
# chiron" — a named thing the user wants to know about. These were rejected as
# ordinary chat, so they never reached the decision model and could never show
# a picture. A false positive here costs one short model call, which then
# answers "no search"; a false negative costs the feature.
_ENTITY_ASK = re.compile(
    r"\b(who\s+(?:is|are|was|were)|what\s+(?:is|are|was|were)|what'?s\b|who'?s\b|"
    r"tell\s+me\s+about|whats\b)\b",
    re.IGNORECASE,
)
_RECENT_YEAR = re.compile(r"\b(202[5-9]|20[3-9]\d)\b")
_URL = re.compile(r"https?://\S+|\bwww\.\S+\.\w{2,}", re.IGNORECASE)
# The user asking in so many words. This alone is enough.
_EXPLICIT = re.compile(
    r"\b(search|google|look\s?up|find\s+out|check\s+online|on\s+the\s+(?:web|internet)|"
    r"browse|latest\s+info)\b",
    re.IGNORECASE,
)
# Asking to see something. Without this the gate rejected "show me the eiffel
# tower" as ordinary chat, so no search ran and no picture could ever appear —
# the request was for an image and the image was the one thing it could not get.
_WANTS_TO_SEE = re.compile(
    r"\b(show\s+me|what\s+(?:does|do|did)\s+.{2,40}\s+look\s+like|looks?\s+like|"
    r"pictures?\s+of|photos?\s+of|images?\s+of|see\s+(?:a|an|the)\b)",
    re.IGNORECASE,
)
# Questions about the conversation or the user's own files answer themselves
# from context the assistant already holds; the web has nothing to add.
_SELF_REFERENTIAL = re.compile(
    r"\b(this\s+(?:code|file|function|repo|document|conversation|chat|error)|"
    r"my\s+(?:code|file|repo|document|project)|above|previous\s+(?:answer|reply)|"
    r"you\s+(?:said|wrote|told))\b",
    re.IGNORECASE,
)
# A named place on the internet. Asked what Reddit says about someone, a model
# with no search will invent threads, complete with subreddit and date — the
# most confident wrong answer this system can produce.
_PLATFORM = re.compile(
    r"\b(reddit|subreddit|r/\w+|twitter|tweets?|x\.com|youtube|instagram|linkedin|"
    r"facebook|quora|tiktok|threads|github|stack\s?overflow|hacker\s?news|"
    r"wikipedia|imdb|online)\b",
    re.IGNORECASE,
)
# "about him", "what about that", "is he married" — a question that only makes
# sense as a continuation. On its own it looks like chat; straight after a
# search it is the second half of the same question.
_FOLLOW_UP_REF = re.compile(
    r"\b(he|him|his|she|her|hers|they|them|their|it|its|that|this|those|these)\b|"
    r"^\s*(and|also|what\s+about|how\s+about|any\b|is\s+there|are\s+there)",
    re.IGNORECASE,
)
_TOO_SHORT = 12
# "I watched a movie yesterday", "we went to goa last week" — someone telling
# you about their day. The time words in them are about the speaker, not about
# a fact that needs checking, and searching the web for an answer to a
# statement is how an assistant stops sounding like a person.
_PERSONAL_STATEMENT = re.compile(
    r"\b(i|we)\s+(?:just\s+|already\s+)?"
    r"(watched|saw|read|went|ate|drank|played|finished|started|bought|met|made|"
    r"feel|felt|think|thought|like|liked|love|loved|hate|hated|enjoyed|tried)\b",
    re.IGNORECASE,
)


def worth_searching(
    message: str, *, forced: bool = False, after_search: bool = False,
) -> bool:
    """Should this message be put to the decision model at all?

    ``forced`` is the user pressing the globe: they have said what they want,
    so no gate and no decision call stands between them and a search.

    ``after_search`` says the answer before this one was built from the web.
    A follow-up then inherits that: "is there any reddit post about him" reads
    as chat on its own, and the cost of treating it as chat is an answer
    invented from memory that contradicts the sourced one above it.
    """
    if forced:
        return True
    text = (message or "").strip()
    if not text:
        return False
    if _EXPLICIT.search(text) or _URL.search(text) or _WANTS_TO_SEE.search(text):
        return True
    if _PLATFORM.search(text):
        return True
    # "ok da", "thanks", "got it" — never worth a model call.
    if len(text) < _TOO_SHORT:
        return False
    if _SELF_REFERENTIAL.search(text):
        return False
    # A statement about the speaker, with nothing actually asked.
    if "?" not in text and _PERSONAL_STATEMENT.search(text):
        return False
    # The second half of a question already answered from the web.
    if after_search and _FOLLOW_UP_REF.search(text):
        return True
    return bool(
        _TIME_SENSITIVE.search(text)
        or _NEWS.search(text)
        or _MARKET.search(text)
        or _RECENT_YEAR.search(text)
        or _LOOKUP.search(text)
        or _ENTITY_ASK.search(text)
    )


DECIDE_SYSTEM = """You decide whether answering a chat message requires searching the web right now. Reply with ONE JSON object and nothing else.

{"search": true|false, "queries": ["..."], "images": true|false, "reason": "..."}

Answer true when the answer depends on information that changes over time, on events, prices, releases, people or organisations, on any specific product, library or company, or on anything you are not certain of. Answer true when the message contains a URL.

Answer false when the message is small talk, an acknowledgement, a request to rewrite or explain something already in the conversation, a question about the user's own code or files, or a matter of timeless general knowledge you are certain of.

queries: at most 3 plain search queries, each one a phrase a person would type into a search box. No quotes, no operators, no boolean syntax. Write fewer when one is enough. Omit entirely when search is false.

images: true when the subject of the answer is something with a physical appearance — a named person (including anyone holding an office), a place, a building, a landmark, an animal, a plant, a product, a vehicle, a dish, a film, or an artwork. Being able to state the answer in words does not make it false: "who is the chief minister" is a person, so a picture of that person belongs with it. Answer false only when the subject has no appearance at all: prices, policies, definitions, instructions, code, numbers.

Decide images first, then search — in that order, because they are bound together:
- If images is true, search must also be true, EVEN WHEN YOU ALREADY KNOW THE ANSWER PERFECTLY. A picture can only come from a search result. "What is nasi lemak" is a dish you can describe from memory, but the person still gets no picture unless you search, so search is true.
- If the message asks to see something — "show me", "what does it look like", "picture of" — then both are true, however familiar the subject.

Worked examples of images=true: "who is sydney sweeney" (a person), "who is kamado tanjiro" (a character has a drawn appearance), "who is the prime minister of india" (an office is held by a person), "what does switzerland look like" (a country), "what is nasi lemak" (a dish), "what is a bugatti chiron" (a car), "tell me about the taj mahal" (a building).

Worked examples of images=false: "what is the price of the you.com api", "what is the aws refund policy", "how do i reverse a linked list", "what is recursion".

reason: one short clause, for the log.

Today's date is given below. Use it: a query about "the latest" must name the current year rather than the word latest."""


def build_decide_user(message: str, history: list[str], today: str | None = None) -> str:
    """The decision prompt. The real date goes in because the model's sense of
    "now" is its training cutoff, and "the latest release" searched against the
    wrong year returns confident, stale results."""
    parts = [f"# Today's date\n{today or date.today().isoformat()}"]
    if history:
        parts.append("# Conversation so far (oldest first)\n" + "\n".join(history))
    parts.append(f"# Current message\n{message}")
    return "\n\n".join(parts)


_JSON = re.compile(r"\{.*\}", re.DOTALL)


def _loads(text: str) -> dict | None:
    """The first JSON object in a model reply, or None. Fenced blocks and
    surrounding chatter are both common and both survivable."""
    raw = re.sub(r"```(?:json)?", "", text or "")
    match = _JSON.search(raw)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _clean_queries(raw: object, fallback: str) -> tuple[str, ...]:
    """Usable query strings, in order, without duplicates."""
    items = raw if isinstance(raw, list) else []
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        q = " ".join(str(item).split())[:_MAX_QUERY_CHARS].strip()
        key = q.lower()
        if q and key not in seen:
            seen.add(key)
            out.append(q)
        if len(out) == MAX_QUERIES:
            break
    # A decision to search with no usable query is still a decision to search:
    # the user's own words are a serviceable query.
    if not out:
        cleaned = " ".join((fallback or "").split())[:_MAX_QUERY_CHARS].strip()
        return (cleaned,) if cleaned else ()
    return tuple(out)


def parse_plan(text: str, *, message: str) -> SearchPlan | None:
    """The model's decision as a plan, or None to answer without searching.

    Every doubtful case resolves to None. Searching is an improvement to an
    answer and must never be the reason there is no answer.
    """
    data = _loads(text)
    if data is None:
        return None
    if data.get("search") is not True:
        return None
    queries = _clean_queries(data.get("queries"), message)
    if not queries:
        return None
    return SearchPlan(
        queries=queries,
        reason=str(data.get("reason") or "")[:200],
        # Anything other than an explicit true means no picture: this field is
        # an addition to the answer, so a model that omits it gets the plain one.
        wants_images=data.get("images") is True,
    )


ENOUGH_SYSTEM = """You are told a question and what a web search returned for it. Decide whether the search results already contain the answer, or whether a page must be opened and read in full. Reply with ONE JSON object and nothing else.

{"enough": true|false, "read": ["url", "..."]}

Answer enough=true when the descriptions and extracts below let you answer accurately, and leave read empty.

Answer enough=false when the results point at the answer without containing it — a specification, an exact figure, a procedure, a list of fields, a policy detail. Then put at most 2 urls in read, copied exactly from the results, choosing the pages most likely to hold the missing detail.

Never invent a url. Only urls listed below may appear in read."""


def build_enough_user(message: str, sources: list) -> str:
    """Show the model what came back, compactly. Extracts are trimmed hard: this
    call decides where to look next, and does not need the whole page to do it."""
    lines = []
    for i, s in enumerate(sources, 1):
        body = " ".join((s.content or s.description or "").split())[:600]
        lines.append(f"[{i}] {s.title}\n{s.url}\n{body}")
    return f"# Question\n{message}\n\n# Search results\n" + "\n\n".join(lines)


def parse_reads(text: str, *, allowed: list[str]) -> tuple[str, ...]:
    """URLs to open in full: at most two, and only ones the search returned.

    A model that answers with a plausible-looking invented URL is the failure
    this guards against — we would fetch a page the search never found and
    treat whatever came back as evidence.
    """
    data = _loads(text)
    if data is None or data.get("enough") is not False:
        return ()
    raw = data.get("read")
    items = raw if isinstance(raw, list) else []
    permitted = {u.strip(): u for u in allowed}
    out: list[str] = []
    for item in items:
        url = str(item).strip()
        if url in permitted and url not in out:
            out.append(url)
        if len(out) == MAX_READS:
            break
    return tuple(out)
