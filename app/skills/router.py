"""
SkillRouter — decides which skills shape a turn. No LLM call.

1. Explicit invocation wins: a leading `/slug` or an `@slug` anywhere selects
   that skill and the token is stripped from the message the model sees.
2. Otherwise enabled skills are scored against the message:
     trigger keyword hits · display-name hit · description term overlap ·
     agent-mode match (a skill that lists modes is skipped outside them) ·
     a small bonus from the previous user turn (follow-ups keep their skill)
   and at most SKILL_MAX_ACTIVE skills at or above SKILL_MATCH_THRESHOLD win.
3. The winners are fitted to SKILL_PROMPT_TOKEN_BUDGET (~4 chars/token): the
   lowest-scoring skill is truncated first, and dropped entirely if too
   little room is left — so what is reported as "used" is what the model saw.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.config import get_settings

CHARS_PER_TOKEN = 4
MIN_SKILL_CHARS = 200
TRUNCATION_MARKER = "\n\n…[skill instructions truncated to fit the prompt budget]"

_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_LEADING_SLASH_RE = re.compile(rf"^\s*/({_SLUG})(?=\s|$)")
_AT_RE = re.compile(rf"(?<![\w@./-])@({_SLUG})(?![\w-])")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#]*")

_STOPWORDS = frozenset(
    """a an and are as at be been but by can could do does for from get give had has have
    how i if in into is it its just like make me my no not of on or our please should so
    some than that the their them then there these they this those to too up us use used
    user users uses using via want wants was we what when where which while who why will
    with would you your ask asks asked help helps need needs task tasks thing things also
    any all about over more most other such only own same very""".split()
)


def _stem(word: str) -> str:
    if len(word) > 4:
        for suffix, repl in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                return word[: len(word) - len(suffix)] + repl
    return word


def terms(text: str) -> set[str]:
    return {_stem(w) for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS and len(w) > 2}


def _phrase_in(phrase: str, text_lower: str) -> bool:
    phrase = phrase.strip().lower()
    if not phrase:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text_lower) is not None


@dataclass(frozen=True)
class SkillCandidate:
    id: str
    slug: str
    display_name: str
    description: str
    instructions: str
    triggers: tuple[str, ...] = ()
    modes: tuple[str, ...] = ()
    enabled: bool = True


@dataclass(frozen=True)
class ActiveSkill:
    id: str
    slug: str
    name: str
    instructions: str
    score: float
    explicit: bool = False
    truncated: bool = False

    def ref(self) -> dict[str, str]:
        return {"slug": self.slug, "name": self.name}


@dataclass
class SkillSelection:
    message: str  # message with explicit /slug @slug tokens removed
    skills: list[ActiveSkill] = field(default_factory=list)

    @property
    def refs(self) -> list[dict[str, str]]:
        return [s.ref() for s in self.skills]


class SkillRouter:
    def __init__(
        self,
        threshold: float | None = None,
        max_active: int | None = None,
        token_budget: int | None = None,
    ) -> None:
        cfg = get_settings()
        self.threshold = cfg.skill_match_threshold if threshold is None else threshold
        self.max_active = cfg.skill_max_active if max_active is None else max_active
        self.token_budget = cfg.skill_prompt_token_budget if token_budget is None else token_budget

    # ── Explicit invocation ──────────────────────────────────────────────────

    @staticmethod
    def parse_explicit(message: str, known: Iterable[str]) -> tuple[list[str], str]:
        """Return (slugs, message without the tokens). Unknown slugs are left
        untouched — '/api/v1' or 'me@example.com' never get eaten."""
        known_set = set(known)
        slugs: list[str] = []
        text = message
        while True:
            m = _LEADING_SLASH_RE.match(text)
            if not m or m.group(1) not in known_set:
                break
            if m.group(1) not in slugs:
                slugs.append(m.group(1))
            text = text[m.end() :]

        def _at(m: re.Match[str]) -> str:
            slug = m.group(1)
            if slug not in known_set:
                return m.group(0)
            if slug not in slugs:
                slugs.append(slug)
            return ""

        text = _AT_RE.sub(_at, text)
        if not slugs:
            return [], message
        cleaned = re.sub(r"[ \t]{2,}", " ", text).strip()
        return slugs, cleaned or message

    # ── Scoring ──────────────────────────────────────────────────────────────

    @staticmethod
    def _text_score(cand: SkillCandidate, text: str) -> float:
        lower = text.lower()
        msg_terms = terms(text)
        score = 0.0
        trig = 0.0
        for t in cand.triggers:
            if _phrase_in(t, lower) or (" " not in t.strip() and _stem(t.lower()) in msg_terms):
                trig += 1.25 if " " in t.strip() else 1.0
        score += min(trig, 2.5)
        if _phrase_in(cand.display_name, lower) or _phrase_in(cand.slug.replace("-", " "), lower):
            score += 0.75
        overlap = len(msg_terms & terms(cand.description))
        score += min(0.3 * overlap, 1.2)
        return score

    def score(
        self, cand: SkillCandidate, message: str, agent_mode: str, history_text: str = ""
    ) -> float:
        if cand.modes and agent_mode not in cand.modes:
            return 0.0
        score = self._text_score(cand, message)
        if history_text:
            score += 0.3 * self._text_score(cand, history_text)
        if score > 0 and cand.modes:
            score += 0.1
        return round(score, 4)

    # ── Selection ────────────────────────────────────────────────────────────

    def choose(
        self,
        candidates: Sequence[SkillCandidate],
        message: str,
        agent_mode: str = "auto",
        history: Sequence[dict] | None = None,
        auto_select: bool = True,
        max_active: int | None = None,
        picked: Sequence[str] | None = None,
    ) -> SkillSelection:
        """`picked` = slugs chosen in the UI. They are used as written (in that order,
        beyond the usual cap if need be), and automatic selection is skipped: the
        user said what they want."""
        limit = max(0, self.max_active if max_active is None else max_active)
        by_slug = {c.slug: c for c in candidates}
        explicit, cleaned = self.parse_explicit(message, by_slug)
        if picked:
            chosen_by_user = [s for s in dict.fromkeys(picked) if s in by_slug]
            explicit = chosen_by_user + [s for s in explicit if s not in chosen_by_user]
            limit = max(limit, len(explicit))
            auto_select = False

        chosen: list[ActiveSkill] = []
        for slug in explicit[:limit]:
            c = by_slug[slug]
            chosen.append(
                ActiveSkill(c.id, c.slug, c.display_name, c.instructions, float("inf"), True)
            )

        if auto_select and len(chosen) < limit:
            history_text = ""
            for msg in reversed(list(history or [])):
                if msg.get("role") == "user" and msg.get("content"):
                    history_text = str(msg["content"])[:2000]
                    break
            taken = {s.slug for s in chosen}
            scored = [
                (self.score(c, cleaned, agent_mode, history_text), c)
                for c in candidates
                if c.enabled and c.slug not in taken
            ]
            scored = [(s, c) for s, c in scored if s >= self.threshold and s > 0]
            scored.sort(key=lambda sc: (-sc[0], sc[1].slug))
            for s, c in scored[: limit - len(chosen)]:
                chosen.append(ActiveSkill(c.id, c.slug, c.display_name, c.instructions, s))

        return SkillSelection(message=cleaned, skills=self.fit_budget(chosen))

    def fit_budget(self, skills: list[ActiveSkill]) -> list[ActiveSkill]:
        """Trim to the token budget; lowest-priority skills give way first."""
        budget = max(0, self.token_budget) * CHARS_PER_TOKEN
        out: list[ActiveSkill] = []
        remaining = budget
        for s in skills:  # already in priority order (explicit, then score desc)
            if remaining <= 0:
                break
            if len(s.instructions) <= remaining:
                out.append(s)
                remaining -= len(s.instructions)
                continue
            room = remaining - len(TRUNCATION_MARKER)
            if room < MIN_SKILL_CHARS:
                break
            out.append(
                ActiveSkill(
                    s.id,
                    s.slug,
                    s.name,
                    s.instructions[:room].rstrip() + TRUNCATION_MARKER,
                    s.score,
                    s.explicit,
                    truncated=True,
                )
            )
            remaining = 0
        return out
