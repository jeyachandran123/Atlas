"""Turn model text into JSON, or admit it could not. Never raises.

A VLM told to answer in JSON usually does — and then wraps it in a code fence,
or explains itself first, or trails a comma, or runs out of output tokens
halfway through the last line item. None of those are exceptional; they are the
normal distribution of a language model's output, and treating them as crashes
would make the pipeline's reliability a function of the model's mood.

Every strategy here is **conservative and deterministic**:

* it never invents a field the text did not contain;
* it never discards — what did not parse is reported, not swallowed;
* identical text produces an identical parse, so a replay reproduces.

The repairs are ordered cheapest-first and each is attempted only if the one
before it failed, so well-behaved output costs a single ``json.loads`` and
badly-behaved output degrades in a recorded, inspectable way.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

#: Fenced blocks: ```json … ``` or ``` … ```. The language tag is optional
#: because models are inconsistent about emitting it.
_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)

#: A trailing comma before a closing brace/bracket — by far the most common
#: malformation, and the safest to fix because it changes no value.
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")

#: ``// line`` and ``/* block */`` comments. Models add these when asked to
#: "explain your reasoning" anywhere in the prompt.
_LINE_COMMENT = re.compile(r"(?<![:\"'\\])//[^\n\r]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

#: Python literals leaking out of a model trained on a lot of Python.
_PY_LITERALS = (
    (re.compile(r"\bTrue\b"), "true"),
    (re.compile(r"\bFalse\b"), "false"),
    (re.compile(r"\bNone\b"), "null"),
    (re.compile(r"\bNaN\b"), "null"),
    (re.compile(r"\bInfinity\b"), "null"),
)

#: Typographic quotes, em dashes in numbers, and non-breaking spaces — all of
#: which arrive from models that have seen a lot of rendered documents.
_SMART_QUOTES = str.maketrans(
    {
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u00a0": " ",
    }
)

MAX_REPAIR_INPUT_CHARS = 2_000_000
"""Above this, repair is refused rather than attempted. A multi-megabyte
"JSON object" is a runaway generation, and scanning it repeatedly to prove that
costs more than the answer is worth."""


@dataclass(frozen=True, slots=True)
class JsonParseOutcome:
    """What could be made of the model's text.

    ``value`` is ``None`` exactly when nothing could be parsed. ``strategy``
    names how it was recovered, and ``repairs`` lists what had to be changed —
    both recorded because a model that needs the same repair on every call is a
    prompt that needs one edit, and nobody will make that edit without evidence.
    """

    value: Any | None = None
    raw: str = ""
    strategy: str = "none"
    repaired: bool = False
    repairs: tuple[str, ...] = ()
    error: str = ""
    unparsed: str = ""
    """Text that was not part of the recovered JSON. Preserved, never discarded."""

    @property
    def ok(self) -> bool:
        return self.value is not None

    @property
    def is_object(self) -> bool:
        return isinstance(self.value, dict)

    def as_dict(self) -> dict[str, Any]:
        """The parsed value as a mapping, or ``{}`` if it was not an object.

        Callers that want an object want it defensively — a model that returned
        a list where an object was asked for should not become an
        ``AttributeError`` three frames later.
        """
        return dict(self.value) if isinstance(self.value, dict) else {}

    def telemetry(self) -> dict[str, Any]:
        return {
            "json_ok": self.ok,
            "json_strategy": self.strategy,
            "json_repaired": self.repaired,
            "json_repairs": list(self.repairs),
        }


@dataclass
class _Attempt:
    """Mutable accumulator for one parse run. Internal to this module."""

    repairs: list[str] = field(default_factory=list)

    def note(self, repair: str) -> None:
        if repair not in self.repairs:
            self.repairs.append(repair)


def parse_model_json(text: str | None) -> JsonParseOutcome:
    """Best-effort JSON from model output. **Never raises.**

    Order of attempts, each tried only when the previous failed:

    1. straight ``json.loads`` — the well-behaved case, and the common one;
    2. the contents of a fenced code block;
    3. the first balanced ``{…}`` or ``[…]`` found in the text;
    4. the same, after conservative repairs (fences, comments, trailing commas,
       Python literals, smart quotes);
    5. the same, after closing brackets a truncated generation left open.
    """
    raw = text or ""
    if not raw.strip():
        return JsonParseOutcome(raw=raw, error="model returned empty text")
    if len(raw) > MAX_REPAIR_INPUT_CHARS:
        return JsonParseOutcome(
            raw=raw[:MAX_REPAIR_INPUT_CHARS],
            error=f"model output exceeds the {MAX_REPAIR_INPUT_CHARS} character repair limit",
            unparsed=raw[:4000],
        )

    attempt = _Attempt()

    # 1 — clean.
    parsed = _loads(raw.strip())
    if parsed is not _FAILED:
        return JsonParseOutcome(value=parsed, raw=raw, strategy="direct")

    # 2 — inside a code fence.
    fenced = _FENCE.search(raw)
    if fenced:
        candidate = fenced.group(1).strip()
        parsed = _loads(candidate)
        if parsed is not _FAILED:
            return JsonParseOutcome(
                value=parsed,
                raw=raw,
                strategy="fenced",
                repaired=True,
                repairs=("code_fence_stripped",),
                unparsed=_outside(raw, fenced.start(), fenced.end()),
            )

    # 3 — a balanced object or array embedded in prose.
    span = _find_balanced(raw)
    if span is not None:
        start, end = span
        parsed = _loads(raw[start:end])
        if parsed is not _FAILED:
            return JsonParseOutcome(
                value=parsed,
                raw=raw,
                strategy="embedded",
                repaired=True,
                repairs=("extracted_from_prose",),
                unparsed=_outside(raw, start, end),
            )

    # 4 — repaired.
    repaired_text = _repair(raw, attempt)
    candidate = repaired_text
    span = _find_balanced(repaired_text)
    if span is not None:
        start, end = span
        candidate = repaired_text[start:end]
        attempt.note("extracted_from_prose")
    parsed = _loads(candidate)
    if parsed is not _FAILED:
        return JsonParseOutcome(
            value=parsed,
            raw=raw,
            strategy="repaired",
            repaired=True,
            repairs=tuple(attempt.repairs),
            unparsed=_outside(raw, 0, 0) if candidate == repaired_text else "",
        )

    # 5 — truncated: close what the model left open.
    closed = _close_truncated(candidate, attempt)
    if closed is not None:
        parsed = _loads(closed)
        if parsed is not _FAILED:
            return JsonParseOutcome(
                value=parsed,
                raw=raw,
                strategy="truncation_closed",
                repaired=True,
                repairs=tuple(attempt.repairs),
                unparsed="",
            )

    return JsonParseOutcome(
        raw=raw,
        strategy="none",
        repaired=False,
        repairs=tuple(attempt.repairs),
        error="model output could not be parsed as JSON, with or without repair",
        unparsed=raw[:4000],
    )


# ── internals ────────────────────────────────────────────────────────────────

#: Sentinel distinguishing "parsed to None" (valid JSON ``null``) from "failed".
_FAILED = object()


def _loads(candidate: str) -> Any:
    if not candidate.strip():
        return _FAILED
    try:
        return json.loads(candidate)
    except (ValueError, RecursionError):
        return _FAILED


def _repair(text: str, attempt: _Attempt) -> str:
    """Conservative, value-preserving fixes. Order matters: strip wrappers
    before touching content, and never touch anything inside a string."""
    out = text.strip()

    fenced = _FENCE.search(out)
    if fenced:
        out = fenced.group(1).strip()
        attempt.note("code_fence_stripped")
    elif out.startswith("```"):
        # An opening fence whose closing fence the model never emitted.
        out = re.sub(r"^```(?:json|JSON)?\s*", "", out).strip()
        attempt.note("unterminated_code_fence_stripped")

    translated = out.translate(_SMART_QUOTES)
    if translated != out:
        out = translated
        attempt.note("smart_quotes_normalised")

    stripped = _strip_comments(out)
    if stripped != out:
        out = stripped
        attempt.note("comments_removed")

    for pattern, replacement in _PY_LITERALS:
        replaced = pattern.sub(replacement, out)
        if replaced != out:
            out = replaced
            attempt.note("python_literals_converted")

    # A Python ``repr`` rather than JSON — models trained on a lot of Python do
    # this. Only when there is not a single double quote in the text: with both
    # quote styles present, swapping would corrupt a legitimate apostrophe
    # inside a string, and corrupting data to make it parse is worse than
    # failing to parse.
    if "'" in out and '"' not in out:
        out = out.replace("'", '"')
        attempt.note("single_quotes_converted")

    without_commas = _TRAILING_COMMA.sub(r"\1", out)
    if without_commas != out:
        out = without_commas
        attempt.note("trailing_commas_removed")

    return out


def _strip_comments(text: str) -> str:
    """Remove ``//`` and ``/* */`` comments that fall outside string literals.

    String-aware because ``"url": "https://x"`` is data, and a naive strip
    turns it into a syntax error while claiming to have fixed one.
    """
    if "//" not in text and "/*" not in text:
        return text

    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _find_balanced(text: str) -> tuple[int, int] | None:
    """Span of the first balanced ``{…}`` / ``[…]``, ignoring brackets in strings.

    Finding the object inside prose is *parsing*. Anything cleverer — guessing
    which of two objects was meant, stitching fragments together — would be
    inventing, and inventing is what V2 forbids.
    """
    start = None
    opener = ""
    for index, ch in enumerate(text):
        if ch in "{[":
            start = index
            opener = ch
            break
    if start is None:
        return None

    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return start, index + 1
    return None


def _close_truncated(text: str, attempt: _Attempt) -> str | None:
    """Close brackets a truncated generation left open, dropping the partial tail.

    A model that hit its token ceiling mid-object leaves a prefix of valid JSON.
    Closing it recovers every *complete* field and loses only the fragment that
    was never finished — which is strictly better than discarding the whole
    answer, and honest as long as the caller is told (``repaired``) that this
    happened.
    """
    if not text.strip():
        return None

    boundaries = _element_boundaries(text)
    if boundaries is None:
        return None  # nothing was left open; truncation is not the problem
    if not boundaries:
        return None

    # Try the latest cut first and walk backwards. A single "best guess" cut
    # fails whenever the model stopped somewhere the closers cannot be appended
    # cleanly — mid-key, just after an opening brace, or on a trailing comma —
    # which measured at roughly a third of all cut positions on a long invoice.
    # Backtracking to the previous complete element costs one line item and
    # turns those failures into answers.
    for cut in reversed(boundaries[-MAX_TRUNCATION_BACKTRACKS:]):
        head = text[:cut].rstrip().rstrip(",")
        stack = _open_containers(head)
        if stack is None:
            continue
        candidate = head + "".join(reversed(stack))
        if _loads(candidate) is not _FAILED:
            attempt.note("truncated_output_closed")
            if text[cut:].strip(" \t\r\n,"):
                # Real content was discarded to make this parse. The caller
                # deserves to know: silently dropping a half-written line item
                # is exactly the quiet loss this module exists to prevent.
                attempt.note("incomplete_trailing_element_dropped")
            return candidate
    return None


MAX_TRUNCATION_BACKTRACKS = 64
"""How far back to walk looking for a cut that closes cleanly. Each step gives
up one array element or object member; sixty-four is far more than a truncated
response ever needs and keeps a pathological input bounded."""


def _element_boundaries(text: str) -> list[int] | None:
    """Indices just past each completed element, outermost-last.

    ``None`` means the text is not truncated at all (every container closed), in
    which case closing it is not the repair being looked for.
    """
    stack = 0
    in_string = False
    escape = False
    boundaries: list[int] = []

    for index, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack += 1
        elif ch in "}]":
            stack -= 1
            if stack < 0:
                return None
            boundaries.append(index + 1)
        elif ch == ",":
            # A comma proves whatever preceded it was a complete element.
            boundaries.append(index)

    if stack == 0 and not in_string:
        return None
    return boundaries


def _open_containers(text: str) -> list[str] | None:
    """Closers needed to balance ``text``, or ``None`` if it cannot be balanced.

    Refuses a prefix that ends inside a string or on a dangling key: appending
    brackets there produces syntax, not data.
    """
    stack: list[str] = []
    in_string = False
    escape = False

    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack:
                return None
            stack.pop()

    if in_string:
        return None
    if re.search(r'"[^"]*"\s*:\s*$', text):
        return None  # a key with no value; the next cut back will do better
    return stack


def _outside(text: str, start: int, end: int) -> str:
    """Everything that was not the recovered JSON, preserved as evidence."""
    if start == 0 and end == 0:
        return ""
    prefix = text[:start].strip()
    suffix = text[end:].strip()
    joined = "\n".join(part for part in (prefix, suffix) if part)
    return joined[:4000]


__all__ = ["JsonParseOutcome", "parse_model_json"]
