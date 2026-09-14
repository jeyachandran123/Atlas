"""Turn a natural-language request plus a file's real structure into Python.

The model's job here is small and well-suited to it: read a request, read an
exact column list, and write twenty lines of pandas or openpyxl. It is not
asked to produce the data - the 3136-row output of a real transform is about
half a million tokens, six hours of decoding, and wrong in ways nobody could
check. The code that produces those rows is 800 tokens and runs in two seconds.

The rules below are not style preferences. Each one is a failure that shows up
in generated spreadsheet code and reaches the user as a corrupted file:
``nan`` written into cells that were blank, a column silently dropped by a
default ``to_excel`` call, or a KeyError from a column name the model guessed
at rather than copied.
"""

from __future__ import annotations

import ast
import re

from app.document_platform.conversation.prompts import StructuredPrompt

CODE_MAX_TOKENS = 1600
"""Enough for a substantial transform with comments. At the deployment's ~22
tokens/sec that is a worst case of about 70s, inside the request timeout."""

_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_+-]*\s*\n(.*?)\n?\s*```\s*$", re.DOTALL)
_LEADING_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_+-]*\s*\n", re.IGNORECASE)

SYSTEM = """You write Python that transforms or analyses one document.

It runs in a container with no network. These are the ONLY libraries present,
written as you must import them - the import name is not the package name:

    import pandas            import numpy           import openpyxl
    import xlsxwriter        import docx            (python-docx: Word)
    from pypdf import PdfReader, PdfWriter          (read/merge PDF)
    from reportlab.lib.pagesizes import A4          (WRITE PDF)
    from reportlab.platypus import SimpleDocTemplate, Table, Paragraph
    from PIL import Image    (Pillow - NEVER "import pillow")
    import pptx              (python-pptx)          import lxml
    plus the standard library.

matplotlib, bs4, fpdf and weasyprint are NOT installed. Do not pip install.
To WRITE a PDF use reportlab; there is nothing else.

PATHS
INPUT_PATH and OUTPUT_PATH are already defined for you. Use them as-is.
- To ANSWER A QUESTION: compute it and print() the answer. Write no file.
- To PRODUCE A FILE: write it to OUTPUT_PATH.
Always print a one-line summary (rows in, rows out).

SPREADSHEETS - use pandas, not openpyxl, unless you need cell formatting:
    df = pd.read_excel(INPUT_PATH, dtype=object, keep_default_na=False)
    rows = []
    for _, row in df.iterrows():
        new = row.to_dict()              # keeps all columns as they were
        new["Code"] = f"{row['Code']}-{suffix}"
        rows.append(new)
    out = pd.DataFrame(rows, columns=df.columns)
    out.to_excel(OUTPUT_PATH, index=False)
``dtype=object`` and ``keep_default_na=False`` are what keep blank cells blank.
pandas 2 has no DataFrame.append() - build a list and call pd.DataFrame once.

THE TRAP THAT FOLLOWS FROM dtype=object
Every cell comes back as a STRING, including ID and number columns. Comparing
them to numbers silently matches nothing and writes an empty file:

    df[df["Id"].isin([24798, 24981])]            # WRONG - 0 rows, ints vs str
    ids = {"24798", "24981"}                     # right
    df[df["Id"].astype(str).str.strip().isin(ids)]

Compare as strings, or coerce both sides. The same applies to >, < and ==.

"ADD A FILTER TO COLUMN X" MEANS AN EXCEL FILTER DROPDOWN, NOT DROPPING ROWS.
Keep every row and turn on autofilter over that column:

    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter
    wb = load_workbook(INPUT_PATH); ws = wb.active
    col = [c.value for c in ws[1]].index("Label") + 1
    letter = get_column_letter(col)
    ws.auto_filter.ref = f"{letter}1:{letter}{ws.max_row}"
    wb.save(OUTPUT_PATH)

Only remove rows when the request actually says to remove, keep or show a
subset.

RULES
1. Use the exact column names listed below, character for character.
2. Values the request spells out - codes, suffixes, label text - go into a
   literal dict and are used whole. Never derive them by slicing or
   abbreviating, and never reorder the pieces of a phrase the request gave you.
3. Do the negative instructions too: if other fields must be blank, set them
   blank. Copying a row forward keeps their old values.
4. Copy every column through, in the original order, unless told otherwise.
5. Work over the whole file. Never sample or truncate.
6. Check your result before writing it. Assert what the request states - row
   counts, which fields are set, which are blank - and give every assert a
   message naming the actual and expected value.

Reply with Python source only: no fences, no prose. The first line must be
valid Python."""


def _strip_fences(text: str) -> str:
    """Models wrap code in fences even when told not to; unwrap rather than fail."""
    match = _FENCE.match(text.strip())
    if match:
        return match.group(1)
    cleaned = _LEADING_FENCE.sub("", text.strip())
    if cleaned.rstrip().endswith("```"):
        cleaned = cleaned.rstrip()[:-3]
    return cleaned.strip()


def extract_code(raw: str) -> str:
    """The model's reply, reduced to something that can be written to a .py file."""
    code = _strip_fences(raw)
    # A model that ignores "code only" tends to open with a sentence. Drop any
    # leading prose, keeping from the first line that could start a program.
    lines = code.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^(import |from |#|\"\"\"|'''|INPUT_PATH|OUTPUT_PATH|def |[A-Za-z_]\w*\s*=)",
                    stripped):
            return "\n".join(lines[i:]).strip()
    return code


_MISSING_KEY = re.compile(
    r"KeyError:\s*[\"'](?P<key>[^\"']+)[\"']"
    r"|None of \[(?P<keys>[^\]]+)\] are in the \[columns\]"
    r"|\[(?P<label>'[^\]]+')\] not (?:found )?in axis"
)


def column_hint(error_text: str, headers: list[str]) -> str:
    """Name the column the code should have used, when it used one that is not there.

    This is the single most common way generated spreadsheet code fails, and it
    is the one a model cannot reliably repair on its own: the request says
    "Easy to Chew", the sheet says "Easy to chew", and one capital letter buried
    among seventy-seven column names is invisible in a traceback. Left alone the
    model rewrites the same KeyError until the attempts run out.

    Matching is done here rather than by the model because it is a string
    comparison, not a judgement - so it is exact, free, and always right.
    """
    if not headers:
        return ""
    match = _MISSING_KEY.search(error_text)
    if not match:
        return ""
    raw = match.group("key") or match.group("keys") or match.group("label") or ""
    wanted = [k.strip().strip("\"'") for k in raw.split(",") if k.strip()]

    lines: list[str] = []
    lower = {h.lower(): h for h in headers}
    for name in wanted:
        if name in headers:
            continue
        exact_case = lower.get(name.lower())
        if exact_case:
            lines.append(f'  {name!r} does not exist. The real column is {exact_case!r} '
                         f'(same words, different capitalisation).')
            continue
        import difflib

        close = difflib.get_close_matches(name, headers, n=3, cutoff=0.6)
        if close:
            lines.append(f"  {name!r} does not exist. Closest real columns: "
                         + ", ".join(repr(c) for c in close))
        else:
            lines.append(f"  {name!r} does not exist and nothing in the file is close to it. "
                         f"Re-read the column list and pick the right one.")
    if not lines:
        return ""
    return (
        "COLUMN NAME MISMATCH - this is why it failed:\n"
        + "\n".join(lines)
        + "\nUse the exact names from the column list. Do not re-type them from "
          "the request; the request and the file disagree, and the file wins."
    )


_LIST_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s*")
_INLINE_ITEM = re.compile(r"\d+[.)]\s*([A-Za-z][A-Za-z0-9 &/'\-]{2,40}?)(?=\s*\d+[.)]|\s*$)")
_SPLIT = re.compile(r"[,;|]|->|=|\s{2,}|:")


def _phrases(request: str):
    """Fragments of the request that might be naming a column.

    Lines, list items and comma-separated pieces - not free-running text. A
    greedy scan over the whole request produces one enormous match per line and
    matches nothing; the useful unit is the fragment a person would write a
    column name in.
    """
    for line in request.splitlines():
        line = _LIST_MARKER.sub("", line.strip())
        if not line:
            continue
        yield line
        for part in _SPLIT.split(line):
            part = part.strip()
            if part:
                yield part
    for match in _INLINE_ITEM.finditer(request):
        yield match.group(1).strip()


def request_column_map(request: str, headers: list[str]) -> str:
    """Resolve the names a person used to the names the file uses, up front.

    People write the columns the way they say them - "Easy to Chew", "Soft &
    Bite" - and the sheet spells them "Easy to chew" and "Soft and bite-sized".
    That mismatch is not an edge case, it is the normal case, and left to the
    first attempt it costs a full generate-run-repair cycle every time: the
    model copies the request's spelling, gets a KeyError, and only then learns
    the real name.

    Doing the match before the first attempt removes that cycle. It is the same
    string comparison the repair hint does, run earlier, where it is cheap.
    """
    if not headers:
        return ""
    import difflib

    lower = {h.lower(): h for h in headers}
    seen: dict[str, str] = {}

    for raw in _phrases(request):
        phrase = raw.strip(" .,:;-")
        if len(phrase) < 3 or phrase in seen or phrase in headers:
            continue
        # A case-only difference is still a KeyError - pandas does not fold
        # case - and it is the one a person is least likely to spot.
        same_words = lower.get(phrase.lower())
        if same_words:
            seen[phrase] = same_words
            continue
        # Only phrases that plainly mean a column: close to a real header, and
        # not merely sharing a common word with one.
        close = difflib.get_close_matches(phrase.lower(), list(lower), n=1, cutoff=0.75)
        if not close:
            normalised = phrase.lower().replace("&", "and")
            close = difflib.get_close_matches(normalised, list(lower), n=1, cutoff=0.8)
        if close:
            real = lower[close[0]]
            if real.lower() != phrase.lower():
                seen[phrase] = real

    if not seen:
        return ""
    lines = [f"  the request says {said!r} -> the column is {real!r}"
             for said, real in list(seen.items())[:25]]
    return (
        "COLUMN NAMES IN THE REQUEST DO NOT MATCH THE FILE.\n"
        "Use the right-hand name in your code; the file's spelling wins.\n"
        + "\n".join(lines)
    )


_MISSING_MODULE = re.compile(r"ModuleNotFoundError: No module named ['\"](?P<mod>[^'\"]+)['\"]")

# What a model reaches for, and what is actually here. The left side is not a
# typo in most cases - it is the package name (pillow, fpdf2) or a library that
# simply is not installed; the import name and the availability are what differ.
_MODULE_ALIASES = {
    "pillow": "PIL (from PIL import Image) - 'pillow' is the package name, 'PIL' is the import",
    "python_docx": "docx (import docx)",
    "python-docx": "docx (import docx)",
    "pythondocx": "docx (import docx)",
    "python_pptx": "pptx (import pptx)",
    "sklearn": "not installed - do it with pandas or the standard library",
    "matplotlib": "not installed - there is no charting library; describe data in text or a table",
    "seaborn": "not installed - there is no charting library",
    "bs4": "lxml (from lxml import html, etree) - BeautifulSoup is not installed",
    "beautifulsoup4": "lxml (from lxml import html, etree)",
    "fpdf": "reportlab - use reportlab.platypus to write PDFs",
    "fpdf2": "reportlab - use reportlab.platypus to write PDFs",
    "weasyprint": "reportlab - use reportlab.platypus to write PDFs",
    "pdfkit": "reportlab - use reportlab.platypus to write PDFs",
    "fitz": "pypdf (from pypdf import PdfReader) - PyMuPDF is not installed",
    "pymupdf": "pypdf (from pypdf import PdfReader)",
    "PyPDF2": "pypdf (from pypdf import PdfReader) - PyPDF2 is the old name",
    "xlrd": "pandas.read_excel with openpyxl, which handles .xlsx",
    "docx2txt": "docx (import docx)",
    "tabula": "not installed - read tables with pandas or pypdf text extraction",
    "camelot": "not installed - read tables with pandas or pypdf text extraction",
}

AVAILABLE = (
    "pandas, numpy, openpyxl, xlsxwriter, docx (python-docx), pypdf, reportlab, "
    "PIL (Pillow), pptx (python-pptx), lxml, and the standard library"
)


def module_hint(error_text: str) -> str:
    """Name the library that exists, when the code imported one that does not.

    The container is fixed and offline, so a missing import is never solved by
    installing something - it is solved by using what is there. A model told
    only "No module named 'pillow'" will try 'pillow' again, or reach for
    another absent library; told that the import is 'PIL', it moves on.
    """
    match = _MISSING_MODULE.search(error_text)
    if not match:
        return ""
    missing = match.group("mod").split(".")[0]
    replacement = _MODULE_ALIASES.get(missing) or _MODULE_ALIASES.get(missing.lower())
    lines = [f"IMPORT ERROR: {missing!r} is not installed and cannot be installed."]
    if replacement:
        # Some entries name a substitute, others say there is none; only the
        # first kind reads as an instruction.
        lines.append(
            replacement[0].upper() + replacement[1:] + "."
            if replacement.startswith("not installed")
            else f"Use {replacement}."
        )
    lines.append(f"Everything available: {AVAILABLE}.")
    lines.append("Rewrite the program using only those.")
    return "\n".join(lines)


NOT_PYTHON_HINT = (
    "Your reply was not a Python program - it could not be parsed:\n"
    "  {error}\n"
    "Reply with Python source only. No JSON, no markdown, no prose, no code "
    "fences. The first line must be valid Python."
)


def python_error(code: str) -> str:
    """Why this reply is not a program, or empty if it is one.

    Checked before the container is started: a reply that is JSON, prose or a
    fenced block fails identically every time, and finding that out through a
    two-second sandbox round trip wastes an attempt and tells the model less
    than the parser does.
    """
    if not code.strip():
        return "The reply was empty."
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return f"{type(exc).__name__}: {exc.msg} (line {exc.lineno})"
    return ""


def build_script(code: str, input_path: str, output_path: str) -> str:
    """The generated code, with the paths it was promised actually bound.

    The prompt tells the model INPUT_PATH and OUTPUT_PATH are given to it, and
    the model reasonably takes that literally and uses them without assigning
    them - which is a NameError on line one, repeated through every repair
    attempt because the model does not believe it is the one at fault. It is
    not: the prompt made a promise. This keeps it.

    A script that assigns them anyway simply shadows these with the same
    values, so both styles run.
    """
    preamble = (
        "# Bound by the platform - the paths this script was given.\n"
        f"INPUT_PATH = {input_path!r}\n"
        f"OUTPUT_PATH = {output_path!r}\n"
        f"input_path = INPUT_PATH\n"
        f"output_path = OUTPUT_PATH\n"
    )
    return preamble + "\n" + code


def build_prompt(
    structure_text: str,
    request: str,
    input_path: str,
    output_path: str,
    previous_code: str = "",
    previous_error: str = "",
    column_map: str = "",
) -> StructuredPrompt:
    """The first attempt, or a repair attempt when the last one failed.

    A repair sends back the code and the traceback rather than restating the
    task from scratch: the model is far better at fixing a named error on a
    line it can see than at re-deriving the whole transform and hoping.
    """
    parts = [
        "# DOCUMENT STRUCTURE",
        structure_text,
    ]
    if column_map:
        parts += ["", "# NAME RESOLUTION", column_map]
    parts += [
        "",
        "# PATHS",
        f'INPUT_PATH = "{input_path}"',
        f'OUTPUT_PATH = "{output_path}"',
        "",
        "# REQUEST",
        request.strip(),
    ]
    if previous_error:
        parts += [
            "",
            "# YOUR PREVIOUS ATTEMPT FAILED",
            "This is the code you wrote:",
            "```python",
            previous_code.strip()[:6000],
            "```",
            "",
            "It failed with:",
            "```",
            previous_error.strip()[:4000],
            "```",
            "",
            "Fix the cause and reply with the complete corrected program. "
            "Check the column names above against the ones your code used.",
        ]
    parts += [
        "",
        "Reply with the complete Python program and nothing else.",
    ]
    return StructuredPrompt(
        system=SYSTEM,
        user="\n".join(parts),
        strategy="document_task_code",
        max_output_tokens=CODE_MAX_TOKENS,
    )
