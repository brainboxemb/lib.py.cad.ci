"""Host-side orchestration for built-in generic CAD builder batches."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import sys
from typing import Mapping

from .catalog import (
    BUILTIN_BUILDERS,
    RUNTIME_BATCH_CONTRACTS,
    runtime_catalog_signature,
)

from ..context import current_context
from ..execution.process import (
    DEFAULT_PROCESS_RUNNER,
    ProcessExecutionError,
    ProcessRunner,
)
from ..verification.package import (
    PACKAGE_ITEM_ID,
    materialized_wheel,
)


class CadBuilderError(RuntimeError):
    """Raised for invalid built-in batch configuration or execution."""


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise CadBuilderError(f"missing required environment: {name}")
    return value


def _safe_relative(value: str, field: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or value in (".", "..")
    ):
        raise CadBuilderError(f"{field} must be a safe repository-relative path")
    return path.as_posix()


def _active_ids(env: Mapping[str, str]) -> tuple[str, ...]:
    raw = _required(env, "CAD_CI_ACTIVE_DEPENDENTS_JSON")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CadBuilderError(
            "CAD_CI_ACTIVE_DEPENDENTS_JSON must contain valid JSON"
        ) from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CadBuilderError(
            "CAD_CI_ACTIVE_DEPENDENTS_JSON must contain a string list"
        )
    if not value:
        raise CadBuilderError("built-in runtime batch has no active model items")
    return tuple(value)


def build_manifest(
    runtime: str,
    contract: int,
    catalog: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[Path, Path, str, Path | None]:
    """Write one manifest and resolve any shared verification wheel."""

    env = os.environ if environ is None else environ
    expected = RUNTIME_BATCH_CONTRACTS.get(runtime)
    if expected is None:
        raise CadBuilderError(f"unknown built-in runtime role: {runtime}")
    if contract != expected:
        raise CadBuilderError(
            f"unsupported {runtime} batch contract {contract}; expected {expected}"
        )
    expected_catalog = runtime_catalog_signature(runtime)
    if catalog != expected_catalog:
        raise CadBuilderError(
            f"built-in catalog mismatch for {runtime}: "
            f"{catalog!r} != {expected_catalog!r}"
        )

    from ..config import load_repository

    repo = Path(_required(env, "CAD_CI_REPO")).resolve()
    output = Path(_required(env, "CAD_CI_OUTPUT")).resolve()
    runtime_env = _required(env, "CAD_CI_RUNTIME")
    image = _required(env, "CAD_CI_RUNTIME_IMAGE")
    if runtime_env != runtime:
        raise CadBuilderError(
            f"runtime environment mismatch: {runtime_env!r} != {runtime!r}"
        )
    try:
        output.relative_to(repo)
    except ValueError as exc:
        raise CadBuilderError("CAD_CI_OUTPUT must stay inside CAD_CI_REPO") from exc

    items = load_repository(repo)
    rows = []
    for item_id in _active_ids(env):
        try:
            item = items[item_id]
        except KeyError as exc:
            raise CadBuilderError(f"unknown active model item: {item_id}") from exc
        builder_name = item.builder or ""
        try:
            builder = BUILTIN_BUILDERS[builder_name]
        except KeyError as exc:
            raise CadBuilderError(
                f"active item {item_id} does not use a built-in CAD builder"
            ) from exc
        if builder.runtime_role != runtime:
            raise CadBuilderError(
                f"active item {item_id} uses runtime {builder.runtime_role}, "
                f"not {runtime}"
            )

        item_path = _safe_relative(item.path.as_posix(), "item path")
        source = repo / item.path / "model.py"
        if not source.is_file() or source.is_symlink():
            raise CadBuilderError(
                f"{item_id}: built-in {builder_name} requires regular model.py"
            )
        row = {
            "item_id": item_id,
            "item_path": item_path,
            "builder": builder.name,
            "builder_contract": builder.contract,
            "engine_python": builder.engine_python,
            "source": f"/repo/{item_path}/model.py",
            "output": f"/output/items/{item_path}/{builder.output}",
        }
        if item.verification is not None:
            row["verification"] = {
                "adapter": item.verification.adapter,
                "definition": f"/repo/{item.verification.definition}",
                "verification_id": item.verification.verification_id,
                "output": f"/output/items/{item_path}/verification",
            }
        rows.append(row)

    verification_wheel = None
    if any("verification" in row for row in rows):
        context = current_context(repo=repo, items=items)
        dist = context.dependency(PACKAGE_ITEM_ID).output("dist")
        verification_wheel = materialized_wheel(dist)

    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "batch-manifest.json"
    report = output / "batch-report.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "runtime": runtime,
                "batch_contract": contract,
                "catalog": catalog,
                "models": rows,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest, report, image, verification_wheel


def run_batch(
    runtime: str,
    contract: int,
    catalog: str,
    *,
    environ: Mapping[str, str] | None = None,
    process: ProcessRunner | None = None,
) -> int:
    """Execute one shared runtime batch through the external-process boundary."""

    env = os.environ if environ is None else environ
    runner = DEFAULT_PROCESS_RUNNER if process is None else process
    manifest, report, image, verification_wheel = build_manifest(
        runtime,
        contract,
        catalog,
        environ=env,
    )
    repo = Path(_required(env, "CAD_CI_REPO")).resolve()
    output = Path(_required(env, "CAD_CI_OUTPUT")).resolve()
    cad_ci_dir = Path(__file__).resolve().parents[1]
    pythonpath = "/cad-ci-lib"
    extra_mounts: list[str] = []
    if verification_wheel is not None:
        pythonpath = "/cad-verification.whl:/cad-ci-lib"
        extra_mounts = [
            "-v",
            f"{verification_wheel}:/cad-verification.whl:ro",
        ]

    runner.run(["docker", "pull", image], cwd=repo, check=True)
    completed = runner.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "-e",
            f"PYTHONPATH={pythonpath}",
            "-v",
            f"{repo}:/repo:ro",
            "-v",
            f"{output}:/output",
            "-v",
            f"{cad_ci_dir}:/cad-ci-lib/cad_ci:ro",
            *extra_mounts,
            "-w",
            "/repo",
            image,
            "python",
            "-m",
            "cad_ci.builders.runtime",
            "--manifest",
            f"/output/{manifest.name}",
            "--report",
            f"/output/{report.name}",
        ],
        cwd=repo,
        check=False,
    )
    return int(completed.returncode)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point used by the normal shared-producer Step."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    batch = subparsers.add_parser("batch")
    batch.add_argument("--runtime", required=True)
    batch.add_argument("--contract", type=int, required=True)
    batch.add_argument("--catalog", required=True)
    args = parser.parse_args(argv)

    try:
        if args.operation == "batch":
            return run_batch(args.runtime, args.contract, args.catalog)
    except (CadBuilderError, ProcessExecutionError) as exc:
        print(f"CAD CI built-in builder error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
