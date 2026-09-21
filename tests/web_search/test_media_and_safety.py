"""Pictures, YouTube videos, and keeping explicit material out of both."""

from __future__ import annotations

import pytest

from app.cognitive_integration.pipeline import _STYLE_REMINDER, _stream_history
from app.web_search.context import screen_note, with_outcome
from app.web_search.decision import asks_for_pictures, asks_for_videos, parse_plan
from app.web_search.safety import asks_for_explicit, clean, is_explicit_source
from app.web_search.schemas import SearchOutcome, SourceImage, WebSource, youtube_id
from app.web_search.service import WebSearchService, pick_images

PAGE = WebSource(url="https://frenchmoments.eu/lake-annecy/", title="Lake Annecy",
                 thumbnail_url="https://frenchmoments.eu/uploads/2014/05/annecy.jpg")
VIDEO = WebSource(url="https://www.youtube.com/watch?v=M4tj_1LXRCk", title="The magic of Annecy",
                  thumbnail_url="https://i.ytimg.com/vi/M4tj_1LXRCk/maxresdefault.jpg")
OTHER_VIDEO_SITE = WebSource(url="https://www.dailymotion.com/video/x8abc", title="Annecy clip")


async def _always_allowed(_cap):
    return True


class TestYouTubeIds:
    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=M4tj_1LXRCk",
        "https://youtube.com/watch?feature=share&v=M4tj_1LXRCk",
        "https://m.youtube.com/watch?v=M4tj_1LXRCk",
        "https://youtu.be/M4tj_1LXRCk?t=30",
        "https://www.youtube.com/shorts/M4tj_1LXRCk",
    ])
    def test_every_video_url_shape_yields_the_id(self, url):
        assert youtube_id(url) == "M4tj_1LXRCk"

    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/@frenchmoments",
        "https://www.youtube.com/results?search_query=annecy",
        "https://notyoutube.com/watch?v=M4tj_1LXRCk",
        "https://www.dailymotion.com/video/x8abc",
    ])
    def test_anything_that_is_not_a_youtube_video_is_not_one(self, url):
        assert youtube_id(url) is None


class TestExplicitFilter:
    @pytest.mark.parametrize("message", [
        "show me porn videos", "send nudes", "nude pics of her", "xxx clips",
        "sex tape of the actress", "onlyfans leaks", "hentai images",
    ])
    def test_explicit_requests_are_recognised(self, message):
        assert asks_for_explicit(message)

    @pytest.mark.parametrize("message", [
        "show me pictures of Annecy", "what is Essex famous for", "nude lipstick shades",
        "visible to the naked eye", "sex education curriculum in india", "blue tit bird",
    ])
    def test_ordinary_requests_are_not(self, message):
        assert not asks_for_explicit(message)

    def test_explicit_hosts_and_titles_are_dropped(self):
        bad_host = WebSource(url="https://www.pornhub.com/view?x=1", title="Annecy")
        bad_title = WebSource(url="https://example.com/a", title="Nude pics leaked")
        bad_thumb = WebSource(url="https://example.com/b", title="Lake",
                              thumbnail_url="https://cdn.xvideos.com/t.jpg")
        assert all(is_explicit_source(s) for s in (bad_host, bad_title, bad_thumb))
        assert clean([bad_host, PAGE, bad_title, VIDEO, bad_thumb]) == [PAGE, VIDEO]


class TestAskingToSee:
    @pytest.mark.parametrize("message", [
        "Can you show some images of that", "show me pictures of annecy",
        "photos of the eiffel tower", "what does lake annecy look like",
    ])
    def test_picture_requests(self, message):
        assert asks_for_pictures(message)

    @pytest.mark.parametrize("message", [
        "show me some videos of annecy", "any youtube video on this?", "trailer for dune 3",
    ])
    def test_video_requests(self, message):
        assert asks_for_videos(message)

    def test_a_request_to_see_is_honoured_even_when_the_model_says_no_search(self):
        plan = parse_plan('{"search": false}', message="show me some videos of annecy")
        assert plan is not None and plan.wants_videos

    def test_the_model_can_ask_for_videos_itself(self):
        plan = parse_plan('{"search": true, "queries": ["annecy"], "videos": true}',
                          message="what is it like in annecy")
        assert plan is not None and plan.wants_videos and not plan.wants_images


class TestPictures:
    def test_a_youtube_frame_is_not_also_offered_as_a_picture(self):
        assert [i.source_url for i in pick_images([VIDEO, PAGE])] == [PAGE.url]


class VideoProvider:
    """Ordinary results for the main query; YouTube results for the video one."""

    def __init__(self, main, videos):
        self.main, self.videos, self.searched = main, videos, []

    async def search(self, query, *, count):
        self.searched.append(query)
        return list(self.videos if "site:youtube.com" in query else self.main)

    async def contents(self, urls):
        return {}


def replies(*texts):
    queue = list(texts)

    async def complete(*, system, user):
        return queue.pop(0) if queue else "{}"

    return complete


async def drain(service, message):
    events = [e async for e in service.run(message)]
    return events, events[-1]["outcome"]


class TestService:
    async def test_an_explicit_request_is_never_searched(self, monkeypatch):
        monkeypatch.setattr("app.web_search.budget.claim_search", _always_allowed)
        provider = VideoProvider([PAGE], [VIDEO])

        async def must_not_run(*, system, user):  # pragma: no cover
            raise AssertionError("an explicit request reached the decision model")

        _, outcome = await drain(WebSearchService(provider, complete=must_not_run),
                                 "show me nude pics of that actress")
        assert provider.searched == []
        assert outcome.blocked and not outcome.sources

    async def test_videos_come_from_youtube_only(self, monkeypatch):
        monkeypatch.setattr("app.web_search.budget.claim_search", _always_allowed)
        provider = VideoProvider([PAGE, OTHER_VIDEO_SITE], [VIDEO, OTHER_VIDEO_SITE])
        service = WebSearchService(provider, complete=replies(
            '{"search": true, "queries": ["Lake Annecy"], "videos": true}', '{"enough": true}'))
        _, outcome = await drain(service, "show me some videos of lake annecy")
        assert "Lake Annecy site:youtube.com" in provider.searched
        assert outcome.videos == [VIDEO]
        # Stored with the answer, so the videos survive a reload.
        assert VIDEO in outcome.sources

    async def test_explicit_results_never_reach_the_answer(self, monkeypatch):
        monkeypatch.setattr("app.web_search.budget.claim_search", _always_allowed)
        bad = WebSource(url="https://www.xhamster.com/videos/annecy", title="Annecy")
        service = WebSearchService(VideoProvider([bad, PAGE], []), complete=replies(
            '{"search": true, "queries": ["annecy"]}', '{"enough": true}'))
        _, outcome = await drain(service, "what is the latest news in annecy today")
        assert outcome.sources == [PAGE]


class TestWhatTheModelIsTold:
    def test_shown_pictures_are_announced_in_the_final_turn(self):
        outcome = SearchOutcome(sources=[PAGE], images=[SourceImage(PAGE.thumbnail_url, PAGE.url)])
        out = with_outcome(_stream_history(()), outcome)
        assert out[-1]["content"].startswith(_STYLE_REMINDER["content"])
        assert "1 picture is on screen" in out[-1]["content"]

    def test_pictures_wanted_but_none_found_is_said_as_this_search_only(self):
        note = screen_note(SearchOutcome(sources=[PAGE], wanted_images=True))
        assert "this one search simply found none" in note

    def test_videos_are_named_for_the_model(self):
        note = screen_note(SearchOutcome(sources=[VIDEO], videos=[VIDEO]))
        assert "1 YouTube video is on screen" in note and "The magic of Annecy" in note

    def test_a_blocked_request_reaches_the_model_without_any_sources(self):
        out = with_outcome(_stream_history(()), SearchOutcome(blocked=True))
        assert "sexually explicit" in out[-1]["content"]
        assert len(out) == 1

    def test_nothing_to_say_leaves_the_history_alone(self):
        history = _stream_history(())
        assert with_outcome(history, SearchOutcome()) == history
