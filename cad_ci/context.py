"""Expose validated dependency outputs to consumer step scripts.

Consumer code should never reconstruct the generic build directory layout or
read dependency state files directly. This module resolves the current item,
validates direct dependencies with the runner's normal rules, and exposes only
outputs declared by dependency ci.yml files.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .config import load_repository
from .model import Item
from .runner import RunError, current_item_result, item_output_dir


class ContextError(RunError):
    """Raised when dependency context is missing, stale or requested unsafely."""


def _declared_outputs(item: Item) -> frozenset[str]:
    """Return every output path explicitly owned by one dependency item."""

    return frozenset(output for step in item.steps for output in step.outputs)


@dataclass(frozen=True)
class Dependency:
    """One validated direct dependency visible to the current consumer step."""

    id: str
    result_fingerprint: str
    _root: Path
    _outputs: frozenset[str]

    def output(self, name: str) -> Path:
        """Return one exact output declared by the dependency's ci.yml."""

        if name not in self._outputs:
            raise ContextError(
                f"{self.id} does not declare dependency output {name!r}"
            )
        path = self._root / name
        if not path.exists():
            raise ContextError(f"{self.id} dependency output is missing: {name}")
        return path


@dataclass(frozen=True)
class ItemContext:
    """Validated runtime context for the item currently executed by cad-ci."""

    repo: Path
    item: Item
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
        """Return direct dependencies in the order declared by the item."""

        return tuple(self._dependencies[item_id] for item_id in self.item.needs)


def current_context(
    *,
    repo: Path | None = None,
    item_id: str | None = None,
) -> ItemContext:
    """Resolve and validate the current item and all direct dependencies."""

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

    items = load_repository(repo)
    try:
        item = items[item_id]
    except KeyError as exc:
        raise ContextError(f"unknown current item: {item_id}") from exc

    dependencies: dict[str, Dependency] = {}
    for dependency_id in item.needs:
        dependency = items[dependency_id]
        try:
            result = current_item_result(repo, dependency, items)
        except RunError as exc:
            raise ContextError(
                f"{item.id} requires a current result for {dependency_id}: {exc}"
            ) from exc
        dependencies[dependency_id] = Dependency(
            id=dependency_id,
            result_fingerprint=result,
            _root=item_output_dir(repo, dependency),
            _outputs=_declared_outputs(dependency),
        )

    return ItemContext(repo=repo, item=item, _dependencies=dependencies)
