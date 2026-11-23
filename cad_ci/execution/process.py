"""Owned boundary for external process execution.

Owner modules describe commands and consume the small result type below.
Only this adapter talks to :mod:`subprocess`, which keeps process mechanics
replaceable in unit/conformance tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Protocol, Sequence


@dataclass(frozen=True)
class ProcessResult:
    """Minimal process result exposed to owner logic."""

    returncode: int


class ProcessExecutionError(RuntimeError):
    """Raised when an external process cannot satisfy a checked invocation."""


class ProcessRunner(Protocol):
    """Interface used by owner logic for external process execution."""

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = False,
    ) -> ProcessResult:
        """Run one command and return the owned result shape."""


class SubprocessRunner:
    """Production adapter backed by :func:`subprocess.run`."""

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = False,
    ) -> ProcessResult:
        """Run one external command, translating process-library failures."""

        argv = [str(part) for part in command]
        try:
            completed = subprocess.run(argv, cwd=cwd, check=check)
        except (OSError, subprocess.CalledProcessError) as exc:
            rendered = " ".join(argv)
            raise ProcessExecutionError(
                f"external process failed: {rendered}: {exc}"
            ) from exc
        return ProcessResult(returncode=int(completed.returncode))


DEFAULT_PROCESS_RUNNER: ProcessRunner = SubprocessRunner()
