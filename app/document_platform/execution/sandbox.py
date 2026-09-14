"""Run generated Python against a real file, isolated from everything else.

The container is the security boundary and the dependency boundary at once:
``--network none`` means generated code cannot reach the internet, the
database, or the model endpoint; the mounted directory is the only filesystem
it can see, and it holds exactly one input file. Memory, CPU and wall clock are
capped so a runaway loop ends by itself.

The image is the one the workers already run, which is why nothing new has to
be built or installed: pandas, openpyxl, python-docx, pypdf and numpy are
already in it.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

WORK_DIR = "/work"
"""Where the mounted directory appears inside the container."""

SCRIPT_NAME = "task.py"
STDOUT_LIMIT = 20_000
"""Generated code sometimes prints a whole dataframe. Only the head of that is
useful to a person or to the repair prompt, and the tail is what blows up a
prompt's token budget."""


class SandboxUnavailableError(RuntimeError):
    """Docker is not usable, so no generated code can be run at all."""


@dataclass
class SandboxResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    output_bytes: bytes | None = None
    output_name: str = ""
    timed_out: bool = False
    files_written: list[str] = field(default_factory=list)

    @property
    def failure_text(self) -> str:
        """What to show the model when asking it to fix its own code.

        stderr carries the traceback, which is the part that identifies the
        mistake; stdout is included because generated code often prints the
        column list right before failing on one of them.
        """
        if self.timed_out:
            return "The script did not finish in time. It was killed."
        parts = []
        if self.stderr.strip():
            parts.append(self.stderr.strip()[-4000:])
        if self.stdout.strip():
            parts.append("stdout before the failure:\n" + self.stdout.strip()[-1000:])
        return "\n\n".join(parts) or f"The script exited with code {self.exit_code}."


def docker_available(binary: str = "docker") -> bool:
    try:
        proc = subprocess.run(
            [binary, "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=15,
        )
        return proc.returncode == 0
    except Exception:  # noqa: BLE001 - any failure here means "cannot run code"
        return False


def run_python(
    code: str,
    input_bytes: bytes,
    input_name: str,
    output_name: str,
    *,
    image: str,
    timeout_seconds: int = 120,
    memory: str = "2g",
    cpus: str = "2",
    docker_binary: str = "docker",
) -> SandboxResult:
    """Execute ``code`` with one input file mounted, and collect what it wrote.

    The generated script addresses its files through ``INPUT_PATH`` and
    ``OUTPUT_PATH`` inside the container, so it never sees a host path and the
    same code runs identically wherever the service is deployed.
    """
    workdir = Path(tempfile.mkdtemp(prefix=f"doctask-{uuid.uuid4().hex[:8]}-"))
    try:
        (workdir / input_name).write_bytes(input_bytes)
        (workdir / SCRIPT_NAME).write_text(code, encoding="utf-8")

        args = [
            docker_binary, "run", "--rm",
            "--network", "none",              # no internet, no database, no model
            "--memory", memory,
            "--cpus", cpus,
            "--pids-limit", "256",            # a fork bomb ends as an error
            "-v", f"{workdir}:{WORK_DIR}",
            "-w", WORK_DIR,
            image,
            "python", f"{WORK_DIR}/{SCRIPT_NAME}",
        ]

        started = time.perf_counter()
        timed_out = False
        try:
            proc = subprocess.run(
                args, capture_output=True, text=True,
                timeout=timeout_seconds, encoding="utf-8", errors="replace",
            )
            exit_code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(
                exc.stdout, bytes) else (exc.stdout or "")
            stderr = f"Killed after {timeout_seconds}s."
        except FileNotFoundError as exc:
            raise SandboxUnavailableError(
                f"'{docker_binary}' is not on PATH, so generated code cannot be run"
            ) from exc
        duration_ms = int((time.perf_counter() - started) * 1000)

        produced = workdir / output_name
        output_bytes = produced.read_bytes() if produced.is_file() else None
        written = sorted(
            p.name for p in workdir.iterdir()
            if p.is_file() and p.name not in (SCRIPT_NAME, input_name)
        )

        # A script that writes nothing is fine - a question is answered on
        # stdout - but a non-zero exit is always a failure worth repairing.
        ok = exit_code == 0 and not timed_out
        if not ok:
            logger.info(
                f"Sandbox run failed (exit={exit_code}, timeout={timed_out}): "
                f"{stderr.strip()[:300]}"
            )
        return SandboxResult(
            ok=ok,
            exit_code=exit_code,
            stdout=stdout[:STDOUT_LIMIT],
            stderr=stderr[:STDOUT_LIMIT],
            duration_ms=duration_ms,
            output_bytes=output_bytes,
            output_name=output_name if output_bytes else "",
            timed_out=timed_out,
            files_written=written,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
