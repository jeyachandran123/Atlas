"""SkillRouter — explicit invocation, scoring, limits and the token budget."""

from __future__ import annotations

from app.skills.router import (
    CHARS_PER_TOKEN,
    TRUNCATION_MARKER,
    ActiveSkill,
    SkillCandidate,
    SkillRouter,
)

REVIEW = SkillCandidate(
    id="1",
    slug="review-agent",
    display_name="Review Agent",
    description="Find actionable bugs in code changes. Use when reviewing a diff or pull request.",
    instructions="REVIEW INSTRUCTIONS",
    triggers=("code review", "pull request", "diff"),
    modes=("code", "auto"),
)
DOCS = SkillCandidate(
    id="2",
    slug="atlas-docs",
    display_name="Atlas Docs",
    description="Explains how to use Atlas features like workspaces and repositories.",
    instructions="DOCS INSTRUCTIONS",
    triggers=("how do i use atlas",),
)
BIZ = SkillCandidate(
    id="3",
    slug="invoice-helper",
    display_name="Invoice Helper",
    description="Drafts invoices.",
    instructions="BIZ",
    triggers=("invoice",),
    modes=("business",),
)


def router(**kw) -> SkillRouter:
    kw.setdefault("threshold", 1.0)
    kw.setdefault("max_active", 3)
    kw.setdefault("token_budget", 3000)
    return SkillRouter(**kw)


# ── Explicit invocation ──────────────────────────────────────────────────────


def test_leading_slash_selects_and_strips() -> None:
    sel = router().choose([REVIEW, DOCS], "/review-agent check this function")
    assert [s.slug for s in sel.skills] == ["review-agent"]
    assert sel.skills[0].explicit
    assert sel.message == "check this function"


def test_at_mention_selects_and_strips() -> None:
    sel = router().choose([REVIEW, DOCS], "please use @atlas-docs to explain workspaces")
    assert [s.slug for s in sel.skills][0] == "atlas-docs"
    assert sel.message == "please use to explain workspaces"


def test_unknown_tokens_untouched() -> None:
    slugs, text = SkillRouter.parse_explicit(
        "/api/v1/chat is slow, mail me@example.com", ["review-agent"]
    )
    assert slugs == [] and text == "/api/v1/chat is slow, mail me@example.com"


def test_email_is_not_a_mention() -> None:
    slugs, _ = SkillRouter.parse_explicit("write to admin@review-agent", ["review-agent"])
    assert slugs == []


def test_explicit_works_for_disabled_skill() -> None:
    disabled = SkillCandidate(**{**REVIEW.__dict__, "enabled": False})
    assert router().choose([disabled], "/review-agent go").skills[0].slug == "review-agent"
    assert router().choose([disabled], "code review this diff").skills == []


def test_only_slug_keeps_message() -> None:
    sel = router().choose([REVIEW], "/review-agent")
    assert sel.skills and sel.message == "/review-agent"


# ── Automatic selection ──────────────────────────────────────────────────────


def test_trigger_selects() -> None:
    sel = router().choose([REVIEW, DOCS], "Can you do a code review of this pull request?", "code")
    assert [s.slug for s in sel.skills] == ["review-agent"]
    assert sel.message == "Can you do a code review of this pull request?"


def test_below_threshold_selects_nothing() -> None:
    assert router().choose([REVIEW, DOCS], "What is the capital of France?").skills == []


def test_mode_mismatch_excludes() -> None:
    assert router().choose([BIZ], "make an invoice", "code").skills == []
    assert router().choose([BIZ], "make an invoice", "business").skills[0].slug == "invoice-helper"


def test_description_overlap_alone_can_select() -> None:
    cand = SkillCandidate(
        id="9",
        slug="sql-tuner",
        display_name="SQL Tuner",
        description="Optimize slow postgres queries using indexes and explain plans.",
        instructions="SQL",
    )
    sel = router().choose(
        [cand], "my postgres queries are slow, which indexes and explain plans help?"
    )
    assert [s.slug for s in sel.skills] == ["sql-tuner"]


def test_history_keeps_strong_follow_up_on_topic() -> None:
    r = router()
    strong = [{"role": "user", "content": "code review this pull request diff"}]
    weak = [{"role": "user", "content": "can you look at the diff"}]
    assert r.choose([REVIEW], "and the second file?", "code").skills == []
    # a strongly on-topic previous turn carries the skill to a terse follow-up…
    assert r.choose([REVIEW], "and the second file?", "code", strong).skills
    # …a weak one does not (history counts at 0.3x)
    assert r.choose([REVIEW], "and the second file?", "code", weak).skills == []
    # only the latest user turn counts, assistant turns are ignored
    mixed = strong + [{"role": "assistant", "content": "x"}, {"role": "user", "content": "thanks"}]
    assert r.choose([REVIEW], "and the second file?", "code", mixed).skills == []


def test_max_active_and_ordering() -> None:
    cands = [
        SkillCandidate(
            id=str(i),
            slug=f"s{i}",
            display_name=f"S{i}",
            description="x",
            instructions="i",
            triggers=tuple(f"kw{j}" for j in range(i)),
        )
        for i in range(1, 6)
    ]
    # s1=1.0, s2=2.0, s3..s5 capped at 2.5 → top three tie, ordered by slug
    sel = router(max_active=3).choose(cands, "kw0 kw1 kw2 kw3 kw4")
    assert [s.slug for s in sel.skills] == ["s3", "s4", "s5"]
    sel = router(max_active=4).choose(cands, "kw0 kw1 kw2 kw3 kw4")
    assert [s.slug for s in sel.skills] == ["s3", "s4", "s5", "s2"]


def test_explicit_comes_first_then_auto() -> None:
    sel = router().choose([REVIEW, DOCS], "/atlas-docs how do i use atlas for a code review")
    assert [s.slug for s in sel.skills] == ["atlas-docs", "review-agent"]


def test_auto_select_off_keeps_explicit_only() -> None:
    r = router()
    assert r.choose([REVIEW], "code review this diff", "code", auto_select=False).skills == []
    assert r.choose([REVIEW], "/review-agent x", "code", auto_select=False).skills


def test_max_active_zero_disables() -> None:
    assert router().choose([REVIEW], "/review-agent code review", max_active=0).skills == []


# ── Budget ───────────────────────────────────────────────────────────────────


def test_budget_truncates_lowest_scoring_first() -> None:
    budget_tokens = 200  # 800 chars: the first (500) fits whole, the second gets the rest
    big = "A" * 500
    skills = [
        ActiveSkill("1", "high", "High", big, 5.0),
        ActiveSkill("2", "low", "Low", big, 1.0),
    ]
    out = router(token_budget=budget_tokens).fit_budget(skills)
    assert out[0].instructions == big and not out[0].truncated
    assert out[1].truncated and out[1].instructions.endswith(TRUNCATION_MARKER)
    assert sum(len(s.instructions) for s in out) <= budget_tokens * CHARS_PER_TOKEN


def test_budget_drops_skill_with_too_little_room() -> None:
    skills = [
        ActiveSkill("1", "high", "High", "A" * 390, 5.0),
        ActiveSkill("2", "low", "Low", "B" * 500, 1.0),
    ]
    out = router(token_budget=100).fit_budget(skills)  # 400 chars total
    assert [s.slug for s in out] == ["high"]


def test_selection_applies_budget() -> None:
    long_review = SkillCandidate(**{**REVIEW.__dict__, "instructions": "R" * 20000})
    sel = router(token_budget=1000).choose([long_review], "code review this diff", "code")
    assert sel.skills[0].truncated
    assert len(sel.skills[0].instructions) <= 1000 * CHARS_PER_TOKEN


# ── Skills picked in the composer's + menu ───────────────────────────────────


def test_picked_skills_are_used_exactly_and_replace_automatic_selection() -> None:
    sel = router().choose([REVIEW, DOCS, BIZ], "code review this diff", picked=["invoice-helper"])
    assert [s.slug for s in sel.skills] == ["invoice-helper"]     # not review-agent, though it matches


def test_picked_skills_work_when_switched_off() -> None:
    off = SkillCandidate(**{**REVIEW.__dict__, "enabled": False})
    assert [s.slug for s in router().choose([off], "hello", picked=["review-agent"]).skills] == ["review-agent"]


def test_picked_skills_keep_their_order_and_ignore_unknown_and_duplicate_slugs() -> None:
    sel = router().choose([REVIEW, DOCS, BIZ], "hi", picked=["atlas-docs", "nope", "review-agent", "atlas-docs"])
    assert [s.slug for s in sel.skills] == ["atlas-docs", "review-agent"]


def test_picking_more_than_the_automatic_limit_is_allowed() -> None:
    sel = router(max_active=1).choose([REVIEW, DOCS, BIZ], "hi", picked=["review-agent", "atlas-docs", "invoice-helper"])
    assert len(sel.skills) == 3


def test_a_slash_command_still_works_alongside_picks() -> None:
    sel = router().choose([REVIEW, DOCS], "/atlas-docs what is this", picked=["review-agent"])
    assert [s.slug for s in sel.skills] == ["review-agent", "atlas-docs"]
    assert sel.message == "what is this"


def test_no_picks_changes_nothing() -> None:
    assert router().choose([REVIEW], "code review this diff", picked=[]).skills[0].slug == "review-agent"
