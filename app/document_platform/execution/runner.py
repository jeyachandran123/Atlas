"""One document, one request, one answer or one file.

The loop is the whole design: describe the file, write code against that
description, run it, and if it fails hand the traceback back to the model. A
first attempt that dies on a mistyped column name is normal and recoverable;
what is not recoverable is a system that reports "error" and stops, which is
what makes generated-code approaches feel unusable.

Attempts are bounded because the failures worth fixing are fixed on the first
retry - a wrong column, a wrong dtype, a missing import. A model still failing
on the third try is misunderstanding the request, and burning more attempts
turns a 30-second answer into a three-minute one without changing the outcome.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import AsyncIterator, Callable

from loguru import logger

from app.document_platform.execution import codegen
from app.document_platform.execution.introspect import DocumentStructure, introspect
from app.document_platform.execution.model import CodegenError, get_codegen_model
from app.document_platform.execution.preview import ResultPreview, preview_output
from app.document_platform.execution.sandbox import (
    SandboxResult,
    SandboxUnavailableError,
    run_python,
)

MAX_ATTEMPTS = 3
"""One attempt plus two repairs."""

OUTPUT_STEM = "output"


@dataclass
class Attempt:
    number: int
    code: str
    ok: bool
    stdout: str
    error: str
    duration_ms: int


@dataclass
class TaskResult:
    ok: bool
    kind: str                                  # "file" | "answer" | "failed"
    request: str
    structure: DocumentStructure | None = None
    code: str = ""
    answer: str = ""
    output_bytes: bytes | None = None
    output_name: str = ""
    preview: ResultPreview | None = None
    attempts: list[Attempt] = field(default_factory=list)
    error: str = ""
    llm_ms: int = 0
    sandbox_ms: int = 0

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


def _output_name(input_name: str, requested_format: str | None) -> str:
    """What the generated code should write, so we know what to collect."""
    if requested_format:
        ext = requested_format.lower().lstrip(".")
        ext = {"excel": "xlsx", "word": "docx", "markdown": "md"}.get(ext, ext)
        return f"{OUTPUT_STEM}.{ext}"
    ext = input_name.rsplit(".", 1)[-1].lower() if "." in input_name else "xlsx"
    return f"{OUTPUT_STEM}.{ext}"


NO_OUTPUT_HINT = (
    "The script finished without writing a file and without printing "
    "anything, so there is no result. If the request asks a question, "
    "compute the answer and print() it in a readable sentence. If it asks for a file, write it to OUTPUT_PATH. Do both only if both were asked for."
)


EMPTY_RESULT_HINT = (
    "The script ran but produced a file with no data rows, only a header, "
    "while the input had rows. Nothing matched.\n"
    "The usual cause: pd.read_excel(..., dtype=object) returns every cell as a "
    "string, so comparing an id or number column against integers matches "
    "nothing. Compare as strings - df[df['Id'].astype(str).str.strip()"
    ".isin({'24798', '24981'})] - or coerce both sides.\n"
    "Check the sample rows above for how the values are really written, then "
    "rewrite the program."
)


def _empty_result(
    output_bytes: bytes | None, output_name: str, structure: DocumentStructure,
) -> bool:
    """Did the run write a file that has nothing in it?

    Only spreadsheets are judged here, and only when the input had rows: an
    empty output is a legitimate answer to "keep the rows matching X" when
    nothing matches, but it is never what a person meant when the input had
    1251 rows and they named three ids that are in it.
    """
    if not output_bytes:
        return False
    if not output_name.lower().endswith((".xlsx", ".xlsm", ".csv")):
        return False
    source_rows = structure.sheets[0].rows if structure.sheets else 0
    if source_rows <= 0:
        return False
    try:
        preview = preview_output(output_bytes, output_name, structure)
    except Exception:  # noqa: BLE001 - unreadable is a different failure
        return False
    return preview.row_count == 0


class DocumentTaskRunner:
    """Runs one natural-language document task to completion."""

    def __init__(self, settings=None) -> None:
        if settings is None:
            from app.config import get_settings

            settings = get_settings()
        self._settings = settings
        self._image = getattr(settings, "dip_sandbox_image", "ai-coding-assistant:latest")
        self._timeout = int(getattr(settings, "dip_sandbox_timeout_seconds", 120))
        self._memory = str(getattr(settings, "dip_sandbox_memory", "2g"))
        self._cpus = str(getattr(settings, "dip_sandbox_cpus", "2"))
        self._max_attempts = int(getattr(settings, "dip_task_max_attempts", MAX_ATTEMPTS))

    async def run(
        self,
        data: bytes,
        filename: str,
        request: str,
        *,
        requested_format: str | None = None,
        on_stage: Callable[[str, dict], None] | None = None,
    ) -> TaskResult:
        stages = on_stage or (lambda *_: None)
        result = TaskResult(ok=False, kind="failed", request=request)

        stages("inspecting_document", {"filename": filename})
        structure = await asyncio.to_thread(introspect, data, filename)
        result.structure = structure
        logger.info(f"Document task on {filename}: {structure.summary}")

        input_name = f"input.{filename.rsplit('.', 1)[-1].lower()}" if "." in filename else "input"
        output_name = _output_name(filename, requested_format)
        input_path = f"/work/{input_name}"
        output_path = f"/work/{output_name}"
        send_samples = bool(getattr(self._settings, "dip_codegen_send_samples", True))
        structure_text = structure.as_prompt_text(include_samples=send_samples)
        headers = structure.sheets[0].headers if structure.sheets else []
        column_map = codegen.request_column_map(request, headers)
        if column_map:
            logger.info("Resolved column names from the request:" + "\n" + column_map)

        model = get_codegen_model(self._settings)
        code = ""
        run: SandboxResult | None = None

        for attempt in range(1, self._max_attempts + 1):
            stages(
                "writing_code" if attempt == 1 else "fixing_code",
                {"attempt": attempt, "of": self._max_attempts},
            )
            failure = ""
            if run is not None and attempt > 1:
                # A column or a library that does not exist is diagnosed here
                # rather than left to the model. Both are lookups, not
                # judgements, and a model left to guess spends the whole
                # attempt budget re-making the same mistake: it retyped
                # "Easy to Chew" three times, and reached for "import pillow"
                # where the import is PIL.
                failure = run.failure_text
                hints = [
                    codegen.module_hint(failure),
                    codegen.column_hint(failure, headers),
                ]
                lead = "\n\n".join(h for h in hints if h)
                if lead:
                    failure = f"{lead}\n\n{failure}"
            prompt = codegen.build_prompt(
                structure_text, request, input_path, output_path,
                column_map=column_map,
                previous_code=code if attempt > 1 else "",
                previous_error=failure,
            )
            try:
                llm = await model.complete(
                    prompt.system, prompt.user, codegen.CODE_MAX_TOKENS
                )
            except CodegenError as e:
                result.error = f"The code-writing model could not be reached: {e}"
                return result
            result.llm_ms += llm.latency_ms
            logger.info(
                f"Codegen attempt {attempt} via {llm.provider}/{llm.model}: "
                f"{llm.completion_tokens} tokens in {llm.latency_ms}ms "
                f"({llm.tokens_per_second:.0f} tok/s)"
            )
            code = codegen.extract_code(llm.text)
            syntax = codegen.python_error(code)
            if syntax:
                # A reply that is JSON or prose fails the same way every time;
                # the parser says why in less time than starting a container.
                message = codegen.NOT_PYTHON_HINT.format(error=syntax)
                run = replace(
                    SandboxResult(ok=False, exit_code=-1, stdout="", stderr=message,
                                  duration_ms=0),
                    ok=False,
                )
                result.attempts.append(
                    Attempt(attempt, code, False, "", message, 0))
                logger.info(f"Attempt {attempt} was not Python: {syntax}")
                continue

            stages("running_code", {"attempt": attempt})
            try:
                script = codegen.build_script(code, input_path, output_path)
                run = await asyncio.to_thread(
                    run_python, script, data, input_name, output_name,
                    image=self._image, timeout_seconds=self._timeout,
                    memory=self._memory, cpus=self._cpus,
                )
            except SandboxUnavailableError as e:
                result.error = str(e)
                return result
            result.sandbox_ms += run.duration_ms
            result.attempts.append(Attempt(
                number=attempt, code=code, ok=run.ok,
                stdout=run.stdout, error="" if run.ok else run.failure_text,
                duration_ms=run.duration_ms,
            ))
            if run.ok and not run.output_bytes and not run.stdout.strip():
                # No file and nothing printed: the script ran to completion and
                # said nothing, which answers no question and produces no
                # document. Silence is not a result.
                if attempt < self._max_attempts:
                    logger.info(f"Attempt {attempt} produced no output; repairing")
                    run = replace(run, ok=False, stderr=NO_OUTPUT_HINT)
                    result.attempts[-1] = replace(
                        result.attempts[-1], ok=False, error=NO_OUTPUT_HINT)
                    continue
            if run.ok:
                empty = _empty_result(run.output_bytes, output_name, structure)
                if not empty or attempt == self._max_attempts:
                    break
                # Exiting zero having written a header and no rows is the
                # loudest quiet failure this produces: the file opens, the
                # download works, and there is nothing in it. It is almost
                # always a comparison that matched nothing - numbers read as
                # strings under dtype=object - so it is worth one more attempt
                # with that said out loud.
                logger.info(f"Attempt {attempt} produced an empty file; repairing")
                run = replace(run, ok=False, stderr=EMPTY_RESULT_HINT)
                result.attempts[-1] = replace(
                    result.attempts[-1], ok=False, error=EMPTY_RESULT_HINT,
                )
                continue
            logger.info(f"Attempt {attempt}/{self._max_attempts} failed; repairing")

        result.code = code
        if run is None or not run.ok:
            result.error = (
                run.failure_text if run else "The model did not produce runnable code."
            )
            stages("failed", {"attempts": len(result.attempts)})
            return result

        # A file was written, or the answer was printed. Both are successes;
        # which one happened is decided by what the code actually produced,
        # not by guessing the user's intent up front.
        if run.output_bytes:
            stages("validating", {"bytes": len(run.output_bytes)})
            result.preview = await asyncio.to_thread(
                preview_output, run.output_bytes, output_name, structure,
            )
            result.ok = True
            result.kind = "file"
            result.output_bytes = run.output_bytes
            result.output_name = output_name
            result.answer = run.stdout.strip()
        else:
            result.ok = True
            result.kind = "answer"
            result.answer = run.stdout.strip() or "The script produced no output."
        stages("done", {"kind": result.kind})
        return result

    async def run_streaming(
        self, data: bytes, filename: str, request: str,
        *, requested_format: str | None = None,
    ) -> AsyncIterator[tuple[str, dict]]:
        """Same run, with stage events forwarded as they happen.

        The work takes tens of seconds and the stages are meaningful to a
        person - "fixing_code, attempt 2 of 3" is the difference between a
        system that looks stuck and one that looks like it is working.
        """
        queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

        def emit(stage: str, detail: dict) -> None:
            queue.put_nowait((stage, detail))

        async def drive() -> TaskResult:
            try:
                return await self.run(
                    data, filename, request,
                    requested_format=requested_format, on_stage=emit,
                )
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(drive())
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
        yield "result", {"result": await task}
