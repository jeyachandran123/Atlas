"""A second look at a table written from memory, before it becomes a file.

A model writing a long table drifts from its own brief: a list asked for
"2021 to 2026, sorted by year" comes back with a 2016 row in it and in no
particular order. Asking it to try harder does not fix that; checking does.

The check is deliberately narrow. The model is shown the request and the
numbered rows and answers with row numbers to drop and the order to sort by —
a few dozen tokens. Code applies the verdict, so the check can remove rows and
reorder them but never rewrites, adds or invents one. And a check that fails
for any reason leaves the table as it was: it is a filter on the file, never a
reason to lose it.
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable

from loguru import logger

REVIEW_SYSTEM = """You check a table against the request it was written for. Reply with ONE JSON object and nothing else:
{"drop": [row numbers], "sort": [{"column": "exact column name", "descending": true or false}]}

- drop: every row that breaks a criterion the request states explicitly — outside the requested date or year range, the wrong type, category, origin or region, or a repeat of another row. Judge only against what the request says; never drop a row merely because you are unsure of it.
- sort: the ordering the request asks for, most important key first. An empty list if it asks for none.
Row numbers are the numbers at the start of each row."""

_MAX_REVIEW_ROWS = 400
_JSON = re.compile(r"\{.*\}", re.DOTALL)
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

SpecReview = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def parse_verdict(text: str) -> dict[str, Any] | None:
    match = _JSON.search(re.sub(r"```(?:json)?", "", text or ""))
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _number(value: str) -> float | None:
    v = value.replace(",", "").strip()
    return float(v) if _NUMBER.fullmatch(v) else None


def _sort_keys(raw: Any) -> list[tuple[str, bool]]:
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    keys = []
    for item in raw:
        if isinstance(item, dict) and str(item.get("column") or "").strip():
            keys.append((str(item["column"]).strip().casefold(), bool(item.get("descending"))))
    return keys


def apply_review(
    rows: list[list[str]], headers: list[str], verdict: dict[str, Any],
) -> list[list[str]]:
    """Rows with the verdict applied: some dropped, the rest reordered, none changed."""
    drop = set()
    for n in verdict.get("drop") or []:
        try:
            drop.add(int(n))
        except (TypeError, ValueError):
            continue
    kept = [r for i, r in enumerate(rows, 1) if i not in drop]
    if not kept:
        # Dropping everything is a misreading of the request, not a result.
        logger.warning("Table review would have emptied the table; keeping it as written")
        kept = list(rows)

    folded = [h.strip().casefold() for h in headers]
    # Stable sorts applied from the least important key to the most important
    # give a multi-key order ("year descending, then title").
    for column, descending in reversed(_sort_keys(verdict.get("sort"))):
        if column not in folded:
            continue
        idx = folded.index(column)

        def cell(r: list[str], idx: int = idx) -> str:
            return (r[idx] if idx < len(r) else "").strip()

        filled = [r for r in kept if cell(r)]
        blank = [r for r in kept if not cell(r)]
        if all(_number(cell(r)) is not None for r in filled):
            filled.sort(key=lambda r: _number(cell(r)) or 0.0, reverse=descending)
        else:
            filled.sort(key=lambda r: cell(r).casefold(), reverse=descending)
        kept = filled + blank  # an empty cell sorts last either way
    return kept


def _as_rows(raw: Any, headers: list[str]) -> list[list[str]]:
    rows = []
    for r in raw:
        if isinstance(r, list):
            rows.append([str(c) if c is not None else "" for c in r])
        elif isinstance(r, dict):
            rows.append([str(r.get(h, "") or "") for h in headers])
    return rows


def make_table_review(brief: str) -> SpecReview:
    """A spec review that checks every table in a plan against ``brief``."""

    async def review(spec: dict[str, Any]) -> dict[str, Any]:
        from app.llm import GENERAL, get_chat_gateway

        for section in spec.get("sections") or []:
            table = section.get("table") if isinstance(section, dict) else None
            if not isinstance(table, dict):
                continue
            headers = [str(h) for h in table.get("headers") or []]
            raw = table.get("rows")
            if not headers or not isinstance(raw, list) or not 2 <= len(raw) <= _MAX_REVIEW_ROWS:
                continue
            rows = _as_rows(raw, headers)
            listing = "\n".join(f"{i}. " + " | ".join(r) for i, r in enumerate(rows, 1))
            user = (
                f"# Request\n{brief}\n\n# Columns\n{' | '.join(headers)}\n\n# Rows\n{listing}"
            )
            try:
                result = await get_chat_gateway().complete(
                    user=user, system=REVIEW_SYSTEM, profile=GENERAL,
                    thinking=False, temperature=0.0, max_tokens=800,
                )
            except Exception as e:  # noqa: BLE001 - the table stands unchecked
                logger.warning(f"Table review unavailable ({e}); keeping the table as written")
                continue
            verdict = parse_verdict(result.text)
            if verdict is None:
                continue
            checked = apply_review(rows, headers, verdict)
            dropped = [r for r in rows if r not in checked]
            # What was dropped is logged, so a check that went too far can be seen.
            logger.info(
                f"Table review: {len(rows)} rows, {len(dropped)} dropped, "
                f"sort={_sort_keys(verdict.get('sort'))}"
                + (f"; dropped e.g. {[' | '.join(r)[:60] for r in dropped[:10]]}" if dropped else "")
            )
            table["rows"] = checked
        return spec

    return review
