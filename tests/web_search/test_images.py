"""Telling a photograph from a logo, without looking at either.

Asked where Switzerland is, the assistant showed the World Population Review
brand plate: a correct preview of a relevant page, and a picture of nothing the
user asked about. These are the checks that stop that.
"""

from __future__ import annotations

import struct

from app.web_search.images import (
    MIN_WIDTH,
    dimensions,
    is_about_subject,
    is_photograph,
    looks_like_furniture,
    subject_words,
    vet,
)
from app.web_search.schemas import SourceImage


def png(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", width, height)


def gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height)


class TestFurniture:
    def test_a_share_image_at_the_domain_root_belongs_to_the_site(self):
        """This is the one that stood in for Switzerland."""
        assert looks_like_furniture("https://worldpopulationreview.com//og-image.png")

    def test_obvious_branding_is_named(self):
        for url in (
            "https://site.com/assets/logo-dark.png",
            "https://site.com/img/placeholder.jpg",
            "https://cdn.site.com/sprite.png",
            "https://site.com/default-thumb.png",
        ):
            assert looks_like_furniture(url), url

    def test_a_photograph_whose_words_merely_contain_a_junk_word_survives(self):
        """"supercar-icon-the-bugatti" was thrown away for containing "icon".
        Icons are small, so size catches them without losing this."""
        assert not looks_like_furniture(
            "https://www.autowin.com/cdn/shop/articles/supercar-icon-the-bugatti-chiron.jpg"
        )
        assert not looks_like_furniture(
            "https://static.foxnews.com/content/uploads/2026/09/sydney-sweeney.jpg"
        )


class TestDimensions:
    def test_png_and_gif_headers_are_read(self):
        assert dimensions(png(1280, 720)) == (1280, 720)
        assert dimensions(gif(640, 480)) == (640, 480)

    def test_anything_unreadable_is_unknown(self):
        """An SVG, or an HTML error page served as an image: not measurable,
        so not shown. What cannot be judged is not put in front of the user."""
        for data in (b"", b"<svg xmlns=", b"<!DOCTYPE html>", b"not an image at all"):
            assert dimensions(data) is None


class TestShape:
    def test_a_wide_picture_is_a_photograph(self):
        assert is_photograph(1280, 720)
        assert is_photograph(1200, 630)

    def test_a_square_is_a_logo_or_a_flag(self):
        """Britannica's Switzerland preview was a 1600x1600 flag. A flag is not
        what "how does it look" is asking for."""
        assert not is_photograph(1600, 1600)
        assert not is_photograph(630, 630)

    def test_a_tall_picture_is_not_a_scene(self):
        assert not is_photograph(1200, 1500)

    def test_a_small_picture_is_an_icon(self):
        assert not is_photograph(MIN_WIDTH - 1, 300)
        assert not is_photograph(800, 100)


class TestSubject:
    def test_question_words_are_not_the_subject(self):
        assert subject_words("Where is switzerland and how it's looks like ?") == {"switzerland"}

    def test_a_picture_whose_address_names_the_subject_qualifies(self):
        image = SourceImage(
            url="https://cdn.x.com/Satellite_image_of_Switzerland.jpg",
            source_url="https://x.com/page", title="Anything",
        )
        assert is_about_subject(image, {"switzerland"})

    def test_a_site_graphic_on_a_relevant_page_does_not(self):
        """The page was about Switzerland; the image was the publisher's own
        general-purpose graphic. Judging by the page is what let it through."""
        image = SourceImage(
            url="https://atlas.co/images/world-of-data.png",
            source_url="https://atlas.co/where-is-switzerland",
            title="Where is Switzerland located?",
        )
        assert not is_about_subject(image, {"switzerland"})

    def test_an_article_photograph_qualifies_when_its_page_names_the_subject(self):
        """News photographs are filed under a date or behind a CDN id, and
        their names are rarely the subject — so the page title has to be."""
        for url in (
            "https://static.foxnews.com/content/uploads/2026/09/abc123.jpg",
            "https://s.yimg.com/lo/mysterio/api/650c07ee129e920bb9e3f4314c775f25bd485cb0.jpg",
            "https://cdn.shop.com/articles/how-to-make-it.png?v=1699",
        ):
            image = SourceImage(url=url, source_url="https://x.com/a",
                                title="Ten days in Switzerland")
            assert is_about_subject(image, {"switzerland"}), url

    def test_an_article_photograph_about_something_else_does_not(self):
        """"Which places in Germany": a Swiss ski resort and an airport-malaria
        mosquito were shown, both filed like article photos, neither about
        Germany."""
        words = subject_words("Germany travel destinations 2026")
        assert words == {"germany"}
        for url, title in (
            ("https://imageio.forbes.com/specials-images/imageserve/6512ab34cd56ef7890123456/0x0.jpg",
             "Andermatt, Switzerland Is Changing The Concept Of Traditional Ski Resorts"),
            ("https://static.foxnews.com/content/uploads/2026/09/mosquito.jpg",
             "3 dead in rare 'airport malaria' outbreak linked to one of world's busiest hubs"),
        ):
            assert not is_about_subject(SourceImage(url=url, source_url="https://x.com", title=title), words)

    async def test_nothing_related_means_no_picture_rather_than_the_top_result(self):
        unrelated = SourceImage(
            url="https://static.foxnews.com/content/uploads/2026/09/mosquito.jpg",
            source_url="https://foxnews.com/a", title="Airport malaria outbreak",
        )
        assert await vet([unrelated], query="Germany travel destinations 2026") == []

    def test_with_no_subject_every_picture_qualifies(self):
        image = SourceImage(url="https://x.com/a.png", source_url="https://x.com", title="t")
        assert is_about_subject(image, set())
