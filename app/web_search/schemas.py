"""What a web search produces, as plain data.

Nothing here talks to a network or a model, so the shapes can be built in a test
without either. ``WebSource`` is the single currency of this package: the provider
returns them, the context builder reads them, the stream sends them to the browser
and the database stores them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

# A source card shows the domain, not the URL: "reuters.com" reads as a
# publisher, "https://www.reuters.com/markets/..." reads as noise.
_WWW = "www."


def domain_of(url: str) -> str:
    """The bare host of a URL, or "" when it has none worth showing."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[len(_WWW):] if host.startswith(_WWW) else host


# watch?v=ID, youtu.be/ID, /shorts/ID, /embed/ID — the eleven-character id is
# all a player needs. Anything else on YouTube (a channel, a search page) is
# not a video and is not offered as one.
_YOUTUBE_ID = re.compile(
    r"^https?://(?:(?:www|m)\.)?(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"
)


def youtube_id(url: str) -> str | None:
    """The video id of a YouTube video URL, or None for anything else."""
    match = _YOUTUBE_ID.match((url or "").strip())
    return match.group(1) if match else None


@dataclass(frozen=True, slots=True)
class WebSource:
    """One page the assistant looked at."""

    url: str
    title: str
    description: str = ""
    thumbnail_url: str | None = None
    favicon_url: str | None = None
    published: str | None = None
    #: The page text the model reads. Empty when only a snippet was available.
    content: str = ""

    @property
    def domain(self) -> str:
        return domain_of(self.url)

    def card(self) -> dict[str, str | None]:
        """The shape the browser renders. Deliberately without ``content``:
        a card carries a few hundred bytes, page text carries tens of
        thousands, and the browser never displays it."""
        return {
            "url": self.url,
            "title": self.title or self.domain or self.url,
            "domain": self.domain,
            "description": self.description,
            "thumbnail_url": self.thumbnail_url,
            "favicon_url": self.favicon_url,
            "published": self.published,
        }


@dataclass(frozen=True, slots=True)
class SearchPlan:
    """The decision to search, and what to search for."""

    queries: tuple[str, ...]
    #: Why the model thought this needs the web. Logged, never shown.
    reason: str = ""
    #: Would seeing a picture help answer this? A person, a place, a product —
    #: yes. A price, a policy, a definition — no. Decided in the same call that
    #: decides to search, so it costs nothing extra.
    wants_images: bool = False
    #: Asked for videos. They come from YouTube and nowhere else.
    wants_videos: bool = False


@dataclass(frozen=True, slots=True)
class SourceImage:
    """A picture shown with an answer, and the page it belongs to."""

    url: str
    source_url: str
    title: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"url": self.url, "source_url": self.source_url, "title": self.title}


@dataclass(slots=True)
class SearchOutcome:
    """What the service gathered, ready to be shown and to be read by the model."""

    sources: list[WebSource] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    #: URLs opened in full during the read round, a subset of ``sources``.
    read: list[str] = field(default_factory=list)
    #: The one or two pictures worth showing, empty when none would help.
    images: list[SourceImage] = field(default_factory=list)
    #: YouTube results shown as playable videos; also present in ``sources``,
    #: which is what stores them with the answer.
    videos: list[WebSource] = field(default_factory=list)
    #: The turn asked for pictures or videos, whether or not any were found.
    wanted_images: bool = False
    wanted_videos: bool = False
    #: The request was for sexually explicit material, so nothing was searched.
    blocked: bool = False

    def __bool__(self) -> bool:
        return bool(self.sources)

    @property
    def matters_to_the_reply(self) -> bool:
        """Is there anything here the answer must be told about?"""
        return bool(self.sources or self.blocked or self.wanted_images or self.wanted_videos)
