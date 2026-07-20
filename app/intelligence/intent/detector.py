"""
Intent Detector.

Classifies user messages into one or more intents with confidence scores.
Supports multiple simultaneous intents (e.g. "Explain React and show architecture").

Design:
- Each intent is detected by an independent IntentRule
- Rules are registered in a registry — adding a new intent = adding one rule
- No if-else chains; rules are evaluated in parallel
- Returns primary intent + secondary intents above threshold
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

from app.intelligence.interfaces import AbstractIntentDetector
from app.intelligence.models import DetectedIntent, Intent, IntentAnalysis

# ── Repository Mode signals ───────────────────────────────────────────────────
# A concrete file reference ("main.py", "src/auth/router.ts") is the strongest
# possible repository signal — when a repo is active, the file is assumed to
# live in it. Never ask "which file?".
FILE_REF_RE = re.compile(
    r"\b[\w./\\-]+\.(?:py|ts|tsx|js|jsx|mjs|go|rs|java|kt|rb|php|c|cc|cpp|h|hpp|"
    r"cs|swift|scala|sql|sh|ps1|bat|json|ya?ml|toml|ini|cfg|env|md|rst|txt|css|"
    r"scss|html|vue|svelte|proto|tf|dockerfile)\b",
    re.IGNORECASE,
)

# "the repo / this codebase / the project …" — corpus nouns
_REPO_NOUN_RE = re.compile(
    r"\b(?:repo|repository|codebase|code\s*base|project|source\s+code)\b",
    re.IGNORECASE,
)

# Verbs that, combined with a corpus noun, mean "operate on the repository"
_REPO_VERB_RE = re.compile(
    r"\b(?:read|explain|summari[sz]e|analy[sz]e|understand|describe|walk\s*(?:me\s*)?through|"
    r"review|audit|explore|scan|map|document|tour|overview)\b",
    re.IGNORECASE,
)

# Verbs that mean "change this file/code"
_EDIT_VERB_RE = re.compile(
    r"\b(?:edit|modify|change|update|patch|rewrite|refactor|fix|improve|rename|"
    r"add\s+to|remove\s+from|delete\s+from)\b",
    re.IGNORECASE,
)

# Verbs that mean "make a NEW file" — a file mention next to these is a
# creation request, not a reference into the existing repository.
_CREATION_VERB_RE = re.compile(
    r"\b(?:write|create|generate|make|scaffold|new)\b",
    re.IGNORECASE,
)


def repo_read_requested(message: str) -> bool:
    """True for 'read the full repository'-class requests."""
    return bool(_REPO_NOUN_RE.search(message) and _REPO_VERB_RE.search(message)) or bool(
        re.search(r"\b(?:full|entire|whole|complete)\s+(?:repo|repository|codebase|project)\b", message, re.IGNORECASE)
    )


def file_reference(message: str) -> str | None:
    """Return the first concrete file reference in the message, if any."""
    m = FILE_REF_RE.search(message)
    return m.group(0) if m else None


# ── Intent Rule ───────────────────────────────────────────────────────────────


@dataclass
class IntentRule:
    """
    A single intent detection rule.
    Evaluates a message and returns a confidence score (0.0 – 1.0).
    """
    intent: Intent
    keywords: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)   # regex patterns
    scorer: Callable[[str, list[dict]], float] | None = None  # custom scorer

    def score(self, message: str, history: list[dict]) -> tuple[float, list[str]]:
        """Return (confidence, matched_signals)."""
        lower = message.lower()
        signals: list[str] = []
        hits = 0

        for kw in self.keywords:
            if kw in lower:
                hits += 1
                signals.append(kw)

        for pat in self.patterns:
            if re.search(pat, lower):
                hits += 1
                signals.append(pat)

        # Score: first hit gives 0.3 base, each additional hit adds 0.1 (capped at 1.0)
        keyword_score = min(0.3 + (hits - 1) * 0.1, 1.0) if hits > 0 else 0.0

        custom_score = 0.0
        if self.scorer:
            custom_score = self.scorer(message, history)

        confidence = max(keyword_score, custom_score)
        return confidence, signals


# ── Intent Rule Registry ──────────────────────────────────────────────────────


class IntentRuleRegistry:
    """
    Registry of all intent rules.
    Adding a new intent = calling register() with a new IntentRule.
    """

    def __init__(self) -> None:
        self._rules: dict[Intent, IntentRule] = {}

    def register(self, rule: IntentRule) -> None:
        self._rules[rule.intent] = rule

    def all_rules(self) -> list[IntentRule]:
        return list(self._rules.values())


def _build_default_registry() -> IntentRuleRegistry:
    registry = IntentRuleRegistry()

    registry.register(IntentRule(
        intent=Intent.CODING,
        keywords=[
            "write code", "implement", "create a function", "build a", "generate code",
            "write a script", "add a method", "create a class", "write a component",
            "code for", "function that", "class that", "write a function",
        ],
        patterns=[r"\bimplement\b", r"\bwrite\b.{0,20}\bfunction\b", r"\bcreate\b.{0,20}\bclass\b"],
    ))

    registry.register(IntentRule(
        intent=Intent.DEBUGGING,
        keywords=[
            "fix", "bug", "error", "broken", "failing", "debug", "crash", "exception",
            "traceback", "not working", "why is", "what's wrong", "issue with",
        ],
        patterns=[r"\bfix\b", r"\berror\b", r"\bcrash\b", r"traceback", r"exception"],
    ))

    registry.register(IntentRule(
        intent=Intent.ARCHITECTURE,
        keywords=[
            "architecture", "design", "system design", "diagram", "structure",
            "how should i design", "best way to structure", "pattern", "microservice",
            "clean architecture", "ddd", "domain driven", "event driven",
        ],
        patterns=[r"\barchitect\w*\b", r"\bdesign\b.{0,30}\bsystem\b"],
    ))

    registry.register(IntentRule(
        intent=Intent.REPOSITORY_QUESTION,
        keywords=[
            "in this repo", "in my codebase", "in this project", "find in code",
            "where is", "which file", "show me the", "how does this project",
            "in our code", "this codebase",
            "read the file", "read file", "show the file", "open the file",
            "show me the code", "show me the full code", "show full code",
            "what's in", "what is in", "contents of", "content of",
            "list files", "list directory", "show directory",
            # Repository-corpus requests ("read the repo" ≠ "read the file")
            "read the repo", "read the repository", "read the codebase",
            "read the project", "read full repo", "read full repository",
            "explain the repo", "explain the repository", "explain the codebase",
            "explain this project", "summarize the repo", "summarize the codebase",
            "understand the codebase", "walk me through", "architecture of",
            "how does this codebase", "how is this project", "explore the repo",
        ],
        patterns=[
            r"\bwhere\b.{0,20}\bcode\b", r"\bfind\b.{0,20}\bfile\b",
            r"\bread\b.{0,30}\bfile\b", r"\bshow\b.{0,30}\bfile\b",
            r"\bopen\b.{0,20}\bfile\b", r"\bcontents?\s+of\b",
            r"\b(?:read|explain|summari[sz]e|analy[sz]e|understand|describe|review|audit|explore|map)\b"
            r".{0,40}\b(?:repo|repository|codebase|project|source\s+code)\b",
            r"\b(?:full|entire|whole|complete)\s+(?:repo|repository|codebase|project)\b",
            r"\bwhere\s+is\b.{0,40}\b(?:implement|defin|handl|configur|declar)\w*",
        ],
        # A concrete file mention (that isn't a "create me a new file" request)
        # is a moderate repo signal even without an active repo.
        scorer=lambda msg, hist: (
            0.5
            if file_reference(msg) and not _CREATION_VERB_RE.search(msg)
            else 0.0
        ),
    ))

    registry.register(IntentRule(
        intent=Intent.DOCUMENTATION,
        keywords=[
            "document", "write docs", "add docstring", "readme", "api docs",
            "write documentation", "explain this code", "add comments",
        ],
        patterns=[r"\bdocument\w*\b", r"\bdocstring\b", r"\breadme\b"],
    ))

    registry.register(IntentRule(
        intent=Intent.LEARNING,
        keywords=[
            "what is", "explain", "how does", "teach me", "i want to learn",
            "what are", "can you explain", "help me understand", "what does",
        ],
        patterns=[r"\bwhat\s+is\b", r"\bhow\s+does\b", r"\bexplain\b"],
    ))

    registry.register(IntentRule(
        intent=Intent.DEEP_TEACHING,
        keywords=[
            "teach me from scratch", "beginner to advanced", "complete guide",
            "full tutorial", "deep dive", "comprehensive", "everything about",
            "master", "learn everything",
        ],
        patterns=[r"from\s+(beginner|scratch|zero)", r"complete\s+(guide|tutorial|course)"],
    ))

    registry.register(IntentRule(
        intent=Intent.RECOMMENDATION,
        keywords=[
            "recommend", "suggest", "what should i use", "best library",
            "which is better", "what do you recommend", "best practice",
            "should i use", "best tool",
        ],
        patterns=[r"\brecommend\b", r"\bsuggest\b", r"best\s+\w+\s+for"],
    ))

    registry.register(IntentRule(
        intent=Intent.COMPARISON,
        keywords=[
            "vs", "versus", "compare", "difference between", "which is better",
            "pros and cons", "trade-offs", "tradeoffs",
        ],
        patterns=[r"\bvs\.?\b", r"\bversus\b", r"compare\b", r"difference\s+between"],
    ))

    registry.register(IntentRule(
        intent=Intent.RESEARCH,
        keywords=[
            "research", "find information", "what are the latest", "state of the art",
            "survey", "overview of", "summarize", "what exists",
        ],
        patterns=[r"\bresearch\b", r"state\s+of\s+the\s+art", r"latest\s+\w+\s+in"],
    ))

    registry.register(IntentRule(
        intent=Intent.BRAINSTORMING,
        keywords=[
            "brainstorm", "ideas for", "think of", "what could", "possibilities",
            "options for", "ways to", "how might", "creative",
        ],
        patterns=[r"\bbrainstorm\b", r"ideas?\s+for", r"ways?\s+to\b"],
    ))

    registry.register(IntentRule(
        intent=Intent.PLANNING,
        keywords=[
            "plan", "roadmap", "steps to", "how to build", "how to implement",
            "project plan", "sprint", "milestone", "breakdown",
        ],
        patterns=[r"\bplan\b", r"\broadmap\b", r"steps?\s+to\b"],
    ))

    registry.register(IntentRule(
        intent=Intent.REFACTORING,
        keywords=[
            "refactor", "clean up", "improve this code", "make this better",
            "optimize", "restructure", "simplify", "rewrite",
        ],
        patterns=[r"\brefactor\b", r"\bclean\s+up\b", r"\boptimize\b"],
    ))

    registry.register(IntentRule(
        intent=Intent.TESTING,
        keywords=[
            "write test", "add test", "unit test", "integration test", "test case",
            "test coverage", "mock", "pytest", "jest", "vitest",
        ],
        patterns=[r"\btest\w*\b.{0,20}\bwrite\b", r"\bunit\s+test\b", r"\btest\s+case\b"],
    ))

    registry.register(IntentRule(
        intent=Intent.GIT_OPERATIONS,
        keywords=[
            "git", "commit", "branch", "merge", "pull request", "rebase",
            "git diff", "git log", "stash", "cherry-pick",
        ],
        patterns=[r"\bgit\b", r"\bcommit\b", r"\bbranch\b"],
    ))

    registry.register(IntentRule(
        intent=Intent.TOOL_EXECUTION,
        keywords=[
            "run", "execute", "terminal", "command", "shell", "bash",
            "run this", "execute this", "run the tests",
        ],
        patterns=[r"\brun\b.{0,20}\bcommand\b", r"\bexecute\b"],
    ))

    registry.register(IntentRule(
        intent=Intent.GENERAL_CHAT,
        keywords=[
            "hello", "hi", "hey", "thanks", "thank you", "how are you",
            "what can you do", "help",
        ],
        patterns=[r"^(hi|hello|hey)\b", r"^thanks?\b"],
    ))

    return registry


# ── Intent Detector ───────────────────────────────────────────────────────────


class IntentDetector(AbstractIntentDetector):
    """
    Evaluates all registered intent rules and returns ranked results.

    Primary intent: highest confidence above PRIMARY_THRESHOLD.
    Secondary intents: all others above SECONDARY_THRESHOLD.
    """

    PRIMARY_THRESHOLD = 0.15
    SECONDARY_THRESHOLD = 0.10

    def __init__(self, registry: IntentRuleRegistry | None = None) -> None:
        self._registry = registry or _build_default_registry()

    # Intents that already route through the repository/tool pipeline —
    # a Repository Mode override must not displace them.
    _REPO_NATIVE_INTENTS = {
        Intent.REPOSITORY_QUESTION,
        Intent.DEBUGGING,
        Intent.REFACTORING,
        Intent.CODING,
        Intent.TESTING,
        Intent.GIT_OPERATIONS,
        Intent.TOOL_EXECUTION,
        Intent.ARCHITECTURE,
        Intent.DOCUMENTATION,
    }

    def detect(
        self,
        message: str,
        session_messages: list[dict],
        agent_mode: str = "auto",
        repo_active: bool = False,
    ) -> IntentAnalysis:
        scored: list[tuple[float, IntentRule, list[str]]] = []

        for rule in self._registry.all_rules():
            confidence, signals = rule.score(message, session_messages)
            if confidence > 0:
                scored.append((confidence, rule, signals))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Apply agent_mode overrides
        if agent_mode == "business":
            # Business mode always routes through GENERAL_CHAT
            return IntentAnalysis(
                primary=DetectedIntent(Intent.GENERAL_CHAT, 0.9, ["business_mode"]),
                raw_message=message,
            )

        if not scored or scored[0][0] < self.PRIMARY_THRESHOLD:
            analysis = IntentAnalysis(
                primary=DetectedIntent(Intent.UNKNOWN, 0.0, []),
                raw_message=message,
            )
            return self._apply_repo_mode(analysis, message) if repo_active else analysis

        primary_score, primary_rule, primary_signals = scored[0]
        primary = DetectedIntent(primary_rule.intent, primary_score, primary_signals)

        secondary = [
            DetectedIntent(rule.intent, conf, sigs)
            for conf, rule, sigs in scored[1:]
            if conf >= self.SECONDARY_THRESHOLD and rule.intent != primary_rule.intent
        ]

        analysis = IntentAnalysis(primary=primary, secondary=secondary, raw_message=message)
        return self._apply_repo_mode(analysis, message) if repo_active else analysis

    def _apply_repo_mode(self, analysis: IntentAnalysis, message: str) -> IntentAnalysis:
        """
        Repository Mode override: with an active repo, repository signals win.

        - A concrete file reference (non-creation) → REPOSITORY_QUESTION
        - A repo-corpus request ("read the repository") → REPOSITORY_QUESTION
        - An edit verb + file reference → stays repo-native (never general chat)

        Repo-native primaries (debugging, refactoring, …) are left untouched —
        they already route through the repository pipeline.
        """
        if analysis.primary.intent in self._REPO_NATIVE_INTENTS:
            # Already repo-native — just attach the located file as a signal
            # so downstream stages (tool args, observability) can use it.
            native_fref = file_reference(message)
            if native_fref and f"file:{native_fref}" not in analysis.primary.signals:
                analysis.primary.signals.append(f"file:{native_fref}")
            return analysis

        fref = file_reference(message)
        is_creation = bool(_CREATION_VERB_RE.search(message))
        repoish = repo_read_requested(message) or (fref is not None and not is_creation)
        # An edit verb with a file reference is repo work even with a creation verb nearby
        if fref is not None and _EDIT_VERB_RE.search(message):
            repoish = True

        if not repoish:
            return analysis

        signals = list(analysis.primary.signals) + ["repo_mode_override"]
        if fref:
            signals.append(f"file:{fref}")

        demoted = analysis.primary
        secondary = [s for s in analysis.secondary if s.intent != Intent.REPOSITORY_QUESTION]
        if demoted.intent not in (Intent.UNKNOWN, Intent.REPOSITORY_QUESTION):
            secondary = [demoted, *secondary]

        return IntentAnalysis(
            primary=DetectedIntent(
                Intent.REPOSITORY_QUESTION,
                max(analysis.primary.confidence, 0.85),
                signals,
            ),
            secondary=secondary,
            raw_message=message,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_detector: IntentDetector | None = None


def get_intent_detector() -> IntentDetector:
    global _detector
    if _detector is None:
        _detector = IntentDetector()
    return _detector
