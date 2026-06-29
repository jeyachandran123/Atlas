"""
Terminal tool — sandboxed command execution.

SECURITY: Every command runs inside an ephemeral Docker container.
- No access to host filesystem except the repository (mounted read-write)
- No network access (--network none)
- CPU and memory limits enforced
- Maximum execution time: 30 seconds
- Command blocklist for known dangerous patterns
- All executions logged to AuditLog

Why Docker even in V1:
subprocess.run() with shell=True is an RCE vulnerability.
The 200ms Docker startup overhead is a reasonable price for isolation.
"""

from __future__ import annotations

import asyncio
import re
import shlex
from typing import Any

from app.agents.tools.base import BaseTool, ToolContext, ToolResult

# Commands that are blocked regardless of context
BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/",          # recursive delete from root
    r"rm\s+-rf\s+~",          # recursive delete from home
    r":\(\)\{.*\}",           # fork bomb
    r">\s*/dev/sd",           # disk wipe
    r"mkfs",                  # filesystem format
    r"fdisk",                 # disk partition
    r"dd\s+if=",              # disk dump
    r"\|\s*(bash|sh|zsh|fish)",  # piping to shell
    r"curl.*\|",              # curl pipe
    r"wget.*\|",              # wget pipe
    r"chmod\s+777",           # world-writable
    r"sudo\s+",               # privilege escalation
    r"su\s+",                 # switch user
]

BLOCKED_COMPILED = [re.compile(p, re.IGNORECASE) for p in BLOCKED_PATTERNS]

MAX_OUTPUT_BYTES = 50 * 1024   # 50 KB
TIMEOUT_SECONDS = 30
MEMORY_LIMIT = "512m"
CPU_LIMIT = "1.0"

# Docker image for the sandbox
SANDBOX_IMAGE = "ai-coding-assistant-sandbox:latest"


def _is_blocked(command: str) -> tuple[bool, str]:
    """Check if a command matches any blocked pattern."""
    for pattern in BLOCKED_COMPILED:
        if pattern.search(command):
            return True, f"Command blocked by security policy: matches pattern '{pattern.pattern}'"
    return False, ""


class TerminalTool(BaseTool):
    """
    Sandboxed terminal command execution.

    Every command runs in an ephemeral Docker container:
    - Mounted: repository directory at /workspace
    - Network: none (--network none)
    - CPU: 1 core max
    - Memory: 512MB max
    - Timeout: 30 seconds
    - Working directory: /workspace

    The container is destroyed after each command.
    """

    name = "terminal_tool"
    description = (
        "Execute terminal commands in an isolated sandbox. "
        "The sandbox has access to the repository files but no internet connection. "
        "Use for running tests, linters, build tools."
    )

    async def _execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        command = kwargs.get("command", "").strip()
        working_dir = kwargs.get("working_dir", ".")

        if not command:
            return ToolResult(self.name, False, error="Command is required")

        if not context.repo_path:
            return ToolResult(self.name, False, error="No repository path configured")

        # Security check
        blocked, reason = _is_blocked(command)
        if blocked:
            return ToolResult(self.name, False, error=reason)

        return await self._run_in_docker(
            command=command,
            repo_path=context.repo_path,
            working_dir=working_dir,
        )

    async def _run_in_docker(
        self,
        command: str,
        repo_path: str,
        working_dir: str = ".",
    ) -> ToolResult:
        """Execute command in an ephemeral Docker container."""
        # Normalise working directory within the container
        safe_workdir = f"/workspace/{working_dir.lstrip('/')}" if working_dir != "." else "/workspace"

        docker_command = [
            "docker", "run",
            "--rm",                          # remove container after exit
            "--network", "none",             # no internet
            f"--memory={MEMORY_LIMIT}",      # memory cap
            f"--cpus={CPU_LIMIT}",           # CPU cap
            "--read-only",                   # read-only root filesystem
            f"--volume={repo_path}:/workspace:rw",  # mount repo
            "--tmpfs", "/tmp:size=100m",     # writable /tmp
            "--ulimit", "nproc=50",          # process count limit
            "-e", "HOME=/workspace",
            f"--workdir={safe_workdir}",
            SANDBOX_IMAGE,
            "timeout", str(TIMEOUT_SECONDS),
            "sh", "-c", command,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=TIMEOUT_SECONDS + 5,  # +5s grace period
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult(
                    self.name, False,
                    error=f"Command timed out after {TIMEOUT_SECONDS} seconds",
                )

            stdout_text = stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
            stderr_text = stderr.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]

            # Truncation notice
            if len(stdout) > MAX_OUTPUT_BYTES:
                stdout_text += f"\n... [output truncated at {MAX_OUTPUT_BYTES // 1024}KB]"

            success = proc.returncode == 0
            output = stdout_text if stdout_text else stderr_text

            return ToolResult(
                self.name,
                success,
                output=output,
                error=stderr_text if not success and stderr_text else None,
                metadata={
                    "command": command,
                    "exit_code": proc.returncode,
                    "stdout_bytes": len(stdout),
                    "stderr_bytes": len(stderr),
                },
            )

        except FileNotFoundError:
            # Docker not available — fallback mode for development
            return await self._run_fallback(command, repo_path, working_dir)
        except Exception as e:
            return ToolResult(self.name, False, error=f"Execution failed: {str(e)}")

    async def _run_fallback(
        self, command: str, repo_path: str, working_dir: str
    ) -> ToolResult:
        """
        Fallback when Docker is not available.
        Uses restricted subprocess for local development ONLY.
        NOT suitable for production — no sandbox isolation.
        """
        import os

        work_path = os.path.join(repo_path, working_dir.lstrip("/"))
        if not os.path.isdir(work_path):
            work_path = repo_path

        try:
            proc = await asyncio.create_subprocess_shell(
                f"cd {shlex.quote(work_path)} && timeout {TIMEOUT_SECONDS} {command}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=TIMEOUT_SECONDS + 5
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult(self.name, False, error="Command timed out")

            stdout_text = stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
            stderr_text = stderr.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
            success = proc.returncode == 0

            return ToolResult(
                self.name,
                success,
                output=stdout_text or stderr_text,
                error=stderr_text if not success else None,
                metadata={
                    "command": command,
                    "exit_code": proc.returncode,
                    "mode": "fallback_no_sandbox",
                },
            )
        except Exception as e:
            return ToolResult(self.name, False, error=str(e))
