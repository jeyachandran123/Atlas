"""
Repository Mode smoke test — exercises the decision layer deterministically.

No DB, no Redis, no LLM: instantiates the intent detector, tool planner, and
confidence evaluator directly and asserts the Codex-style behaviours:

  1. "Read the full repository"  → REPOSITORY_QUESTION + list_directory/search plan
  2. "Edit main.py"              → REPOSITORY_QUESTION (file located, never "which file?")
  3. "Where is authentication implemented?" → repo intent + search plan
  4. "hello"                     → GENERAL_CHAT untouched (no tools)
  5. No-repo "write a main.py for a flask app" → NOT forced into repo intent
  6. Repo active + zero retrieved chunks + tool plan → NEVER clarifies

Run:  venv\\Scripts\\python.exe scripts\\smoke_repo_mode.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.intelligence.intent.detector import IntentDetector  # noqa: E402
from app.intelligence.models import Complexity, Intent  # noqa: E402
from app.intelligence.reasoning.confidence.evaluator import ConfidenceEvaluator  # noqa: E402
from app.intelligence.reasoning.models import GoalType, InferredGoal  # noqa: E402
from app.intelligence.tools.planner import IntelligenceToolPlanner  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


detector = IntentDetector()
planner = IntelligenceToolPlanner()
evaluator = ConfidenceEvaluator()


def fake_context(message: str, intent: Intent, confidence: float, repo: bool):
    """Minimal duck-typed IntelligenceContext for planner/evaluator."""
    return SimpleNamespace(
        user_message=message,
        repo_id="repo-123" if repo else None,
        code_context_block="",
        retrieved_chunks_count=0,
        intent_analysis=SimpleNamespace(
            primary=SimpleNamespace(intent=intent, confidence=confidence),
        ),
        complexity=SimpleNamespace(level=Complexity.MEDIUM, signals=[]),
        tool_plan=None,
    )


print("— Intent detection (repo active) —")

r1 = detector.detect("Read the full repository", [], repo_active=True)
check(
    "'Read the full repository' → REPOSITORY_QUESTION",
    r1.primary.intent == Intent.REPOSITORY_QUESTION,
    f"got {r1.primary.intent}",
)

r2 = detector.detect("Edit main.py", [], repo_active=True)
check(
    "'Edit main.py' → REPOSITORY_QUESTION",
    r2.primary.intent == Intent.REPOSITORY_QUESTION,
    f"got {r2.primary.intent}",
)
check(
    "'Edit main.py' carries file signal",
    any(s.startswith("file:") for s in r2.primary.signals),
    f"signals={r2.primary.signals}",
)

r3 = detector.detect("Where is authentication implemented?", [], repo_active=True)
check(
    "'Where is authentication implemented?' → repo-native intent",
    r3.primary.intent == Intent.REPOSITORY_QUESTION,
    f"got {r3.primary.intent}",
)

r4 = detector.detect("hello", [], repo_active=True)
check(
    "'hello' stays GENERAL_CHAT in repo mode",
    r4.primary.intent == Intent.GENERAL_CHAT,
    f"got {r4.primary.intent}",
)

r5 = detector.detect("explain this codebase to me", [], repo_active=True)
check(
    "'explain this codebase' → REPOSITORY_QUESTION",
    r5.primary.intent == Intent.REPOSITORY_QUESTION,
    f"got {r5.primary.intent}",
)

print("— Intent detection (no repo) —")

r6 = detector.detect("write a main.py for a flask app", [], repo_active=False)
check(
    "no-repo creation request NOT forced to repo intent",
    r6.primary.intent != Intent.REPOSITORY_QUESTION,
    f"got {r6.primary.intent}",
)

print("— Tool planning (repo active) —")

p1 = planner.plan(fake_context("Read the full repository", Intent.REPOSITORY_QUESTION, 0.9, repo=True))
check(
    "repo-read plans list_directory + search_code",
    p1.should_use_tools and "list_directory" in p1.tools and "search_code" in p1.tools,
    f"tools={p1.tools}",
)

p2 = planner.plan(fake_context("Edit main.py to add logging", Intent.REPOSITORY_QUESTION, 0.9, repo=True))
check(
    "file mention plans search_code + read_file",
    p2.should_use_tools and "search_code" in p2.tools and "read_file" in p2.tools,
    f"tools={p2.tools}",
)

p3 = planner.plan(fake_context("how does caching work here?", Intent.LEARNING, 0.4, repo=True))
check(
    "ambiguous question in repo mode → search-first default",
    p3.should_use_tools and "search_code" in p3.tools,
    f"tools={p3.tools} rationale={p3.rationale}",
)

p4 = planner.plan(fake_context("hello", Intent.GENERAL_CHAT, 0.9, repo=True))
check(
    "smalltalk plans no tools",
    not p4.should_use_tools,
    f"tools={p4.tools}",
)

p5 = planner.plan(fake_context("where is auth?", Intent.REPOSITORY_QUESTION, 0.9, repo=False))
check(
    "no repo → no tools",
    not p5.should_use_tools,
    f"tools={p5.tools}",
)

print("— Confidence / clarification —")

goal = InferredGoal(
    goal_type=GoalType.UNKNOWN,
    primary_objective="understand the repository",
    sub_objectives=[],
    success_criteria=[],
    requires_repo=True,
    requires_tools=True,
    confidence=0.2,
)

ctx = fake_context("Read the full repository", Intent.UNKNOWN, 0.0, repo=True)
ctx.tool_plan = SimpleNamespace(should_use_tools=True, tools=["search_code"])
report = evaluator.evaluate(goal, ctx)
check(
    "repo + tool plan + low confidence → NEVER clarifies",
    not report.should_clarify,
    f"overall={report.overall:.2f} clarify={report.should_clarify}",
)
check(
    "repo + zero chunks → requests retrieval",
    report.should_retrieve_more,
    f"should_retrieve_more={report.should_retrieve_more}",
)

ctx_norepo = fake_context("asdf qwerty", Intent.UNKNOWN, 0.0, repo=False)
report2 = evaluator.evaluate(goal, ctx_norepo)
check(
    "no-repo path follows plain threshold (repo override not applied)",
    report2.should_clarify == (report2.overall < 0.30),
    f"overall={report2.overall:.2f} clarify={report2.should_clarify}",
)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
