"""The gate and the parsers: what reaches the search, and what a bad reply cannot do."""

from __future__ import annotations

import json

from app.web_search.decision import (
    MAX_QUERIES,
    build_decide_user,
    build_enough_user,
    parse_plan,
    parse_reads,
    worth_searching,
)
from app.web_search.schemas import WebSource


class TestWorthSearching:
    def test_ordinary_chat_never_costs_a_model_call(self):
        for message in ("ok da", "thanks", "got it", "nice", "hmm", "ok da got it"):
            assert worth_searching(message) is False, message

    def test_questions_about_the_conversation_stay_in_the_conversation(self):
        """The assistant already holds these; the web has nothing to add."""
        for message in (
            "explain this code properly to me",
            "why did you write this function like that",
            "summarise my document for me please",
            "rewrite the previous answer shorter",
        ):
            assert worth_searching(message) is False, message

    def test_time_sensitive_questions_pass(self):
        for message in (
            "what is the latest version of next js",
            "what happened in the news today about tariffs",
            "is the weather good in singapore tomorrow",
        ):
            assert worth_searching(message) is True, message

    def test_prices_and_lookups_pass(self):
        for message in (
            "how much does the you.com api cost per search",
            "who is the ceo of nvidia right now",
            "compare tavily vs brave search api for an agent",
        ):
            assert worth_searching(message) is True, message

    def test_comparisons_recommendations_and_versions_pass(self):
        """All three were rejected by the first version of the gate. A product
        comparison and a recommendation both date badly, and a library version
        answered from memory is answered wrong."""
        for message in (
            "is claude opus 5 better than gpt 5 for coding",
            "give me the best hotels in bali",
            "our vision ai project need onnx runtime version",
        ):
            assert worth_searching(message) is True, message

    def test_a_year_the_model_cannot_know_passes(self):
        assert worth_searching("what were the biggest ai releases of 2026") is True

    def test_a_named_thing_reaches_the_decision_model(self):
        """These were rejected as chat, so a question about a person, a dish or
        a car never got as far as deciding whether to show a picture of it."""
        for message in (
            "who is kamado tanjiro",
            "who is sydney sweeney",
            "what is nasi lemak",
            "machaa what is bugatti chiron",
            "tell me about the taj mahal da",
            "what are the northern lights",
        ):
            assert worth_searching(message) is True, message

    def test_telling_the_assistant_about_your_day_is_not_a_question(self):
        """"I watched a movie yesterday" reached the model only because of the
        word yesterday — a time word about the speaker, not about a fact."""
        for message in (
            "i watched a movie yesterday da",
            "we went to goa last week machaa",
            "i just finished that novel da , it was good",
        ):
            assert worth_searching(message) is False, message

    def test_but_a_question_inside_a_personal_sentence_still_counts(self):
        assert worth_searching("i watched a movie yesterday, who is the lead actor?") is True

    def test_asking_to_see_something_always_passes(self):
        """These were rejected as small talk, so no search ran and no picture
        could appear — the one thing asked for was the one thing unreachable."""
        for message in (
            "show me the eiffel tower",
            "what does a red panda look like",
            "send me some pictures of kodaikanal",
        ):
            assert worth_searching(message) is True, message

    def test_a_named_website_always_passes(self):
        """Asked what Reddit says about someone with no search, the model
        invented threads — subreddit, date and all — and used them to
        contradict the sourced answer directly above it."""
        for message in (
            "is there any reddit post about him ?",
            "what do people say about him online",
            "any tweets about this da",
            "check his imdb page",
        ):
            assert worth_searching(message) is True, message

    def test_a_follow_up_to_a_searched_answer_searches_too(self):
        """On its own each of these reads as chat. Straight after a search they
        are the second half of the same question, and answering them from
        memory is how a grounded conversation turns into an invented one."""
        for message in (
            "is there any reddit post about him ?",
            "what about his education",
            "is he married?",
            "and his family?",
        ):
            assert worth_searching(message, after_search=True) is True, message

    def test_the_same_follow_up_without_a_search_behind_it_stays_chat(self):
        """The inheritance is from the previous answer, not from the wording."""
        assert worth_searching("what about his education") is False
        assert worth_searching("is he married?") is False

    def test_a_follow_up_after_a_search_is_still_not_an_essay_prompt(self):
        """"ok da" after a search is still an acknowledgement."""
        assert worth_searching("ok da", after_search=True) is False
        assert worth_searching("thanks machaa", after_search=True) is False

    def test_a_url_always_passes_however_short(self):
        """Pasting a link is asking about that page, and the gate's length floor
        must not swallow it."""
        assert worth_searching("https://you.com/docs") is True

    def test_asking_in_so_many_words_always_passes(self):
        assert worth_searching("search this da") is True
        assert worth_searching("google it and tell me") is True

    def test_the_globe_button_overrides_every_rule(self):
        """The user has said what they want; no gate stands in front of it."""
        assert worth_searching("ok da", forced=True) is True
        assert worth_searching("", forced=True) is True


class TestParsePlan:
    def test_a_decision_to_search_becomes_a_plan(self):
        plan = parse_plan(
            '{"search": true, "queries": ["nvidia ceo 2026"], "reason": "changes"}',
            message="who is the nvidia ceo",
        )
        assert plan is not None
        assert plan.queries == ("nvidia ceo 2026",)
        assert plan.reason == "changes"

    def test_a_decision_not_to_search_is_no_plan(self):
        assert parse_plan('{"search": false}', message="hi") is None

    def test_fenced_json_and_surrounding_chatter_survive(self):
        text = 'Sure!\n```json\n{"search": true, "queries": ["a b"]}\n```\nHope that helps.'
        plan = parse_plan(text, message="x")
        assert plan is not None and plan.queries == ("a b",)

    def test_malformed_replies_answer_without_searching(self):
        """Searching improves an answer; it must never be why there is no answer."""
        for text in ("", "not json at all", "{broken", "[]", '{"search": "yes"}'):
            assert parse_plan(text, message="x") is None, text

    def test_queries_are_capped_deduplicated_and_tidied(self):
        plan = parse_plan(
            '{"search": true, "queries": ["  a   query ", "A QUERY", "two", "three", "four"]}',
            message="x",
        )
        assert plan is not None
        assert plan.queries == ("a query", "two", "three")
        assert len(plan.queries) <= MAX_QUERIES

    def test_searching_with_no_usable_query_falls_back_to_the_users_words(self):
        """The model said the web is needed; an empty query list is a formatting
        failure, not a reason to discard a correct decision."""
        plan = parse_plan('{"search": true, "queries": []}', message="latest nvidia news")
        assert plan is not None and plan.queries == ("latest nvidia news",)


class TestImageDecision:
    def test_the_prompt_ties_pictures_to_searching(self):
        """The model answered images=true with search=false, which shows
        nothing: pictures are taken from search results."""
        from app.web_search.decision import DECIDE_SYSTEM

        assert "If images is true, search must also be true" in DECIDE_SYSTEM

    def test_knowing_the_answer_is_not_a_reason_to_show_nothing(self):
        """"What is nasi lemak" returned search=false — the model knew the dish,
        so it did not search, so there was no picture of the dish to show."""
        from app.web_search.decision import DECIDE_SYSTEM

        assert "EVEN WHEN YOU ALREADY KNOW THE ANSWER PERFECTLY" in DECIDE_SYSTEM
        assert "Decide images first, then search" in DECIDE_SYSTEM

    def test_the_prompt_says_an_office_holder_is_still_a_person(self):
        """"Who is the chief minister" was read as a fact question, so it
        returned no picture of the person it named."""
        from app.web_search.decision import DECIDE_SYSTEM

        assert "including anyone holding an office" in DECIDE_SYSTEM

    def test_a_plan_carries_the_decision(self):
        plan = parse_plan(
            '{"search": true, "queries": ["q"], "images": true}', message="who is x"
        )
        assert plan is not None and plan.wants_images is True

    def test_anything_but_an_explicit_true_means_no_pictures(self):
        for body in (
            '{"search": true, "queries": ["q"]}',
            '{"search": true, "queries": ["q"], "images": false}',
            '{"search": true, "queries": ["q"], "images": "yes"}',
            '{"search": true, "queries": ["q"], "images": 1}',
        ):
            plan = parse_plan(body, message="x")
            assert plan is not None and plan.wants_images is False, body


class TestSubjectQuery:
    """What gets searched when someone asks to see something: the thing, not
    the asking. "show me pictures of" is not what the pictures are of."""

    def test_the_asking_is_stripped_off(self):
        from app.web_search.decision import subject_query

        cases = {
            "show me pictures of Lake Annecy": "Lake Annecy",
            "what does a red panda look like": "a red panda",
            "can you show me some photos of kerala da": "kerala",
            "pictures of the eiffel tower pls": "the eiffel tower",
            "show me a video of the matterhorn": "the matterhorn",
        }
        for message, subject in cases.items():
            assert subject_query(message) == subject, message


class TestParseReads:
    urls = ["https://a.com/one", "https://b.com/two"]

    def test_enough_results_read_nothing_further(self):
        assert parse_reads('{"enough": true, "read": []}', allowed=self.urls) == ()

    def test_named_pages_are_returned_in_order(self):
        text = '{"enough": false, "read": ["https://b.com/two", "https://a.com/one"]}'
        assert parse_reads(text, allowed=self.urls) == ("https://b.com/two", "https://a.com/one")

    def test_an_invented_url_is_never_fetched(self):
        """A model that answers with a plausible URL the search never returned
        would have us fetch a page and treat it as evidence."""
        text = '{"enough": false, "read": ["https://evil.example/made-up"]}'
        assert parse_reads(text, allowed=self.urls) == ()

    def test_at_most_two_pages_are_opened(self):
        allowed = [f"https://s{i}.com" for i in range(5)]
        text = json.dumps({"enough": False, "read": allowed})
        assert len(parse_reads(text, allowed=allowed)) == 2

    def test_a_broken_reply_reads_nothing(self):
        for text in ("", "nonsense", "{", '{"enough": false}'):
            assert parse_reads(text, allowed=self.urls) == (), text


class TestPrompts:
    def test_the_decision_prompt_carries_the_real_date(self):
        """Without it, "the latest" is searched against the training cutoff and
        returns confident, stale results."""
        assert "2026-09-21" in build_decide_user("what is new", [], today="2026-09-21")

    def test_the_read_prompt_shows_each_result_with_its_url(self):
        sources = [WebSource(url="https://a.com/x", title="A", description="about a")]
        prompt = build_enough_user("q", sources)
        assert "https://a.com/x" in prompt and "about a" in prompt

    def test_extracts_are_trimmed_so_the_check_stays_cheap(self):
        sources = [WebSource(url="https://a.com", title="A", content="word " * 5000)]
        assert len(build_enough_user("q", sources)) < 1500
