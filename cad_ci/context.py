"""Expose direct dependency output already made current by SCons.

The SCons action wrapper materializes each direct dependency's cumulative final
bundle into a target-private runtime snapshot before the consumer command runs
and supplies CAD_CI_DEPENDENCIES_JSON.
This module validates that runtime context. It never decides whether a
dependency should rebuild.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path

from .config import load_repository
from .model import Item
from .scons.bundle import (
    BundleError,
    bundle_sha256,
    outputs_match_bundle,
    read_bundle_manifest,
)


class ContextError(RuntimeError):
    """Raised when dependency runtime context is missing, stale or unsafe."""


def _declared_outputs(item: Item) -> frozenset[str]:
    """Return every output owned by the complete dependency item."""

    return frozenset(
        output
        for step in item.steps
        for output in step.outputs
    )


@dataclass(frozen=True)
class Dependency:
    """One direct dependency snapshot materialized from its final bundle."""

    id: str
    result_fingerprint: str
    _root: Path
    _outputs: frozenset[str]
    _bundle: Path

    @property
    def bundle_sha256(self) -> str:
        """Return the validated final bundle digest."""

        return self.result_fingerprint

    @property
    def root(self) -> Path:
        """Return the materialized dependency output root."""

        return self._root

    def output(self, name: str) -> Path:
        """Return one exact output declared by the dependency's ci.yml."""

        normalized = name.replace("\\", "/")
        if normalized not in self._outputs:
            raise ContextError(
                f"{self.id} does not declare dependency output {name!r}"
            )
        path = self._root / Path(normalized)
        if not path.exists():
            raise ContextError(
                f"{self.id} dependency output is missing: {normalized}"
            )
        return path


@dataclass(frozen=True)
class ItemContext:
    """Validated runtime context for the current consumer step."""

    repo: Path
    item: Item
    output: Path
    _dependencies: dict[str, Dependency]

    def dependency(self, item_id: str) -> Dependency:
        """Return one declared direct dependency by item ID."""

        try:
            return self._dependencies[item_id]
        except KeyError as exc:
            raise ContextError(
                f"{self.item.id} does not directly depend on {item_id}"
            ) from exc

    @property
    def dependencies(self) -> tuple[Dependency, ...]:
        """Return direct dependencies in ci.yml declaration order."""

        return tuple(
            self._dependencies[item_id]
            for item_id in self.item.needs
        )


def _dependency_rows(item: Item) -> dict[str, object]:
    """Read the runtime dependency map supplied by the SCons wrapper."""

    raw = os.environ.get("CAD_CI_DEPENDENCIES_JSON", "").strip()
    if not raw:
        if item.needs:
            raise ContextError(
                "CAD_CI_DEPENDENCIES_JSON is required for this item"
            )
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContextError(
            "CAD_CI_DEPENDENCIES_JSON is invalid JSON"
        ) from exc
    if not isinstance(data, dict):
        raise ContextError(
            "CAD_CI_DEPENDENCIES_JSON must be an object"
        )

    expected = set(item.needs)
    actual = set(str(value) for value in data)
    if actual != expected:
        raise ContextError(
            "runtime dependency set does not match ci.yml: "
            f"expected {sorted(expected)}, found {sorted(actual)}"
        )
    return data


def _validated_dependency(
    dependency: Item,
    row: object,
) -> Dependency:
    """Validate one materialized dependency against its final target bundle."""

    if not isinstance(row, dict):
        raise ContextError(
            f"invalid runtime dependency data for {dependency.id}"
        )

    root_value = row.get("output_root")
    outputs_value = row.get("outputs")
    bundle_value = row.get("final_bundle")
    digest_value = row.get("final_bundle_sha256")
    if (
        not isinstance(root_value, str)
        or not isinstance(outputs_value, list)
        or not all(isinstance(value, str) for value in outputs_value)
        or not isinstance(bundle_value, str)
        or not isinstance(digest_value, str)
    ):
        raise ContextError(
            f"invalid runtime dependency data for {dependency.id}"
        )

    declared = _declared_outputs(dependency)
    runtime_outputs = frozenset(outputs_value)
    if runtime_outputs != declared:
        raise ContextError(
            f"runtime outputs for {dependency.id} do not match ci.yml"
        )

    root = Path(root_value).resolve()
    bundle = Path(bundle_value).resolve()
    if not bundle.is_file():
        raise ContextError(
            f"{dependency.id} dependency bundle is missing"
        )

    try:
        actual_digest = bundle_sha256(bundle)
        manifest = read_bundle_manifest(bundle)
    except BundleError as exc:
        raise ContextError(
            f"{dependency.id} dependency bundle is invalid: {exc}"
        ) from exc

    if actual_digest != digest_value:
        raise ContextError(
            f"{dependency.id} dependency bundle digest does not match context"
        )
    if set(manifest["outputs"]) != set(declared):
        raise ContextError(
            f"{dependency.id} final bundle does not contain complete item output"
        )
    if not outputs_match_bundle(
        bundle,
        root,
        tuple(sorted(declared)),
    ):
        raise ContextError(
            f"{dependency.id} dependency output does not match its SCons bundle"
        )

    return Dependency(
        id=dependency.id,
        result_fingerprint=actual_digest,
        _root=root,
        _outputs=declared,
        _bundle=bundle,
    )


def current_context(
    *,
    repo: Path | None = None,
    item_id: str | None = None,
    items: dict[str, Item] | None = None,
) -> ItemContext:
    """Resolve current item and validate SCons-supplied direct dependencies."""

    if repo is None:
        raw_repo = os.environ.get("CAD_CI_REPO", "").strip()
        if not raw_repo:
            raise ContextError("CAD_CI_REPO is required")
        repo = Path(raw_repo)
    repo = repo.resolve()

    if item_id is None:
        item_id = os.environ.get("CAD_CI_ITEM", "").strip()
        if not item_id:
            raise ContextError("CAD_CI_ITEM is required")

    if items is None:
        items = load_repository(repo)
    try:
        item = items[item_id]
    except KeyError as exc:
        raise ContextError(f"unknown current item: {item_id}") from exc

    rows = _dependency_rows(item)
    dependencies = {
        dependency_id: _validated_dependency(
            items[dependency_id],
            rows[dependency_id],
        )
        for dependency_id in item.needs
    }

    raw_output = os.environ.get("CAD_CI_OUTPUT", "").strip()
    output = (
        Path(raw_output).resolve()
        if raw_output
        else (repo / "build" / item.path).resolve()
    )

    return ItemContext(
        repo=repo,
        item=item,
        output=output,
        _dependencies=dependencies,
    )
