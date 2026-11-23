"""Path matching and source-file discovery for CAD CI configuration."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable


_GENERATED_ROOTS = {".git", ".cache", "build"}


class PathDiscoveryError(ValueError):
    """Raised when a configured source path is unsafe or unsupported."""


def matches(path: str, pattern: str) -> bool:
    """Match one repository path against a configured POSIX-style pattern."""

    path = path.replace("\\", "/")
    pattern = pattern.replace("\\", "/")

    # fnmatch does not give trailing ** the directory-tree meaning needed by
    # repository configuration. Match the recursive directory prefix against
    # the path and each POSIX ancestor so wildcard syntax in that prefix keeps
    # its normal meaning.
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        parts = path.split("/")
        candidates = (
            path,
            *(
                "/".join(parts[:index])
                for index in range(1, len(parts))
            ),
        )
        return any(fnmatch(candidate, prefix) for candidate in candidates)
    return fnmatch(path, pattern)


def _ignored_relative_path(relative: Path) -> bool:
    """Return whether one repository path belongs to generated/tool state."""

    if not relative.parts:
        return False
    if relative.parts[0] in _GENERATED_ROOTS:
        return True
    return "__pycache__" in relative.parts


def source_inventory(repo: Path) -> tuple[Path, ...]:
    """Enumerate source file/symlink candidates once for one execution run.

    Symlinks stay in the inventory so a step that actually matches one can
    reject it. Unselected steps never inspect their patterns against the
    inventory and therefore cannot make an unrelated selective run fail.
    """

    repo = repo.resolve()
    result: list[Path] = []
    for candidate in repo.rglob("*"):
        relative = candidate.relative_to(repo)
        if _ignored_relative_path(relative):
            continue
        if candidate.is_symlink() or candidate.is_file():
            result.append(candidate)
    return tuple(sorted(set(result), key=lambda path: path.as_posix()))


def files_for_patterns(
    repo: Path,
    patterns: tuple[str, ...],
    *,
    exclude: tuple[str, ...] = (),
    candidates: Iterable[Path] | None = None,
) -> list[Path]:
    """Return stable regular source files matched by repository patterns.

    Root generated directories are ignored. A symlink that is actually matched
    is rejected instead of followed so target signatures cannot depend on
    content outside the repository-owned source tree.

    When candidates is supplied, it must come from one repository source
    inventory and is reused without another filesystem walk.
    """

    repo = repo.resolve()
    excluded = {value.replace("\\", "/") for value in exclude}
    inventory = source_inventory(repo) if candidates is None else candidates
    result: list[Path] = []

    for candidate in inventory:
        relative = candidate.relative_to(repo)
        relative_text = relative.as_posix()
        if relative_text in excluded:
            continue
        if not any(matches(relative_text, pattern) for pattern in patterns):
            continue

        if candidate.is_symlink():
            raise PathDiscoveryError(
                f"configured source input is a symlink: {relative_text}"
            )
        # source_inventory() already limits candidates to regular files and
        # symlinks. Callers may pass their own iterable, so retain this guard.
        if candidate.is_file():
            result.append(candidate)

    return sorted(set(result), key=lambda path: path.as_posix())
