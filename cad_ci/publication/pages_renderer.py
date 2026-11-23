"""Run one repository-owned Pages renderer at the durable publication boundary.

This is deliberately not a scheduler or rebuild engine. The normal CAD-CI
SCons graph has already finished and the durable build commit already exists.
The renderer runs exactly once with explicit publication context and writes only
to a fresh temporary output root.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from .build_store import BuildStoreError
from ..model import PagesPublication
from ..scons.bundle import BundleError, output_snapshot


def render_pages_builder(
    *,
    repo: Path,
    publication: PagesPublication,
    complete_scope: Path,
    build_scope: str,
    source_sha: str,
    source_ref: str,
    build_commit: str,
    output_root: Path,
    variables: tuple[tuple[str, str], ...] = (),
) -> Path:
    """Run one validated publication builder and return its Pages directory."""

    repo = repo.resolve()
    complete_scope = complete_scope.resolve()
    output_root = output_root.resolve()

    if (
        publication.builder is None
        or publication.builder_path is None
        or publication.builder_step is None
    ):
        raise BuildStoreError("Pages publication has no resolved builder")

    step = publication.builder_step
    if step.run is None or step.copy is not None:
        raise BuildStoreError("Pages publication builder is not a command step")

    output_root.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    for name in tuple(env):
        if name.startswith("CAD_CI_"):
            env.pop(name)
    env.update(dict(variables))
    env.update(
        {
            "CAD_CI_REPO": str(repo),
            "CAD_CI_OUTPUT": str(output_root),
            "CAD_CI_BUILDER": publication.builder,
            "CAD_CI_BUILDER_PATH": str(
                (repo / publication.builder_path).resolve()
            ),
            "CAD_CI_COMPLETE_SCOPE": str(complete_scope),
            "CAD_CI_BUILD_SCOPE": build_scope,
            "CAD_CI_SOURCE_SHA": source_sha,
            "CAD_CI_SOURCE_REF": source_ref,
            "CAD_CI_BUILD_COMMIT": build_commit,
        }
    )

    command = step.run
    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            env=env,
            shell=isinstance(command, str),
            timeout=step.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BuildStoreError(
            f"Pages publication builder timed out: {publication.builder}"
        ) from exc
    except OSError as exc:
        raise BuildStoreError(
            f"Pages publication builder could not start: "
            f"{publication.builder}: {exc}"
        ) from exc

    if completed.returncode != 0:
        raise BuildStoreError(
            "Pages publication builder failed with exit "
            f"{completed.returncode}: {publication.builder}"
        )

    try:
        output_snapshot(output_root, step.outputs)
    except BundleError as exc:
        raise BuildStoreError(
            f"Pages publication builder produced invalid output: {exc}"
        ) from exc

    site = output_root / publication.output
    if not site.is_dir():
        raise BuildStoreError(
            "configured Pages publication output is not a directory: "
            f"{publication.builder}:{publication.output}"
        )
    return site.resolve()
