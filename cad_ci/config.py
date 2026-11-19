"""Read and validate CI configuration owned by a consumer repository.

The root cad-ci.yml owns repository-wide defaults and item discovery. Each
item folder owns ci.yml with Git-selection paths, dependencies and ordered
steps. Step inputs are build dependencies; item watch paths are only coarse
Git-selection inputs.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
from typing import Any

import yaml

from .model import Item, Step


class ConfigError(ValueError):
    """Raised when a consumer CI file is missing, unsafe or inconsistent."""


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_RESERVED_ENV_PREFIXES = ("GITHUB_", "RUNNER_", "ACTIONS_", "CAD_CI_")
_GENERATED_ROOTS = {".git", ".cache", "build"}


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load one YAML mapping and report the file name in configuration errors."""

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"missing config: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config must be a mapping: {path}")
    return data


def _strings(value: object, field: str, path: Path) -> tuple[str, ...]:
    """Read a YAML list of strings as an immutable tuple."""

    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ConfigError(f"{field} must be a list of strings: {path}")
    return tuple(value)


def _variables(value: object, path: Path) -> tuple[tuple[str, str], ...]:
    """Read validated repository-wide command environment variables."""

    if value is None:
        return ()
    if not isinstance(value, dict):
        raise ConfigError(f"variables must be a mapping: {path}")

    result: list[tuple[str, str]] = []
    for name, variable_value in value.items():
        if not isinstance(name, str) or not _ENV_NAME.fullmatch(name):
            raise ConfigError(
                "variable name must use uppercase letters, numbers or "
                f"underscore: {path}: {name!r}"
            )
        if name.startswith(_RESERVED_ENV_PREFIXES):
            raise ConfigError(f"reserved variable name: {path}: {name}")
        if not isinstance(variable_value, str):
            raise ConfigError(
                f"variable value for {name} must be a string: {path}"
            )
        result.append((name, variable_value))

    return tuple(sorted(result))


def _repo_patterns(
    value: object,
    field: str,
    path: Path,
    *,
    optional: bool = False,
) -> tuple[str, ...] | None:
    """Read safe repository-relative patterns used by watch/step inputs."""

    if value is None and optional:
        return None
    patterns = _strings(value, field, path)
    normalized: list[str] = []
    for raw in patterns:
        pattern = raw.replace("\\", "/")
        parsed = PurePosixPath(pattern)
        if (
            not pattern
            or parsed.is_absolute()
            or ".." in parsed.parts
            or (parsed.parts and parsed.parts[0] in _GENERATED_ROOTS)
        ):
            raise ConfigError(
                f"{field} must stay inside source paths: {path}: {raw}"
            )
        normalized.append(pattern)
    return tuple(normalized)


def _timeout_seconds(
    value: object,
    field: str,
    path: Path,
    *,
    default: int | None = None,
) -> int | None:
    """Read one optional positive timeout in seconds."""

    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{field} must be a positive integer: {path}")
    return value


def _output_path(raw: str, path: Path, step_id: str) -> str:
    """Normalize and validate one step-owned output path."""

    value = raw.replace("\\", "/").strip("/")
    parsed = PurePosixPath(value)
    if not value or parsed.is_absolute() or ".." in parsed.parts:
        raise ConfigError(
            f"output must stay inside the item build directory: {path}:{step_id}"
        )
    if parsed.parts and parsed.parts[0] == ".cad-ci":
        raise ConfigError(
            f"output uses reserved .cad-ci namespace: {path}:{step_id}"
        )
    return parsed.as_posix()


def _step(data: object, path: Path, default_timeout: int | None) -> Step:
    """Validate one step and convert it to the shared Step object."""

    if not isinstance(data, dict):
        raise ConfigError(f"step must be a mapping: {path}")

    step_id = data.get("id")
    run = data.get("run")
    if not isinstance(step_id, str) or not _ID.fullmatch(step_id):
        raise ConfigError(
            "step id must use letters, numbers, dot, dash or underscore: "
            f"{path}"
        )

    # A list executes directly. A string deliberately requests shell syntax.
    if isinstance(run, list):
        if not run or not all(isinstance(x, str) for x in run):
            raise ConfigError(
                f"step run list must contain strings: {path}:{step_id}"
            )
        command: str | tuple[str, ...] = tuple(run)
    elif isinstance(run, str) and run:
        command = run
    else:
        raise ConfigError(f"step run is required: {path}:{step_id}")

    outputs = tuple(
        _output_path(output, path, step_id)
        for output in _strings(data.get("outputs"), "outputs", path)
    )
    inputs = _repo_patterns(
        data.get("inputs"),
        "inputs",
        path,
        optional="inputs" not in data,
    )
    timeout_seconds = _timeout_seconds(
        data.get("timeout_seconds"),
        "timeout_seconds",
        path,
        default=default_timeout,
    )
    return Step(
        id=step_id,
        run=command,
        outputs=outputs,
        timeout_seconds=timeout_seconds,
        inputs=inputs,
    )


def _check_output_ownership(steps: tuple[Step, ...], path: Path) -> None:
    """Reject duplicate or parent/child output ownership between steps."""

    owned: list[tuple[str, PurePosixPath]] = []
    for step in steps:
        for output in step.outputs:
            current = PurePosixPath(output)
            for owner, existing in owned:
                left = existing.parts
                right = current.parts
                common = min(len(left), len(right))
                if left[:common] == right[:common]:
                    raise ConfigError(
                        "step outputs overlap: "
                        f"{path}: {owner}:{existing.as_posix()} and "
                        f"{step.id}:{current.as_posix()}"
                    )
            owned.append((step.id, current))


def load_repository(repo: Path) -> dict[str, Item]:
    """Discover and validate every configured CI item in repo."""

    repo = repo.resolve()
    root_path = repo / "cad-ci.yml"
    root = _load_yaml(root_path)
    if root.get("schema") != 1:
        raise ConfigError(f"unsupported schema in {root_path}")

    variables = _variables(root.get("variables"), root_path)

    defaults = root.get("defaults", {})
    if defaults is None:
        defaults = {}
    if not isinstance(defaults, dict):
        raise ConfigError(f"defaults must be a mapping: {root_path}")
    default_timeout = _timeout_seconds(
        defaults.get("timeout_seconds"),
        "defaults.timeout_seconds",
        root_path,
    )

    item_patterns = _strings(root.get("items"), "items", root_path)
    if not item_patterns:
        raise ConfigError(f"no items configured in {root_path}")

    item_paths: list[Path] = []
    seen_paths: set[Path] = set()
    for pattern in item_patterns:
        rel_pattern = Path(pattern)
        if rel_pattern.is_absolute() or ".." in rel_pattern.parts:
            raise ConfigError(
                f"item path must stay inside the repository: {pattern}"
            )

        has_glob = any(char in pattern for char in "*?[")
        matches = sorted(repo.glob(pattern)) if has_glob else [repo / rel_pattern]
        matches = [
            candidate
            for candidate in matches
            if candidate.is_dir() and (candidate / "ci.yml").is_file()
        ]
        if not matches:
            raise ConfigError(f"item pattern matches no CI folders: {pattern}")

        for candidate in matches:
            rel = candidate.relative_to(repo)
            if rel not in seen_paths:
                seen_paths.add(rel)
                item_paths.append(rel)

    items: dict[str, Item] = {}
    for rel in item_paths:
        item_dir = repo / rel
        config_path = item_dir / "ci.yml"
        data = _load_yaml(config_path)

        item_id = data.get("id", rel.as_posix())
        if not isinstance(item_id, str) or not _ID.fullmatch(item_id):
            raise ConfigError(
                "item id must use letters, numbers, dot, dash or underscore: "
                f"{config_path}"
            )
        if item_id in items:
            raise ConfigError(f"duplicate item id: {item_id}")

        # kind is descriptive metadata only.
        kind = data.get("kind", "item")
        if not isinstance(kind, str) or not kind:
            raise ConfigError(f"kind must be a string: {config_path}")

        strategy = data.get("strategy", {})
        if strategy is None:
            strategy = {}
        if not isinstance(strategy, dict):
            raise ConfigError(f"strategy must be a mapping: {config_path}")

        affected = strategy.get("affected", "changed")
        if affected not in ("changed", "direct", "always"):
            raise ConfigError(
                "strategy.affected must be changed, direct or always: "
                f"{config_path}"
            )

        reuse = strategy.get("reuse", True)
        if not isinstance(reuse, bool):
            raise ConfigError(
                f"strategy.reuse must be true or false: {config_path}"
            )

        # Watch paths select top-level items from a Git diff. They are not the
        # fine-grained SCons dependency model; steps may declare inputs.
        watch_value = data.get("watch")
        watch = _repo_patterns(watch_value, "watch", config_path)
        if not watch:
            watch = (f"{rel.as_posix()}/**",)

        raw_steps = data.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ConfigError(
                f"steps must be a non-empty list: {config_path}"
            )
        steps = tuple(
            _step(value, config_path, default_timeout)
            for value in raw_steps
        )
        step_ids = [step.id for step in steps]
        if len(step_ids) != len(set(step_ids)):
            raise ConfigError(f"duplicate step id in {config_path}")
        _check_output_ownership(steps, config_path)

        items[item_id] = Item(
            id=item_id,
            path=rel,
            kind=kind,
            needs=_strings(data.get("needs"), "needs", config_path),
            watch=watch,
            affected=affected,
            reuse=reuse,
            variables=variables,
            steps=steps,
            config_path=config_path,
            config_data=data,
        )

    for item in items.values():
        unknown = sorted(set(item.needs) - set(items))
        if unknown:
            raise ConfigError(
                f"{item.id} needs unknown item(s): {', '.join(unknown)}"
            )

    _check_cycles(items)
    return items


def _check_cycles(items: dict[str, Item]) -> None:
    """Reject dependency loops because no valid execution order exists."""

    visiting: set[str] = set()
    done: set[str] = set()

    def visit(item_id: str) -> None:
        if item_id in done:
            return
        if item_id in visiting:
            raise ConfigError(f"dependency cycle includes {item_id}")
        visiting.add(item_id)
        for dependency in items[item_id].needs:
            visit(dependency)
        visiting.remove(item_id)
        done.add(item_id)

    for item_id in items:
        visit(item_id)
