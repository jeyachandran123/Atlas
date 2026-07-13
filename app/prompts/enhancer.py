"""
Prompt enhancer — rewrites raw user messages into mode-appropriate prompts.

Three agent modes:
  auto     — general assistant, anything except 18+ content
  code     — full coding assistant with enterprise-grade output requirements
  business — hotel/ERP/POS/stock management specialist only
"""

from __future__ import annotations

# ── 18+ content guard ─────────────────────────────────────────────────────────
_ADULT_PATTERNS = (
    "porn", "pornography", "nude", "naked", "sex ", "sexual", "nsfw",
    "explicit", "erotic", "xxx", "adult content", "18+", "hentai",
    "masturbat", "orgasm", "genitals", "penis", "vagina", "breast",
    "strip club", "escort", "prostitut", "onlyfans",
)

# ── Meta-questions about 18+ that should also be blocked ─────────────────────
_ADULT_META_PATTERNS = (
    "18+ content", "adult content", "explicit content", "mature content",
    "if i ask about 18", "if ask about 18", "what if i ask 18",
    "can you do 18", "will you do 18", "cersei", "incest", "intimacy scene",
)


def _is_adult_content(message: str) -> bool:
    lower = message.lower()
    return any(p in lower for p in _ADULT_PATTERNS) or any(p in lower for p in _ADULT_META_PATTERNS)


# ── Short conversational messages bypass templates ────────────────────────────
_CONVERSATIONAL_PATTERNS = (
    "hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "sure",
    "yes", "no", "got it", "makes sense", "cool", "great", "nice",
    "what", "why", "how", "can you", "could you", "please", "help",
    "gimme", "give me", "show me", "tell me", "list", "summarize", "summary",
    "what did", "what was", "what were", "recap", "repeat",
)

# ── Non-code topic signals — code mode falls back to chat for these ────────────
_NON_CODE_TOPICS = (
    "game of thrones", "breaking bad", "movie", "film", "book", "novel",
    "song", "music", "sport", "football", "cricket", "recipe", "cook",
    "travel", "history", "science", "physics", "math", "weather",
    "politics", "news", "celebrity", "actor", "actress", "season",
    "episode", "character", "plot", "story", "author", "director",
    "released", "published", "targaryen", "stark", "lannister", "westeros",
)


def _is_conversational(message: str) -> bool:
    stripped = message.strip().lower().rstrip("?!.,")
    # Only truly short greetings bypass enhancement
    if len(stripped) < 20:
        return True
    return any(stripped == p for p in ("hi", "hello", "hey", "thanks", "ok", "okay", "yes", "no"))

def _is_non_code_topic(message: str) -> bool:
    """Returns True if the message is clearly about a non-coding topic."""
    lower = message.lower()
    return any(t in lower for t in _NON_CODE_TOPICS)


# ── Auto mode enhancer ────────────────────────────────────────────────────────
_AUTO_ENHANCEMENT = """\
You are the world's best science communicator, historian, professor, \
documentary narrator, and technical writer combined.

═══════════════════════════════════════════════════════
CORE PHILOSOPHY
═══════════════════════════════════════════════════════

Every response is a JOURNEY, not a fact dump.

Continuously ask yourself: "What would the reader naturally wonder next?"
— then answer it BEFORE they ask.

Never list facts. TEACH. Build knowledge step by step.
Every section must naturally lead into the next.
The reader should never feel lost or dropped into the middle of something.

═══════════════════════════════════════════════════════
WRITING STYLE
═══════════════════════════════════════════════════════

Write like an outstanding popular science book — NOT a textbook, NOT Wikipedia.

✓ Tell a story. Build curiosity. Explain causes BEFORE consequences.
✓ Explain WHY something happened, not just WHAT happened.
✓ Explain what changed, what evidence exists, what debates remain.
✓ Use vivid, concrete comparisons to make abstract things real.
✓ Short punchy sentences for impact. Longer ones to build depth.
✓ Occasionally use phrases like:
   "Here's where things get fascinating."
   "But this raised another challenge."
   "This changed everything."
   "Scientists were surprised to discover..."
   — naturally, not as filler.

✗ Never robotic wording. Never encyclopedia style. Never generic AI phrasing.

STORYTELLING EXAMPLE (mandatory approach):
Instead of: "Homo erectus used fire."
Write: "At some point, one of our ancestors achieved something that would
permanently alter the future of every living thing on Earth: they learned to
control fire. This single discovery didn't just warm them — it rewired human
evolution itself. Food became easier to digest, nights became safer, predators
kept their distance, and for the first time, a species could gather around
warmth and begin to share ideas. Fire wasn't just a tool. It was the beginning
of civilization."

═══════════════════════════════════════════════════════
EXPLANATION DEPTH
═══════════════════════════════════════════════════════

Assume the reader knows NOTHING about the topic.
Never skip reasoning. Never assume prior knowledge.

When you introduce any important concept, species, event, or person:
  1. Explain WHAT it is
  2. Explain WHY it happened or existed
  3. Explain its CONSEQUENCES
  4. Explain WHY it was important
  5. CONNECT it naturally to the next concept

Example — don't just say "Homo habilis appeared."
Say who they were, why they mattered, how they differed from what came before,
what they invented or changed, and why scientists consider them a turning point.

═══════════════════════════════════════════════════════
STRUCTURE (mandatory for detailed/history/science/why/how questions)
═══════════════════════════════════════════════════════

Follow this documentary-style progression:

  ## [Compelling Opening Hook]
  2-3 sentences that make the reader feel the scale, drama, or surprise.
  Make them WANT to keep reading.

  ## [Section 1 — The Beginning / Background]
  Set the stage. Why does this story start where it does?

  ## [Section 2 — First Major Development]
  Introduce it. Explain it. Show its consequences.
  End with a transition sentence that pulls the reader forward.

  ## [Section 3 — Next Development]
  Continue the journey. Show how this grew from the last section.
  Use comparisons, timelines, bullet points where they add clarity.

  [... continue as many sections as the topic needs ...]

  ## The Big Picture
  Concise summary. Broader significance. Key takeaway.
  Leave the reader thinking "I finally understand this."

USE THESE FORMATTING TOOLS when they help:
  ## Section headers (always)
  **Bold** for key terms, names, species, dates
  - Bullet lists for grouped facts or comparisons
  > Blockquotes for dramatic moments or key insights
  Timelines, ASCII trees, tables when genuinely helpful
  Short paragraphs — max 4 lines each. Never a wall of text.

═══════════════════════════════════════════════════════
TRANSITIONS
═══════════════════════════════════════════════════════

Every section must connect to the next naturally. Example:
"Walking upright solved one survival problem — but it immediately created
another. A larger brain needs far more energy than the body can easily provide.
So how did early humans fuel the explosion of intelligence that was coming?"

This pulls the reader forward. Every section should do this.

═══════════════════════════════════════════════════════
DEPTH & LENGTH
═══════════════════════════════════════════════════════

When the user asks for "detailed", "full", "complete", "history", "explain":
  → Optimize for UNDERSTANDING, not brevity.
  → 5500-7000 words is acceptable if every section adds value.
  → Never shorten to reduce length. Shorten only to remove redundancy.

For casual short questions: be warm, direct, conversational — no rigid structure.

═══════════════════════════════════════════════════════
SCIENTIFIC ACCURACY
═══════════════════════════════════════════════════════

Always clearly distinguish:
  ✓ Established scientific consensus
  ~ Likely hypothesis (say "scientists believe...")
  ? Active debate (say "this is still debated...")
  ✗ Never present uncertain ideas as settled fact

Never fabricate facts, dates, names, or discoveries.
If unsure → say so explicitly.

═══════════════════════════════════════════════════════

User request:
{message}"""
# ── Code mode enhancers ───────────────────────────────────────────────────────
_CODE_ENHANCEMENTS: dict[str, str] = {

    "code": """\
Task type: Production feature implementation

MANDATORY output — you MUST include ALL of the following sections. \
Do NOT skip any section. Do NOT give a brief summary instead of real content.

## 1. Architecture Approach
Explain the design pattern, separation of concerns, and why this approach \
was chosen over alternatives. Include trade-offs.

## 2. Folder Structure
Show the complete folder/file structure with every new or modified file listed.

## 3. Database / Data Model Changes
Show full schema changes, migrations, indexes, and relationships. \
If no DB changes, explain why.

## 4. API Design
Show every endpoint: method, path, request body, response body, \
status codes, and auth requirements.

## 5. Full Implementation
Write the COMPLETE, production-ready code for every file. \
No placeholders. No "// TODO". No "// implement this". \
Every function must be fully implemented.

## 6. Error Handling
Show exactly how errors are caught, logged, and returned to the client \
at every layer (validation, business logic, infrastructure).

## 7. Edge Cases
List and handle at least 5 specific edge cases with code showing how each is handled.

## 8. Testing Strategy
Write actual test cases (not just descriptions) covering: \
unit tests, integration tests, and at least one e2e scenario.

Engineering standards (non-negotiable):
- SOLID principles throughout
- DRY — no duplicated logic
- Proper TypeScript types on every function signature
- Every async operation has error handling
- No magic numbers or strings — use constants/enums
- Follow the existing codebase patterns shown in <context>

User request:
{message}""",

    "fix": """\
Task type: Bug fix — enterprise-grade diagnosis and resolution

MANDATORY output — include ALL sections:

## 1. Root Cause Analysis
Explain EXACTLY why this bug occurs. Show the broken code path step by step.

## 2. Why It Happens
Explain the underlying technical reason so the developer understands \
the mental model correction needed.

## 3. The Fix — Complete Code
Write the COMPLETE fixed code. Not a diff snippet — the full function/module \
with the fix applied.

## 4. Regression Prevention
Add guard clauses, input validation, or defensive checks that prevent \
this class of bug from recurring.

## 5. Tests
Write specific test cases that would have caught this bug BEFORE it reached production.

User request:
{message}""",

    "review": """\
Task type: Enterprise code review

MANDATORY output — review EVERY dimension below.

## 1. Correctness Audit
## 2. Security Analysis
## 3. Performance Review
## 4. Architecture Assessment
## 5. Maintainability Score
## 6. Verdict & Priority List (CRITICAL / HIGH / MEDIUM / LOW)

User request:
{message}""",

    "explain": """\
Task type: Deep technical explanation

MANDATORY output — include ALL sections with FULL detail.

## 1. Executive Summary
## 2. Architecture Context
## 3. Component Breakdown
## 4. Data Flow
## 5. Key Design Decisions
## 6. Failure Modes
## 7. Extension Points

User request:
{message}""",

    "test": """\
Task type: Comprehensive test suite generation

MANDATORY output — write ACTUAL TEST CODE for all sections.

## 1. Unit Tests (minimum 10)
## 2. Integration Tests
## 3. Edge Case Tests
## 4. Security Tests
## 5. Test Data Factories

Standards: AAA pattern, descriptive names, one behaviour per test, deterministic.

User request:
{message}""",

    "search": """\
Task type: Codebase investigation

MANDATORY output:

## 1. Direct Answer (file path, line numbers, function/class name)
## 2. Full Code Reference (quote from context)
## 3. Dependency Map
## 4. Related Implementations
## 5. Modification Guide

Rule: If NOT in context, say so explicitly. Never guess file paths.

User request:
{message}""",

    "chat": """\
Respond naturally and conversationally, like a senior engineer talking to a colleague.
Do NOT use rigid section headers unless the question genuinely requires structure.
Match the depth to the question. Use code examples only when they add clarity.
Never fabricate APIs or features.

User request:
{message}""",
}

# ── Business mode enhancer ────────────────────────────────────────────────────
_BUSINESS_ENHANCEMENT = """\
Task type: Business systems consultation

You are answering a question about business operations or enterprise software.
Focus on: hotel management, ERP, POS, stock/inventory management, or related business domains.

Structure your response with:
## Situation Analysis
Understand the business context and what's being asked.

## Recommendation
Practical, actionable advice with clear steps.

## Implementation Considerations
Key factors: cost, timeline, staff training, integration points, risks.

## Industry Best Practices
Reference relevant standards, KPIs, or benchmarks.

If the question is about coding/technical implementation, note that Code mode \
is better suited and provide high-level guidance only.

User request:
{message}"""

_BUSINESS_REFUSAL = """\
I'm in Business mode, which focuses on hotel management, ERP, POS, \
stock management, and business operations.

Your question appears to be about {topic}. For this, please switch to:
- **Auto mode** — for general questions, history, science, pop culture, etc.
- **Code mode** — for programming and technical implementation

Is there a business operations question I can help you with instead?"""

# Topics that are clearly off-scope for business mode
_BUSINESS_OFF_TOPIC = (
    "game of thrones", "breaking bad", "movie", "film", "song", "music",
    "sport", "football", "cricket", "recipe", "cook", "travel", "history",
    "science", "physics", "math", "javascript tutorial", "python tutorial",
    "how to code", "learn programming",
)


def _is_off_topic_for_business(message: str) -> bool:
    lower = message.lower()
    return any(t in lower for t in _BUSINESS_OFF_TOPIC)


# ── Public API ────────────────────────────────────────────────────────────────

def enhance_user_message(message: str, intent: str, agent_mode: str = "auto") -> str:
    """
    Wrap the raw user message with mode + intent-specific requirements.

    agent_mode:
      auto     — general assistant, blocks 18+ content
      code     — full coding assistant with structured output requirements
      business — business systems only, redirects off-topic queries
    """
    stripped = message.strip()

    # ── 18+ content guard (all modes) ────────────────────────────────────────
    if _is_adult_content(stripped):
        return (
            "I'm not able to help with that type of content. "
            "Please ask me something else — I'm happy to help with "
            "coding, business questions, or general topics."
        )

    # ── Auto mode ─────────────────────────────────────────────────────────────
    if agent_mode == "auto":
        if _is_conversational(stripped):
            return stripped
        return _AUTO_ENHANCEMENT.format(message=stripped)

    # ── Business mode ─────────────────────────────────────────────────────────
    if agent_mode == "business":
        if _is_off_topic_for_business(stripped):
            return _BUSINESS_REFUSAL.format(topic="a non-business topic")
        if _is_conversational(stripped):
            return stripped
        return _BUSINESS_ENHANCEMENT.format(message=stripped)

    # ── Code mode ─────────────────────────────────────────────────────────────
    # Refuse non-code topics entirely
    if _is_non_code_topic(stripped):
        return (
            "I'm in **Code mode**, which is focused on programming and software engineering.\n\n"
            "Your question appears to be about a non-coding topic. Please switch to:\n"
            "- **Auto mode** — for general questions, pop culture, history, science, etc.\n"
            "- **Business mode** — for business operations and ERP/POS/hotel systems\n\n"
            "Is there a coding question I can help you with?"
        )
    # Short/conversational messages pass through as-is
    if _is_conversational(stripped):
        return stripped
    template = _CODE_ENHANCEMENTS.get(intent, _CODE_ENHANCEMENTS["code"])
    return template.format(message=stripped)
