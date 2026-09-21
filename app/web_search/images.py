"""Choosing a picture that is actually about the thing.

Search results carry one preview image per page, and a page's preview is often
its publisher's logo rather than a photograph of the subject. Asked where
Switzerland is, the best-ranked result offered its own brand plate — a correct
picture of nothing the user asked about.

Three things separate a photograph from a logo, and all three can be read from
the first few kilobytes of the file:

* **Shape.** A logo is square or nearly so; a photograph is wide. Flags are
  square too, and a flag is not what "how does it look" means.
* **Size.** Brand assets and icons are small. A real photograph is not.
* **Whether it loads at all.** Several image hosts refuse requests that did not
  come from their own page, so the picture would have arrived in the browser as
  a broken box. Reading the header proves it will load.

The check costs one small ranged request per candidate, run concurrently, and
it is the difference between a picture that explains the answer and a logo.
"""

from __future__ import annotations

import asyncio
import re
import struct

import httpx
from loguru import logger

from app.web_search.schemas import SourceImage

#: A photograph is wider than it is tall, but not a banner strip.
MIN_RATIO = 1.15
MAX_RATIO = 3.0
#: Below this, it is an icon, an avatar or a badge.
MIN_WIDTH = 400
MIN_HEIGHT = 220
#: Enough for any header this reads; images are never downloaded whole.
_HEAD_BYTES = 65536
_TIMEOUT = 6.0

# Site-wide furniture rather than a picture of anything: a share image at the
# domain root, a logo, a placeholder, a sprite.
# Only terms that are furniture wherever they appear. "icon" and "banner" were
# here and matched "supercar-icon-the-bugatti", a perfectly good photograph;
# icons are small, so the size check catches them without the false positive.
_JUNK = re.compile(
    r"(logo|sprite|favicon|avatar|placeholder|watermark|default[-_.]|"
    r"no[-_]?image|image[-_]?missing)",
    re.IGNORECASE,
)
# "https://site.com//og-image.png" — one path segment, so it belongs to the
# site, not to the page that was found.
_ROOT_SHARE = re.compile(r"^https?://[^/]+/+[^/]+\.(png|jpe?g|webp|gif)$", re.IGNORECASE)


def looks_like_furniture(url: str) -> bool:
    """Is this the site's own branding rather than a picture of the subject?"""
    return bool(_JUNK.search(url) or _ROOT_SHARE.match(url))


_STOP = {"what", "where", "when", "which", "does", "look", "looks", "looking",
         "like", "about", "the", "and", "for", "with", "from", "this", "that",
         "there", "here", "some", "give", "show", "tell", "located", "location",
         "picture", "pictures", "image", "images", "photo", "photos", "latest",
         "many", "much", "really", "actually",
         # Words that describe the kind of search, not the thing searched for.
         # "Germany travel destinations 2026" is about Germany; with "travel"
         # counted as a subject, a Swiss ski-resort photo on a travel page
         # passed as a picture of Germany.
         "travel", "destinations", "destination", "places", "place", "best",
         "guide", "guides", "trip", "trips", "visit", "visiting", "tourism",
         "tourist", "things", "beautiful", "famous", "popular", "suggest",
         "suggestions", "most", "news", "today", "photography"}


def subject_words(query: str) -> set[str]:
    """The words of a query that name the thing being asked about."""
    return {w for w in re.findall(r"[a-z]{4,}", (query or "").lower()) if w not in _STOP}


# A picture that belongs to one article rather than to the whole site: it was
# uploaded in some year, or filed under an article, or given a long unique id
# by a CDN.
_SPECIFIC_PATH = re.compile(
    r"(/(19|20)\d{2}/|/(articles?|gallery|galleries|media|photos?|content)/|"
    r"/[0-9a-f]{16,}|[?&](v|cb|w|width|crop|resize)=)",
    re.IGNORECASE,
)


def is_about_subject(image: SourceImage, words: set[str]) -> bool:
    """Does the picture connect to what was asked?

    A picture qualifies when its own address names the subject, or when it is
    an article's own photograph (filed under a year, an articles path or a
    long CDN id) *on a page whose title names the subject*.

    Both halves of the second rule were learned the hard way. Judging by the
    page alone let a publisher's "world-of-data.png" through as a picture of
    Switzerland — relevant page, generic graphic. Judging by the file path
    alone let any news photograph through: "places to visit in Germany"
    showed a Swiss ski resort and an "airport malaria" mosquito, both filed
    exactly like article photos, on pages that never mentioned Germany.
    """
    if not words:
        return True
    url = image.url.lower()
    if any(word in url for word in words):
        return True
    title = (image.title or "").lower()
    return bool(_SPECIFIC_PATH.search(image.url)) and any(word in title for word in words)


def dimensions(data: bytes) -> tuple[int, int] | None:
    """Width and height from an image header, or None if it cannot be read.

    Covers PNG, JPEG, GIF and WEBP. Anything else — an SVG, an HTML error page
    served with an image content type — returns None and is not shown, because
    what cannot be measured cannot be judged.
    """
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            width, height = struct.unpack(">II", data[16:24])
            return int(width), int(height)
        if data[:3] == b"\xff\xd8\xff":
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB):
                    height, width = struct.unpack(">HH", data[i + 5:i + 9])
                    return int(width), int(height)
                i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
            return None
        if data[:6] in (b"GIF87a", b"GIF89a"):
            width, height = struct.unpack("<HH", data[6:10])
            return int(width), int(height)
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            chunk = data[12:16]
            if chunk == b"VP8X":
                width = int.from_bytes(data[24:27], "little") + 1
                height = int.from_bytes(data[27:30], "little") + 1
                return width, height
            if chunk == b"VP8 ":
                width = int.from_bytes(data[26:28], "little") & 0x3FFF
                height = int.from_bytes(data[28:30], "little") & 0x3FFF
                return width, height
            if chunk == b"VP8L":
                bits = int.from_bytes(data[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    except Exception:  # noqa: BLE001 - a malformed header is simply unreadable
        return None
    return None


def is_photograph(width: int, height: int) -> bool:
    """Wide enough and big enough to be a picture of something."""
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        return False
    ratio = width / height
    return MIN_RATIO <= ratio <= MAX_RATIO


async def _inspect(client: httpx.AsyncClient, image: SourceImage) -> SourceImage | None:
    """The image, if its header says it is a usable photograph."""
    try:
        response = await client.get(
            image.url,
            headers={"Range": f"bytes=0-{_HEAD_BYTES - 1}", "Accept": "image/*"},
        )
    except httpx.HTTPError as e:
        logger.debug(f"Image unreachable ({type(e).__name__}): {image.url[:80]}")
        return None
    if response.status_code >= 400:
        # 403 here is a host refusing to serve the picture to anyone but its
        # own pages; in the browser it would have been a broken box.
        logger.debug(f"Image refused ({response.status_code}): {image.url[:80]}")
        return None
    size = dimensions(response.content)
    if size is None:
        logger.debug(f"Image header unreadable: {image.url[:80]}")
        return None
    width, height = size
    if not is_photograph(width, height):
        logger.debug(f"Image rejected ({width}x{height}): {image.url[:80]}")
        return None
    return image


async def vet(
    candidates: list[SourceImage], *, limit: int = 2, query: str = "",
) -> list[SourceImage]:
    """The candidates worth showing, best-ranked first.

    Obvious branding is dropped without a request, and so is anything with no
    visible connection to the subject. The rest are inspected together, because
    they are independent and the user is waiting.

    Showing nothing is a valid outcome: an answer with no picture reads fine,
    while an answer beside a stranger's logo reads as a mistake.
    """
    words = subject_words(query)
    # Nothing related means no picture. Falling back to the best-ranked
    # preview is what put a mosquito above a trip to Germany.
    usable = [
        c for c in candidates
        if not looks_like_furniture(c.url) and is_about_subject(c, words)
    ]
    if not usable:
        return []
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, follow_redirects=True,
        ) as client:
            checked = await asyncio.gather(
                *(_inspect(client, c) for c in usable), return_exceptions=True
            )
    except Exception as e:  # noqa: BLE001 - pictures are never worth a failed turn
        logger.warning(f"Could not vet images ({e}); showing none")
        return []
    out = [c for c in checked if isinstance(c, SourceImage)]
    return out[:limit]
