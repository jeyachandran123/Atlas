"""Keeping sexually explicit material out of what search brings back.

Two layers, because neither is enough alone:

* The provider is asked for ``safesearch: strict``. You.com accepts the field
  but does not reject a bad value, so there is no proof it is honoured — it is
  a first filter, not the guarantee.
* Everything is checked here before it can reach the screen or the model: a
  request for explicit material is never searched at all, and any result whose
  address, title or description is explicit is dropped.

The word lists are deliberately phrases rather than single words where a word
has an ordinary meaning too: "nude lipstick", "naked eye", "Essex" and a blue
tit are not what this is for. A false positive here costs one search result;
a false negative puts pornography in front of a user, so the lists lean strict
on everything that has no innocent reading.
"""

from __future__ import annotations

import re

from app.web_search.schemas import WebSource, domain_of

_EXPLICIT = re.compile(
    r"\b("
    r"porn\w*|xxx|nsfw|hentai|rule\s?34|onlyfans|only\s?fans|fansly|"
    r"nudes|nudity|nude\s+(?:pics?|photos?|images?|videos?|scenes?|leaks?|girls?|"
    r"women|woman|men|man|models?|selfies?)|naked\s+(?:pics?|photos?|images?|"
    r"videos?|girls?|women|woman|men|man|body|bodies|selfies?)|"
    r"sex\s?(?:videos?|tapes?|clips?|scenes?|cams?|chats?|pics?|photos?|images?|movies?)|"
    r"having\s+sex|erotic\w*|blowjobs?|handjobs?|camgirls?|cam\s?sex|"
    r"milf|dick\s?pics?|boobs|topless|striptease|bdsm|xvideos|xnxx|xhamster"
    r")\b",
    re.IGNORECASE,
)

# Hosts that exist to serve explicit material. A substring match on the host is
# right for these: nothing innocent is called "pornhub" or "xhamster".
_EXPLICIT_HOST = re.compile(
    r"(porn|xxx|xvideos|xnxx|xhamster|redtube|youporn|spankbang|onlyfans|fansly|"
    r"chaturbate|stripchat|brazzers|rule34|hentai|eporner|tube8|motherless|"
    r"livejasmin|bongacams|camsoda|erome)",
    re.IGNORECASE,
)


def asks_for_explicit(message: str) -> bool:
    """Is this a request for sexually explicit material?"""
    return bool(_EXPLICIT.search(message or ""))


def is_explicit_source(source: WebSource) -> bool:
    """Would showing this result, or its preview image, show explicit material?"""
    if _EXPLICIT_HOST.search(source.domain or domain_of(source.url)):
        return True
    for url in (source.thumbnail_url, source.url):
        if url and _EXPLICIT_HOST.search(domain_of(url)):
            return True
    text = f"{source.title} {source.description} {source.url}"
    return bool(_EXPLICIT.search(text))


def clean(sources: list[WebSource]) -> list[WebSource]:
    """The results with every explicit one removed, order kept."""
    return [s for s in sources if not is_explicit_source(s)]
