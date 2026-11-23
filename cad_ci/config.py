"""Read and validate CI configuration owned by a consumer repository.

The root cad-ci.yml owns repository-wide defaults, item discovery and optional
repository-owned builder aliases. Each item folder owns ci.yml with identity,
Git-selection paths, dependencies and either a declarative builder reference or
legacy inline steps. Builder directories own executable step implementation.
Step inputs are build dependencies; item watch paths are only coarse
Git-selection inputs.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path, PurePosixPath
import re
from typing import Any

import yaml

from .builders.catalog import (
    BUILTIN_BUILDERS,
    projection_steps,
    runtime_batch_id,
    runtime_batch_path,
    runtime_batch_step,
)
from .model import (
    DependencyCopy,
    Item,
    PagesPublication,
    RepositoryConfig,
    Step,
    VerificationConfig,
    VerificationPackage,
)
from .verification.catalog import VERIFICATION_ADAPTERS
from .verification.package import (
    PACKAGE_ITEM_ID,
    PACKAGE_ITEM_PATH,
    package_step,
)


class ConfigError(ValueError):
    """Raised when a consumer CI file is missing, unsafe or inconsistent."""


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_RESERVED_ENV_PREFIXES = ("GITHUB_", "RUNNER_", "ACTIONS_", "CAD_CI_")
_GENERATED_ROOTS = {".git", ".cache", "build"}
_SHA256_IMAGE = re.compile(r"^.+@sha256:[0-9a-fA-F]{64}$")
_GITHUB_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_VERIFICATION_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


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


def _merge_mapping(
    base: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    """Recursively merge configuration mappings with later values winning."""

    merged = deepcopy(base)
    for key, value in override.items():
        previous = merged.get(key)
        if isinstance(previous, dict) and isinstance(value, dict):
            merged[key] = _merge_mapping(previous, value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _templates(value: object, path: Path) -> dict[str, dict[str, Any]]:
    """Read repository-owned named item templates."""

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"templates must be a mapping: {path}")

    forbidden = {"id", "template", "templates"}
    result: dict[str, dict[str, Any]] = {}
    for name, template in value.items():
        if not isinstance(name, str) or not _ID.fullmatch(name):
            raise ConfigError(f"invalid template name: {path}: {name!r}")
        if not isinstance(template, dict):
            raise ConfigError(f"template must be a mapping: {path}: {name}")
        invalid = sorted(forbidden.intersection(template))
        if invalid:
            raise ConfigError(
                f"template {name} contains unsupported field(s): "
                + ", ".join(invalid)
            )
        result[name] = deepcopy(template)
    return result


def _builders(value: object, path: Path) -> dict[str, Path]:
    """Read repository-owned builder aliases as safe repository paths."""

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"builders must be a mapping: {path}")

    result: dict[str, Path] = {}
    for name, raw_path in value.items():
        if not isinstance(name, str) or not _ID.fullmatch(name):
            raise ConfigError(f"invalid builder name: {path}: {name!r}")
        if name in BUILTIN_BUILDERS:
            raise ConfigError(
                f"builder name is reserved by built-in catalog: {path}: {name}"
            )
        if not isinstance(raw_path, str) or not raw_path:
            raise ConfigError(f"builder path must be a string: {path}: {name}")

        normalized = raw_path.replace("\\", "/").strip("/")
        parsed = PurePosixPath(normalized)
        if (
            not normalized
            or parsed.is_absolute()
            or ".." in parsed.parts
            or (parsed.parts and parsed.parts[0] in _GENERATED_ROOTS)
        ):
            raise ConfigError(
                f"builder path must stay inside source paths: {path}: {raw_path}"
            )
        result[name] = Path(parsed.as_posix())
    return result


def _runtime_image(value: object, path: Path, role: str) -> str:
    """Validate one explicit non-latest runtime image reference."""

    if not isinstance(value, str) or not value or any(ch.isspace() for ch in value):
        raise ConfigError(f"runtime image must be a non-empty string: {path}: {role}")
    if "@" in value:
        if not _SHA256_IMAGE.fullmatch(value):
            raise ConfigError(
                f"runtime image digest must use sha256: {path}: {role}: {value}"
            )
        return value

    leaf = value.rsplit("/", 1)[-1]
    if ":" not in leaf:
        raise ConfigError(
            f"runtime image must use an explicit non-latest tag or digest: "
            f"{path}: {role}: {value}"
        )
    tag = leaf.rsplit(":", 1)[1]
    if not tag or tag.lower() == "latest":
        raise ConfigError(
            f"runtime image must use an explicit non-latest tag or digest: "
            f"{path}: {role}: {value}"
        )
    return value


def _runtimes(value: object, path: Path) -> dict[str, str]:
    """Read generic runtime-role mappings used by built-in builders."""

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"runtimes must be a mapping: {path}")

    result: dict[str, str] = {}
    for role, image in value.items():
        if not isinstance(role, str) or not _ID.fullmatch(role):
            raise ConfigError(f"invalid runtime role: {path}: {role!r}")
        result[role] = _runtime_image(image, path, role)
    return result


def _verification_package(
    value: object,
    path: Path,
) -> VerificationPackage | None:
    """Read the exact released verification-library source pin."""

    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConfigError(f"verification must be a mapping: {path}")
    invalid = sorted(set(value) - {"package"})
    if invalid:
        raise ConfigError(
            "verification contains unsupported field(s): "
            + ", ".join(invalid)
        )

    package = value.get("package")
    if not isinstance(package, dict):
        raise ConfigError(f"verification.package must be a mapping: {path}")
    invalid_package = sorted(
        set(package) - {"repository", "version", "commit"}
    )
    if invalid_package:
        raise ConfigError(
            "verification.package contains unsupported field(s): "
            + ", ".join(invalid_package)
        )

    repository = package.get("repository")
    version = package.get("version")
    commit = package.get("commit")
    if (
        not isinstance(repository, str)
        or not _GITHUB_REPOSITORY.fullmatch(repository)
    ):
        raise ConfigError(
            f"verification.package.repository must be owner/name: {path}"
        )
    if not isinstance(version, str) or not _SEMVER.fullmatch(version):
        raise ConfigError(
            f"verification.package.version must be SemVer X.Y.Z: {path}"
        )
    if not isinstance(commit, str) or not _COMMIT_SHA.fullmatch(commit):
        raise ConfigError(
            f"verification.package.commit must be a 40-character lowercase SHA: {path}"
        )
    return VerificationPackage(
        repository=repository,
        version=version,
        commit=commit,
    )


def _item_verification(
    value: object,
    path: Path,
    *,
    repo: Path,
    item_root: Path,
    item_id: str,
) -> VerificationConfig | None:
    """Normalize one item/template verification request."""

    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConfigError(f"item verification must be a mapping: {path}")
    invalid = sorted(set(value) - {"adapter", "definition", "id"})
    if invalid:
        raise ConfigError(
            "item verification contains unsupported field(s): "
            + ", ".join(invalid)
        )

    adapter = value.get("adapter")
    if not isinstance(adapter, str) or adapter not in VERIFICATION_ADAPTERS:
        raise ConfigError(
            f"verification.adapter must name a built-in adapter: {path}"
        )

    raw_definition = value.get("definition")
    if not isinstance(raw_definition, str) or not raw_definition:
        raise ConfigError(
            f"verification.definition must be a non-empty string: {path}"
        )
    normalized = raw_definition.replace("\\", "/")
    parsed = PurePosixPath(normalized)
    if parsed.is_absolute() or any(char in normalized for char in "*?["):
        raise ConfigError(
            f"verification.definition must be one item-relative file: {path}"
        )
    definition = _item_source_pattern(
        item_root,
        parsed,
        "verification.definition",
        path,
        raw_definition,
    )
    definition_path = repo / Path(definition)
    if not definition_path.is_file() or definition_path.is_symlink():
        raise ConfigError(
            f"verification.definition must be a regular source file: {path}: {definition}"
        )

    verification_id = value.get("id", item_id)
    if (
        not isinstance(verification_id, str)
        or not _VERIFICATION_ID.fullmatch(verification_id)
    ):
        raise ConfigError(
            "verification.id must use lowercase letters, numbers, dash or "
            f"underscore: {path}"
        )

    return VerificationConfig(
        adapter=adapter,
        definition=definition,
        verification_id=verification_id,
    )


def _publication_pages(value: object, path: Path) -> PagesPublication | None:
    """Read optional item-output or post-build Pages publication configuration."""

    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConfigError(f"publication must be a mapping: {path}")

    invalid = sorted(set(value) - {"pages"})
    if invalid:
        raise ConfigError(
            "publication contains unsupported field(s): "
            + ", ".join(invalid)
        )

    pages = value.get("pages")
    if pages is None:
        return None
    if not isinstance(pages, dict):
        raise ConfigError(f"publication.pages must be a mapping: {path}")

    invalid_pages = sorted(set(pages) - {"item", "builder", "output"})
    if invalid_pages:
        raise ConfigError(
            "publication.pages contains unsupported field(s): "
            + ", ".join(invalid_pages)
        )

    item = pages.get("item")
    builder = pages.get("builder")
    if (item is None) == (builder is None):
        raise ConfigError(
            f"publication.pages requires exactly one of item or builder: {path}"
        )
    if item is not None and (
        not isinstance(item, str) or not _ID.fullmatch(item)
    ):
        raise ConfigError(
            f"publication.pages.item must be a valid item id: {path}"
        )
    if builder is not None and (
        not isinstance(builder, str) or not _ID.fullmatch(builder)
    ):
        raise ConfigError(
            f"publication.pages.builder must be a valid builder name: {path}"
        )

    output = pages.get("output")
    if not isinstance(output, str) or not output:
        raise ConfigError(
            f"publication.pages.output must be a non-empty string: {path}"
        )
    normalized = output.replace("\\", "/").strip("/")
    parsed = PurePosixPath(normalized)
    if (
        not normalized
        or parsed.is_absolute()
        or ".." in parsed.parts
        or (parsed.parts and parsed.parts[0] == ".cad-ci")
    ):
        raise ConfigError(
            f"publication.pages.output must be a safe item output: {path}"
        )

    return PagesPublication(
        item=item,
        builder=builder,
        output=parsed.as_posix(),
    )


def _effective_item_config(
    raw: dict[str, Any],
    templates: dict[str, dict[str, Any]],
    path: Path,
) -> dict[str, Any]:
    """Apply one optional root template to an item-local mapping."""

    if "templates" in raw:
        raise ConfigError(
            f"templates are only allowed in root cad-ci.yml: {path}"
        )

    template_name = raw.get("template")
    if template_name is None:
        return deepcopy(raw)
    if not isinstance(template_name, str) or not _ID.fullmatch(template_name):
        raise ConfigError(f"template must be a valid name: {path}")
    try:
        template = templates[template_name]
    except KeyError as exc:
        raise ConfigError(
            f"unknown template {template_name!r}: {path}"
        ) from exc

    local = deepcopy(raw)
    local.pop("template", None)
    return _merge_mapping(template, local)


def _item_source_pattern(
    item_root: Path,
    parsed: PurePosixPath,
    field: str,
    path: Path,
    raw: str,
) -> str:
    """Normalize one item-relative pattern without escaping the repository."""

    parts = list(PurePosixPath(item_root.as_posix()).parts)
    for part in parsed.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise ConfigError(
                    f"{field} must stay inside source paths: {path}: {raw}"
                )
            parts.pop()
            continue
        parts.append(part)

    if not parts:
        raise ConfigError(
            f"{field} must stay inside source paths: {path}: {raw}"
        )

    pattern = PurePosixPath(*parts).as_posix()
    normalized = PurePosixPath(pattern)
    if normalized.parts and normalized.parts[0] in _GENERATED_ROOTS:
        raise ConfigError(
            f"{field} must stay inside source paths: {path}: {raw}"
        )
    return pattern


def _source_patterns(
    value: object,
    field: str,
    path: Path,
    *,
    item_root: Path,
    optional: bool = False,
) -> tuple[str, ...] | None:
    """Read legacy repo patterns or explicit item/repo scoped patterns."""

    if value is None and optional:
        return None

    scoped: list[tuple[str, str]] = []
    if isinstance(value, list):
        for raw in _strings(value, field, path):
            scoped.append(("repo", raw))
    elif isinstance(value, dict):
        invalid = sorted(set(value) - {"item", "repo"})
        if invalid:
            raise ConfigError(
                f"{field} contains unsupported scope(s): {path}: "
                + ", ".join(invalid)
            )
        for raw in _strings(value.get("item"), f"{field}.item", path):
            scoped.append(("item", raw))
        for raw in _strings(value.get("repo"), f"{field}.repo", path):
            scoped.append(("repo", raw))
    elif value is None:
        scoped = []
    else:
        raise ConfigError(
            f"{field} must be a list or item/repo mapping: {path}"
        )

    normalized: list[str] = []
    for scope, raw in scoped:
        pattern = raw.replace("\\", "/")
        parsed = PurePosixPath(pattern)
        if not pattern or parsed.is_absolute():
            raise ConfigError(
                f"{field} must stay inside source paths: {path}: {raw}"
            )

        if scope == "item":
            pattern = _item_source_pattern(
                item_root,
                parsed,
                field,
                path,
                raw,
            )
            parsed = PurePosixPath(pattern)
        elif ".." in parsed.parts:
            raise ConfigError(
                f"{field} must stay inside source paths: {path}: {raw}"
            )

        if parsed.parts and parsed.parts[0] in _GENERATED_ROOTS:
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


def _dependency_copy(
    value: object,
    path: Path,
    step_id: str,
    item_root: Path,
) -> DependencyCopy:
    """Validate one engine-owned dependency-output copy action."""

    if not isinstance(value, dict):
        raise ConfigError(f"step copy must be a mapping: {path}:{step_id}")
    invalid = sorted(set(value) - {"dependency", "source"})
    if invalid:
        raise ConfigError(
            f"step copy contains unsupported field(s): {path}:{step_id}: "
            + ", ".join(invalid)
        )

    dependency = value.get("dependency")
    source = value.get("source")
    if not isinstance(dependency, str) or not _ID.fullmatch(dependency):
        raise ConfigError(
            f"copy dependency must be a valid item id: {path}:{step_id}"
        )
    if not isinstance(source, str) or not source:
        raise ConfigError(f"copy source must be a string: {path}:{step_id}")

    rendered = source.replace("{item_path}", item_root.as_posix())
    if "{" in rendered or "}" in rendered:
        raise ConfigError(
            f"copy source contains unsupported substitution: {path}:{step_id}"
        )

    normalized = rendered.replace("\\", "/")
    parsed = PurePosixPath(normalized)
    if (
        parsed.is_absolute()
        or ".." in parsed.parts
        or ".cad-ci" in parsed.parts
    ):
        raise ConfigError(
            f"copy source must stay inside dependency output: {path}:{step_id}"
        )
    source_path = parsed.as_posix()
    if source_path in ("", "."):
        source_path = "."

    return DependencyCopy(dependency=dependency, source=source_path)


def _step(
    data: object,
    path: Path,
    default_timeout: int | None,
    item_root: Path,
) -> Step:
    """Validate one step and convert it to the shared Step object."""

    if not isinstance(data, dict):
        raise ConfigError(f"step must be a mapping: {path}")

    step_id = data.get("id")
    if not isinstance(step_id, str) or not _ID.fullmatch(step_id):
        raise ConfigError(
            "step id must use letters, numbers, dot, dash or underscore: "
            f"{path}"
        )

    has_run = "run" in data
    has_copy = "copy" in data
    if has_run == has_copy:
        raise ConfigError(
            f"step requires exactly one of run or copy: {path}:{step_id}"
        )

    outputs = tuple(
        _output_path(output, path, step_id)
        for output in _strings(data.get("outputs"), "outputs", path)
    )

    selection_context = data.get("selection_context", "none")
    if selection_context not in ("none", "direct_dependents"):
        raise ConfigError(
            "step selection_context must be none or direct_dependents: "
            f"{path}:{step_id}"
        )

    if has_copy:
        if not outputs:
            raise ConfigError(
                f"copy step requires at least one output: {path}:{step_id}"
            )
        if "inputs" in data:
            raise ConfigError(
                f"copy step does not accept inputs: {path}:{step_id}"
            )
        if "timeout_seconds" in data:
            raise ConfigError(
                f"copy step does not accept timeout_seconds: {path}:{step_id}"
            )
        if selection_context != "none":
            raise ConfigError(
                f"copy step does not accept selection_context: {path}:{step_id}"
            )
        return Step(
            id=step_id,
            copy=_dependency_copy(
                data.get("copy"),
                path,
                step_id,
                item_root,
            ),
            outputs=outputs,
            timeout_seconds=None,
            inputs=(),
        )

    run = data.get("run")
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

    inputs = _source_patterns(
        data.get("inputs"),
        "inputs",
        path,
        item_root=item_root,
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
        selection_context=selection_context,
    )


def _configured_steps(
    raw_steps: object,
    path: Path,
    default_timeout: int | None,
    item_root: Path,
    *,
    builder_watch: str | None = None,
) -> tuple[Step, ...]:
    """Parse one executable step list from an item or shared builder file."""

    if not isinstance(raw_steps, list) or not raw_steps:
        raise ConfigError(f"steps must be a non-empty list: {path}")

    parsed = tuple(
        _step(value, path, default_timeout, item_root)
        for value in raw_steps
    )
    if builder_watch is not None:
        parsed = tuple(
            replace(
                step,
                inputs=tuple(dict.fromkeys((*step.inputs, builder_watch))),
            )
            if step.run is not None and step.inputs is not None
            else step
            for step in parsed
        )

    step_ids = [step.id for step in parsed]
    if len(step_ids) != len(set(step_ids)):
        raise ConfigError(f"duplicate step id in {path}")
    _check_output_ownership(parsed, path)
    return parsed


def _builder_steps(
    repo: Path,
    builder_name: str,
    builder_path: Path,
    default_timeout: int | None,
    item_root: Path,
) -> tuple[tuple[Step, ...], Path]:
    """Load executable implementation from one repository-owned builder."""

    config_path = repo / builder_path / "builder.yml"
    data = _load_yaml(config_path)
    if data.get("schema") != 1:
        raise ConfigError(f"unsupported builder schema in {config_path}")

    invalid = sorted(set(data) - {"schema", "description", "steps"})
    if invalid:
        raise ConfigError(
            f"builder {builder_name} contains unsupported field(s): "
            + ", ".join(invalid)
        )

    builder_watch = f"{builder_path.as_posix()}/**"
    steps = _configured_steps(
        data.get("steps"),
        config_path,
        default_timeout,
        item_root,
        builder_watch=builder_watch,
    )
    return steps, config_path


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


def _check_nested_item_output_roots(items: dict[str, Item]) -> None:
    """Reject parent outputs that overlap a nested item's source root."""

    values = tuple(items.values())
    for parent in values:
        parent_parts = parent.path.parts
        for child in values:
            if parent is child:
                continue
            child_parts = child.path.parts
            if (
                len(parent_parts) >= len(child_parts)
                or child_parts[: len(parent_parts)] != parent_parts
            ):
                continue

            relative_child = PurePosixPath(
                *child_parts[len(parent_parts) :]
            )
            for step in parent.steps:
                for output in step.outputs:
                    output_path = PurePosixPath(output)
                    left = output_path.parts
                    right = relative_child.parts
                    common = min(len(left), len(right))
                    if left[:common] == right[:common]:
                        raise ConfigError(
                            "item output overlaps nested item root: "
                            f"{parent.id}:{output_path.as_posix()} and "
                            f"{child.id}:{child.path.as_posix()}"
                        )


def load_repository_config(repo: Path) -> RepositoryConfig:
    """Discover and validate repository-wide configuration and CI items."""

    repo = repo.resolve()
    root_path = repo / "cad-ci.yml"
    root = _load_yaml(root_path)
    if root.get("schema") != 1:
        raise ConfigError(f"unsupported schema in {root_path}")

    variables = _variables(root.get("variables"), root_path)
    runtimes = _runtimes(root.get("runtimes"), root_path)
    verification_package = _verification_package(
        root.get("verification"),
        root_path,
    )
    templates = _templates(root.get("templates"), root_path)
    builders = _builders(root.get("builders"), root_path)
    pages = _publication_pages(root.get("publication"), root_path)

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
    builtin_users: dict[str, list[tuple[str, Path]]] = {}
    for rel in item_paths:
        item_dir = repo / rel
        config_path = item_dir / "ci.yml"
        raw = _load_yaml(config_path)
        data = _effective_item_config(raw, templates, config_path)

        item_id = data.get("id", rel.as_posix().replace("/", "-"))
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

        process = data.get("process", True)
        if not isinstance(process, bool):
            raise ConfigError(f"process must be true or false: {config_path}")

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
        watch = _source_patterns(
            watch_value,
            "watch",
            config_path,
            item_root=rel,
        )
        if not watch:
            watch = (f"{rel.as_posix()}/**",)

        raw_steps = data.get("steps")
        builder_name = data.get("builder")
        has_builder = builder_name is not None
        has_steps = raw_steps is not None
        if has_builder == has_steps:
            raise ConfigError(
                f"item requires exactly one of builder or steps: {config_path}"
            )

        verification = _item_verification(
            data.get("verification"),
            config_path,
            repo=repo,
            item_root=rel,
            item_id=item_id,
        )
        if verification is not None and verification_package is None:
            raise ConfigError(
                f"item verification requires root verification.package: {config_path}"
            )

        builder_path: Path | None = None
        runtime_role: str | None = None
        runtime_image: str | None = None
        needs = _strings(data.get("needs"), "needs", config_path)
        if has_builder:
            if (
                not isinstance(builder_name, str)
                or not _ID.fullmatch(builder_name)
            ):
                raise ConfigError(f"builder must be a valid name: {config_path}")

            if builder_name in BUILTIN_BUILDERS:
                built_in = BUILTIN_BUILDERS[builder_name]
                model_source = item_dir / "model.py"
                if not model_source.is_file() or model_source.is_symlink():
                    raise ConfigError(
                        f"built-in {builder_name} requires regular item-local "
                        f"model.py: {config_path}"
                    )
                runtime_role = built_in.runtime_role
                try:
                    runtime_image = runtimes[runtime_role]
                except KeyError as exc:
                    raise ConfigError(
                        f"built-in {builder_name} requires runtime role "
                        f"{runtime_role!r}: {root_path}"
                    ) from exc

                if verification is not None:
                    adapter = VERIFICATION_ADAPTERS[verification.adapter]
                    if adapter.runtime_role != runtime_role:
                        raise ConfigError(
                            f"verification adapter {verification.adapter!r} requires "
                            f"runtime role {adapter.runtime_role!r}, not "
                            f"{runtime_role!r}: {config_path}"
                        )

                producer = runtime_batch_id(runtime_role)
                needs = tuple(dict.fromkeys((*needs, producer)))
                steps = projection_steps(
                    builder_name,
                    dependency=producer,
                    item_path=rel,
                    verification=verification is not None,
                )
                extra_watch = [f"{rel.as_posix()}/model.py"]
                if verification is not None:
                    extra_watch.append(verification.definition)
                watch = tuple(dict.fromkeys((*watch, *extra_watch)))
                builtin_users.setdefault(runtime_role, []).append((item_id, rel))
            else:
                if verification is not None:
                    raise ConfigError(
                        "verification currently requires a built-in CAD builder: "
                        f"{config_path}"
                    )
                try:
                    builder_path = builders[builder_name]
                except KeyError as exc:
                    raise ConfigError(
                        f"unknown builder {builder_name!r}: {config_path}"
                    ) from exc
                steps, _ = _builder_steps(
                    repo,
                    builder_name,
                    builder_path,
                    default_timeout,
                    rel,
                )
                builder_watch = f"{builder_path.as_posix()}/**"
                watch = tuple(dict.fromkeys((*watch, builder_watch)))
        else:
            if verification is not None:
                raise ConfigError(
                    "verification currently requires a built-in CAD builder: "
                    f"{config_path}"
                )
            steps = _configured_steps(
                raw_steps,
                config_path,
                default_timeout,
                rel,
            )

        items[item_id] = Item(
            id=item_id,
            path=rel,
            kind=kind,
            process=process,
            needs=needs,
            watch=watch,
            affected=affected,
            reuse=reuse,
            variables=variables,
            steps=steps,
            config_path=config_path,
            config_data=data,
            builder=builder_name if has_builder else None,
            builder_path=builder_path,
            runtime_role=runtime_role,
            runtime_image=runtime_image,
            verification=verification,
        )

    verification_items = [
        item
        for item in items.values()
        if item.verification is not None
    ]
    if verification_items:
        assert verification_package is not None
        if PACKAGE_ITEM_ID in items:
            raise ConfigError(
                f"verification package item id conflicts with consumer item: {PACKAGE_ITEM_ID}"
            )
        processed_verification = any(
            item.process for item in verification_items
        )
        items[PACKAGE_ITEM_ID] = Item(
            id=PACKAGE_ITEM_ID,
            path=PACKAGE_ITEM_PATH,
            kind="cad-verification-package",
            process=processed_verification,
            needs=(),
            watch=(),
            affected="direct",
            reuse=True,
            variables=variables,
            steps=(
                package_step(
                    verification_package,
                    timeout_seconds=default_timeout,
                ),
            ),
            config_path=root_path,
            config_data={
                "internal": "verification-package",
                "repository": verification_package.repository,
                "version": verification_package.version,
                "commit": verification_package.commit,
            },
            internal=True,
        )

    for role, users in builtin_users.items():
        producer_id = runtime_batch_id(role)
        if producer_id in items:
            raise ConfigError(
                f"built-in runtime item id conflicts with consumer item: {producer_id}"
            )
        runtime_image = runtimes[role]
        processed_users = [
            (item_id, rel)
            for item_id, rel in users
            if items[item_id].process
        ]
        producer_input_rows: list[str] = []
        verified_processed = []
        for item_id, rel in processed_users:
            producer_input_rows.extend(
                (
                    f"{rel.as_posix()}/ci.yml",
                    f"{rel.as_posix()}/model.py",
                )
            )
            verification = items[item_id].verification
            if verification is not None:
                verified_processed.append(item_id)
                producer_input_rows.append(verification.definition)
        producer_inputs = tuple(dict.fromkeys(producer_input_rows))
        producer_needs = (
            (PACKAGE_ITEM_ID,)
            if verified_processed
            else ()
        )
        items[producer_id] = Item(
            id=producer_id,
            path=runtime_batch_path(role),
            kind="cad-runtime",
            process=bool(processed_users),
            needs=producer_needs,
            watch=(),
            affected="direct",
            reuse=True,
            variables=variables,
            steps=(
                runtime_batch_step(
                    role,
                    inputs=producer_inputs,
                    timeout_seconds=default_timeout,
                ),
            ),
            config_path=root_path,
            config_data={"internal": "built-in-runtime", "runtime": role},
            runtime_role=role,
            runtime_image=runtime_image,
            internal=True,
        )

    for item in items.values():
        unknown = sorted(set(item.needs) - set(items))
        if unknown:
            raise ConfigError(
                f"{item.id} needs unknown item(s): {', '.join(unknown)}"
            )
        if item.process:
            excluded = sorted(
                dependency
                for dependency in item.needs
                if not items[dependency].process
            )
            if excluded:
                raise ConfigError(
                    f"processed item {item.id} needs non-processed item(s): "
                    + ", ".join(excluded)
                )

    for item in items.values():
        for step in item.steps:
            copy = step.copy
            if copy is None:
                continue
            if copy.dependency not in item.needs:
                raise ConfigError(
                    "copy dependency must be a direct need: "
                    f"{item.config_path}:{step.id}: {copy.dependency}"
                )
            dependency = items[copy.dependency]
            dependency_outputs = tuple(
                output
                for dependency_step in dependency.steps
                for output in dependency_step.outputs
            )
            source_root = PurePosixPath(copy.source)
            for output in step.outputs:
                selected = (
                    PurePosixPath(output)
                    if copy.source == "."
                    else source_root / PurePosixPath(output)
                )
                if not any(
                    selected.parts[: len(PurePosixPath(candidate).parts)]
                    == PurePosixPath(candidate).parts
                    for candidate in dependency_outputs
                ):
                    raise ConfigError(
                        "copy source is outside dependency declared output: "
                        f"{item.config_path}:{step.id}: {selected.as_posix()}"
                    )

    _check_nested_item_output_roots(items)
    _check_cycles(items)

    if pages is not None and pages.item is not None:
        try:
            pages_item = items[pages.item]
        except KeyError as exc:
            raise ConfigError(
                f"publication.pages references unknown item: {pages.item}"
            ) from exc
        if not pages_item.process:
            raise ConfigError(
                f"publication.pages item is not processed: {pages.item}"
            )
        if pages_item.internal:
            raise ConfigError(
                f"publication.pages cannot reference internal item: {pages.item}"
            )
        declared_outputs = {
            output
            for step in pages_item.steps
            for output in step.outputs
        }
        if pages.output not in declared_outputs:
            raise ConfigError(
                "publication.pages.output is not declared by item "
                f"{pages.item}: {pages.output}"
            )

    if pages is not None and pages.builder is not None:
        try:
            builder_path = builders[pages.builder]
        except KeyError as exc:
            raise ConfigError(
                f"publication.pages references unknown builder: {pages.builder}"
            ) from exc
        steps, _ = _builder_steps(
            repo,
            pages.builder,
            builder_path,
            default_timeout,
            Path("."),
        )
        if len(steps) != 1:
            raise ConfigError(
                "publication.pages builder requires exactly one command step: "
                f"{pages.builder}"
            )
        step = steps[0]
        if (
            step.run is None
            or step.copy is not None
            or step.selection_context != "none"
        ):
            raise ConfigError(
                "publication.pages builder requires one plain command step: "
                f"{pages.builder}"
            )
        if pages.output not in step.outputs:
            raise ConfigError(
                "publication.pages.output is not declared by builder "
                f"{pages.builder}: {pages.output}"
            )
        pages = replace(
            pages,
            builder_path=builder_path,
            builder_step=step,
        )

    return RepositoryConfig(
        items=items,
        pages=pages,
        variables=variables,
        runtimes=tuple(sorted(runtimes.items())),
        verification_package=verification_package,
    )


def load_repository(repo: Path) -> dict[str, Item]:
    """Backward-compatible item-only repository loader."""

    return load_repository_config(repo).items


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
