"""Path matching and source-file discovery for CAD CI configuration."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path


_GENERATED_ROOTS = {".git", ".cache", "build"}


class PathDiscoveryError(ValueError):
    """Raised when a configured source path is unsafe or unsupported."""


def matches(path: str, pattern: str) -> bool:
    """Match one repository path against a configured POSIX-style pattern."""

    path = path.replace("\\", "/")
    pattern = pattern.replace("\\", "/")

    # fnmatch does not give trailing ** the directory-tree meaning needed by
    # repository configuration. Treat folder/** as folder plus descendants.
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return path == prefix or path.startswith(prefix + "/")
    return fnmatch(path, pattern)


def _ignored_relative_path(relative: Path) -> bool:
    """Return whether one repository path belongs to generated/tool state."""

    if not relative.parts:
        return False
    if relative.parts[0] in _GENERATED_ROOTS:
        return True
    return "__pycache__" in relative.parts


def files_for_patterns(
    repo: Path,
    patterns: tuple[str, ...],
    *,
    exclude: tuple[str, ...] = (),
) -> list[Path]:
    """Return stable regular source files matched by repository patterns.

    Root generated directories are ignored. A symlink that is actually matched
    is rejected instead of followed so target signatures cannot depend on
    content outside the repository-owned source tree.
    """

    excluded = {value.replace("\\", "/") for value in exclude}
    result: list[Path] = []

    for candidate in repo.rglob("*"):
        relative = candidate.relative_to(repo)
        if _ignored_relative_path(relative):
            continue

        relative_text = relative.as_posix()
        if relative_text in excluded:
            continue
        if not any(matches(relative_text, pattern) for pattern in patterns):
            continue

        if candidate.is_symlink():
            raise PathDiscoveryError(
                f"configured source input is a symlink: {relative_text}"
            )
        if candidate.is_file():
            result.append(candidate)

    return sorted(set(result), key=lambda path: path.as_posix())
