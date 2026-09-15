"""The chat file flow's decisions: when to look, what to build, when to ask first."""

from __future__ import annotations

import json

from app.chat_artifacts.decision import parse, worth_deciding
from app.chat_artifacts.service import CLARIFIER, FILE_ARTIFACT, session_text


def decision(**fields) -> str:
    return json.dumps(fields)


def opts(*labels):
    return [{"label": x, "description": ""} for x in labels]


class TestGate:
    def test_asking_for_a_file_is_looked_at(self):
        assert worth_deciding("Can you genarate this as a pdf file for me",
                              has_spreadsheet=False, after_clarifier=False)
        assert worth_deciding("create one excel file with all anime from the last five years",
                              has_spreadsheet=False, after_clarifier=False)

    def test_typos_of_generate_are_still_a_file_request(self):
        for msg in ("now genearate excel file", "genrate a pdf report", "generete the csv file"):
            assert worth_deciding(msg, has_spreadsheet=False, after_clarifier=False), msg

    def test_naming_the_format_of_the_answer_is_a_file_request(self):
        # The message that once got "I can't make .xlsx files" from ordinary chat.
        assert worth_deciding(
            "ok you listed the 50 items right now you have to give this exact thing as a "
            "excel file da now genearate excel file",
            has_spreadsheet=False, after_clarifier=False,
        )
        for msg in ("send me that list in excel", "put the plan into a pdf", "give this as an excel"):
            assert worth_deciding(msg, has_spreadsheet=False, after_clarifier=False), msg

    def test_a_follow_up_right_after_a_file_is_looked_at(self):
        # The message that got a raw JSON "file" from ordinary chat.
        msg = "Nice then we go with phase three now write the phase 3 analyse"
        assert not worth_deciding(msg, has_spreadsheet=False, after_clarifier=False)
        assert worth_deciding(msg, has_spreadsheet=False, after_clarifier=False, after_file=True)
        for follow_up in ("same for chapter 2", "do the next one", "now make part 4"):
            assert worth_deciding(follow_up, has_spreadsheet=False, after_clarifier=False, after_file=True), follow_up

    def test_small_talk_after_a_file_is_not(self):
        for msg in ("thanks!", "great, looks good", "who wrote the theory of relativity?"):
            assert not worth_deciding(msg, has_spreadsheet=False, after_clarifier=False, after_file=True), msg

    def test_write_with_a_file_word_is_a_file_request(self):
        assert worth_deciding("write a pdf report on solar energy", has_spreadsheet=False, after_clarifier=False)

    def test_ordinary_chat_is_not(self):
        for msg in ("hey there", "what is a pdf?", "explain velocity", "thanks!",
                    "what's new in python 3.13", "how do I get better at cooking"):
            assert not worth_deciding(msg, has_spreadsheet=False, after_clarifier=False), msg

    def test_a_question_about_an_attached_sheet_is_looked_at(self):
        assert worth_deciding("how many dishes are halal?", has_spreadsheet=True, after_clarifier=False)
        assert not worth_deciding("thanks", has_spreadsheet=True, after_clarifier=False)

    def test_answering_questions_is_always_looked_at(self):
        assert worth_deciding("1. Japanese only", has_spreadsheet=False, after_clarifier=True)


class TestParse:
    kw = dict(message="make it", has_spreadsheet=False, after_clarifier=False)

    def test_no_file_means_chat(self):
        assert parse(decision(action="none"), **self.kw) is None

    def test_garbage_means_chat(self):
        assert parse("not json at all", **self.kw) is None

    def test_a_ready_request_becomes_a_build(self):
        p = parse(decision(action="create", format="excel", source="knowledge", ready=True,
                           title="Anime 2021-2025", brief="One row per title."), **self.kw)
        assert (p.action, p.format, p.source, p.brief) == ("create", "excel", "knowledge", "One row per title.")

    def test_fenced_json_is_accepted(self):
        p = parse("```json\n" + decision(action="create", format="pdf", ready=True) + "\n```", **self.kw)
        assert p is not None and p.format == "pdf"

    def test_format_aliases_are_understood(self):
        assert parse(decision(action="create", format="xlsx", ready=True), **self.kw).format == "excel"
        assert parse(decision(action="create", format="docx", ready=True), **self.kw).format == "word"

    def test_an_unknown_format_gets_a_sensible_default(self):
        assert parse(decision(action="create", format="pptx", ready=True), **self.kw).format == "pdf"

    def test_an_unclear_request_asks_first(self):
        p = parse(decision(action="create", format="excel", ready=False, intro="Quick check",
                           questions=[{"question": "Which region?", "options": opts("Japan only", "Worldwide")}]),
                  **self.kw)
        assert p.action == "clarify" and p.intro == "Quick check"
        assert [o["label"] for o in p.questions[0].options] == ["Japan only", "Worldwide"]

    def test_the_model_cannot_add_its_own_other_option(self):
        p = parse(decision(action="create", ready=False, questions=[
            {"question": "Genre?", "options": opts("Shonen", "Seinen", "Other")}]), **self.kw)
        assert [o["label"] for o in p.questions[0].options] == ["Shonen", "Seinen"]

    def test_a_recommended_tag_in_a_label_is_removed(self):
        p = parse(decision(action="create", ready=False, questions=[{"question": "Range?", "options": [
            {"label": "Sep 2021 – Sep 2026 (recommended)", "description": "[Recommended] rolling"},
            {"label": "Recommended: 2020–2025", "description": ""},
        ]}]), **self.kw)
        assert [o["label"] for o in p.questions[0].options] == ["Sep 2021 – Sep 2026", "2020–2025"]
        assert p.questions[0].options[0]["description"] == "rolling"

    def test_at_most_three_questions_with_at_most_three_options(self):
        many = [{"question": f"Q{i}", "options": opts("a", "b", "c", "d")} for i in range(5)]
        p = parse(decision(action="create", ready=False, questions=many), **self.kw)
        assert len(p.questions) == 3 and all(len(q.options) == 3 for q in p.questions)

    def test_a_question_with_one_option_is_not_a_question(self):
        p = parse(decision(action="create", ready=False, brief="b",
                           questions=[{"question": "Sure?", "options": opts("Yes")}]), **self.kw)
        assert p.action == "create"

    def test_after_answers_it_never_asks_again(self):
        p = parse(decision(action="create", ready=False, brief="b",
                           questions=[{"question": "Q", "options": opts("a", "b")}]),
                  message="1. a", has_spreadsheet=False, after_clarifier=True)
        assert p.action == "create"

    def test_analyzing_without_a_sheet_is_just_chat(self):
        assert parse(decision(action="analyze", ready=True), **self.kw) is None

    def test_transforming_without_a_sheet_becomes_creating(self):
        assert parse(decision(action="transform", ready=True), **self.kw).action == "create"

    def test_with_a_sheet_transform_and_analyze_stand(self):
        kw = dict(message="m", has_spreadsheet=True, after_clarifier=False)
        assert parse(decision(action="analyze", ready=True), **kw).action == "analyze"
        assert parse(decision(action="transform", ready=True), **kw).format == "excel"

    def test_a_table_from_an_attached_sheet_is_copied_by_code(self):
        kw = dict(message="csv of the movies", has_spreadsheet=True, after_clarifier=False)
        for fmt in ("csv", "excel"):
            p = parse(decision(action="create", format=fmt, source="attachment", ready=True), **kw)
            assert p.action == "transform", fmt

    def test_a_pdf_from_an_attached_sheet_is_still_written(self):
        kw = dict(message="pdf report of it", has_spreadsheet=True, after_clarifier=False)
        p = parse(decision(action="create", format="pdf", source="attachment", ready=True), **kw)
        assert p.action == "create"

    def test_an_empty_brief_falls_back_to_the_message(self):
        p = parse(decision(action="create", ready=True), message="the request",
                  has_spreadsheet=False, after_clarifier=False)
        assert p.brief == "the request"


class TestPrompt:
    def test_the_model_is_told_today_s_date(self):
        from app.chat_artifacts.decision import build_user

        prompt = build_user("anime of the last five years", [], [], False, today="2026-09-14")
        assert "2026-09-14" in prompt

    def test_it_defaults_to_the_real_date(self):
        from datetime import date

        from app.chat_artifacts.decision import build_user

        assert date.today().isoformat() in build_user("m", [], [], False)


class TestSessionText:
    def test_cards_read_as_sentences_in_memory(self):
        asked = json.dumps({"questions": [{"question": "Which years?"}]})
        made = json.dumps({"status": "ready", "filename": "anime.xlsx", "title": "Anime"})
        assert "Which years?" in session_text(asked, CLARIFIER)
        assert "anime.xlsx" in session_text(made, FILE_ARTIFACT)

    def test_prose_is_untouched(self):
        assert session_text("hello", "coding_agent") == "hello"
