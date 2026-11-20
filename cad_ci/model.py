"""Small immutable data objects shared by the config, planner and runner."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Step:
    """One command in an item's ordered CI flow.

    `run` is either an argv tuple or a shell command. `outputs` lists files
    that must exist below the item's build directory after the step succeeds.
    `timeout_seconds` is the effective repository default or step override.
    `inputs` is an optional repository-relative pattern set; None means inherit
    the owning item's `watch` patterns.
    """

    id: str
    run: str | tuple[str, ...]
    outputs: tuple[str, ...] = ()
    timeout_seconds: int | None = None
    inputs: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Item:
    """One consumer-owned folder that can be planned and run independently.

    The tool treats `kind` as descriptive metadata only. Behaviour comes from
    the item's own config, processing state, dependencies, watch paths and ordered steps.
    `variables` is the validated, sorted repository-wide environment mapping
    that applies to every command.
    """

    id: str
    path: Path
    kind: str
    needs: tuple[str, ...]
    watch: tuple[str, ...]
    affected: str
    reuse: bool
    steps: tuple[Step, ...]
    config_path: Path
    config_data: dict[str, Any]
    process: bool = True
    variables: tuple[tuple[str, str], ...] = ()
