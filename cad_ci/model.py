"""Small immutable data objects shared by the config, planner and runner."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DependencyCopy:
    """One engine-owned copy from a direct dependency bundle."""

    dependency: str
    source: str


@dataclass(frozen=True)
class Step:
    """One action in an item's ordered CI flow.

    Exactly one of `run` or `copy` is configured. A command `run` is either
    an argv tuple or a shell command. A `copy` action projects declared output
    from one direct dependency bundle without launching a consumer subprocess.

    `outputs` lists files/directories owned below the item's build directory.
    `timeout_seconds` applies only to command steps. `inputs` is an optional
    repository-relative pattern set for command steps; None means inherit the
    owning item's `watch` patterns. `selection_context` optionally exposes
    already-computed active-graph context to command steps.
    """

    id: str
    run: str | tuple[str, ...] | None = None
    copy: DependencyCopy | None = None
    outputs: tuple[str, ...] = ()
    timeout_seconds: int | None = None
    inputs: tuple[str, ...] | None = None
    selection_context: str = "none"


@dataclass(frozen=True)
class PagesPublication:
    """One configured Pages source: normal item output or publication builder."""

    output: str
    item: str | None = None
    builder: str | None = None
    builder_path: Path | None = None
    builder_step: Step | None = None


@dataclass(frozen=True)
class RepositoryConfig:
    """Validated repository-wide configuration plus discovered items."""

    items: dict[str, "Item"]
    pages: PagesPublication | None = None
    variables: tuple[tuple[str, str], ...] = ()
    runtimes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Item:
    """One consumer-owned folder that can be planned and run independently.

    The tool treats `kind` as descriptive metadata only. Behaviour comes from
    the item's processing state, dependencies, watch paths and resolved builder
    steps. Legacy items may still own steps directly during migration.
    `variables` is the validated, sorted repository-wide environment mapping
    that applies to command actions. `builder` and `builder_path` identify a
    repository-owned shared builder when the item uses the declarative builder
    configuration path.
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
    builder: str | None = None
    builder_path: Path | None = None
    runtime_role: str | None = None
    runtime_image: str | None = None
    internal: bool = False
