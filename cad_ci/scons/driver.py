"""Small SCons-side graph driver for CAD CI step bundle targets.

The Python library writes the complete manifest. This file only wires SCons
nodes and runs one consumer action per dirty/forced step. SCons owns target
freshness, prerequisite ordering, persistent signatures and CacheDir.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

from SCons.Script import (
    ARGUMENTS,
    Action,
    AlwaysBuild,
    CacheDir,
    Command,
    Default,
    Depends,
    NoCache,
    SConsignFile,
    Value,
)

from cad_ci.scons.bundle import (
    BundleError,
    bundle_sha256,
    copy_dependency_outputs,
    materialize_bundle,
    remove_outputs,
    write_bundle,
)
from cad_ci.execution.timing import utc_now
from cad_ci.verification.package import (
    PACKAGE_ITEM_ID,
    VerificationPackageError,
    materialized_wheel,
)


ROOT = Path.cwd().resolve()


def _manifest_path() -> Path:
    """Resolve the manifest argument relative to the consumer repository."""

    value = Path(ARGUMENTS["CAD_CI_MANIFEST"])
    return value if value.is_absolute() else ROOT / value


MANIFEST = json.loads(_manifest_path().read_text(encoding="utf-8"))
SPECS = {str(spec["key"]): spec for spec in MANIFEST["targets"]}


def _write_json(path: Path, data: dict) -> None:
    """Write one private action observation for post-run classification."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _bundle_path(spec: dict) -> Path:
    """Return one private bundle path in the consumer checkout."""

    return ROOT / Path(spec["bundle"])


def _output_root(spec: dict) -> Path:
    """Return the materialized output root for one item."""

    return ROOT / "build" / Path(spec["item_path"])


def _materialize_spec(spec: dict) -> str:
    """Materialize one cumulative prerequisite bundle."""

    return materialize_bundle(
        _bundle_path(spec),
        _output_root(spec),
        tuple(str(value) for value in spec["bundle_outputs"]),
    )


def _dependency_snapshot_root(spec: dict, dependency: dict) -> Path:
    """Return the target-private runtime root for one direct dependency."""

    return (
        ROOT
        / Path(MANIFEST["dependency_run_root"])
        / Path(spec["item_path"])
        / str(spec["step_id"])
        / Path(dependency["item_path"])
    )


def _dependency_context(spec: dict) -> dict:
    """Materialize private direct-dependency snapshots for one consumer target."""

    result: dict[str, dict] = {}
    for dependency in spec["direct_dependencies"]:
        final_spec = SPECS[str(dependency["final_key"])]
        final_bundle = _bundle_path(final_spec)
        if not final_bundle.is_file():
            raise BundleError(
                f"dependency bundle is missing: {dependency['item_id']}"
            )

        snapshot_root = _dependency_snapshot_root(spec, dependency)
        materialize_bundle(
            final_bundle,
            snapshot_root,
            tuple(str(value) for value in dependency["outputs"]),
        )
        row = {
            "output_root": str(snapshot_root.resolve()),
            "outputs": list(dependency["outputs"]),
            "final_bundle": str(final_bundle.resolve()),
            "final_bundle_sha256": bundle_sha256(final_bundle),
        }
        if (
            spec.get("builder_verification_package")
            and str(dependency["item_id"]) == PACKAGE_ITEM_ID
        ):
            try:
                wheel = materialized_wheel(snapshot_root / "dist")
            except VerificationPackageError as exc:
                raise BundleError(
                    f"verification package dependency is invalid: {exc}"
                ) from exc
            row["verification_wheel"] = str(wheel.resolve())
        result[str(dependency["item_id"])] = row
    return result


def _command_environment(
    spec: dict,
    dependency_context: dict,
) -> dict[str, str]:
    """Build the environment exposed to the consumer command."""

    env = dict(os.environ)

    # Repository variables override inherited runner/caller values. CAD-CI's
    # own values are applied afterward and remain authoritative.
    env.update(
        {
            str(name): str(value)
            for name, value in spec.get("variables", {}).items()
        }
    )
    verification_wheel = ""
    if spec.get("builder_verification_package"):
        verification_wheel = str(
            dependency_context.get(PACKAGE_ITEM_ID, {}).get(
                "verification_wheel",
                "",
            )
        )

    env.update(
        {
            "CAD_CI_REPO": str(ROOT),
            "CAD_CI_ITEM": str(spec["item_id"]),
            "CAD_CI_ITEM_PATH": str(
                (ROOT / Path(spec["item_path"])).resolve()
            ),
            "CAD_CI_BUILDER": str(spec.get("builder") or ""),
            "CAD_CI_BUILDER_PATH": (
                str((ROOT / Path(str(spec["builder_path"]))).resolve())
                if spec.get("builder_path")
                else ""
            ),
            "CAD_CI_RUNTIME": str(spec.get("runtime") or ""),
            "CAD_CI_RUNTIME_IMAGE": str(spec.get("runtime_image") or ""),
            "CAD_CI_OUTPUT": str(_output_root(spec).resolve()),
            "CAD_CI_VERIFICATION_WHEEL": verification_wheel,
            "CAD_CI_DEPENDENCIES_JSON": json.dumps(
                dependency_context,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "CAD_CI_ACTIVE_DEPENDENTS_JSON": json.dumps(
                list(spec.get("active_dependents", [])),
                separators=(",", ":"),
            ),
        }
    )
    return env


def _action_error(
    result_path: Path,
    spec: dict,
    *,
    status: str,
    duration: float,
    exit_code: int | None = None,
    error: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> int:
    """Record one failed consumer action and return SCons failure."""

    data = {
        "key": spec["key"],
        "status": status,
        "action_executed": started_at is not None,
        "action_type": spec.get("action_type", "command"),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(duration, 3),
        "exit_code": exit_code,
        "timeout_seconds": spec["timeout_seconds"],
    }
    if error:
        data["error"] = error
    _write_json(result_path, data)
    return 1


def _action_label(target, source, env) -> str:
    """Return the concise operator-facing label for one executed target."""

    spec = SPECS[str(env["CAD_CI_KEY"])]
    verb = "copy" if spec.get("action_type") == "copy" else "run"
    return f"CAD CI {verb}: {env['CAD_CI_KEY']}"


def _execute_bundle(target, source, env) -> int:
    """Execute one command/copy action and write its cumulative bundle target."""

    key = str(env["CAD_CI_KEY"])
    spec = SPECS[key]
    bundle = Path(str(target[0])).resolve()
    result_path = ROOT / Path(spec["action_result"])
    output_root = _output_root(spec)

    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.unlink(missing_ok=True)
    result_path.unlink(missing_ok=True)

    direct_dependency_keys = {
        str(dependency["final_key"])
        for dependency in spec["direct_dependencies"]
    }

    if spec.get("action_type") == "copy":
        action_started_at = utc_now()
        started = time.monotonic()
        try:
            copy = spec.get("copy") or {}
            dependency_id = str(copy.get("dependency", ""))
            descriptor = next(
                (
                    dependency
                    for dependency in spec["direct_dependencies"]
                    if str(dependency["item_id"]) == dependency_id
                ),
                None,
            )
            if descriptor is None:
                raise BundleError(
                    f"copy dependency is not a direct dependency: {dependency_id}"
                )
            source_spec = SPECS[str(descriptor["final_key"])]
            source_bundle = _bundle_path(source_spec)
            if not source_bundle.is_file():
                raise BundleError(
                    f"dependency bundle is missing: {dependency_id}"
                )

            predecessors = [
                str(dependency_key)
                for dependency_key in spec["materialize_before"]
                if str(dependency_key) not in direct_dependency_keys
            ]
            if len(predecessors) > 1:
                raise BundleError(
                    f"copy target has multiple own predecessors: {key}"
                )
            predecessor_bundle = (
                _bundle_path(SPECS[predecessors[0]])
                if predecessors
                else None
            )

            copy_dependency_outputs(
                source_bundle,
                bundle,
                str(copy.get("source", ".")),
                tuple(str(value) for value in spec["outputs"]),
                cumulative_outputs=tuple(
                    str(value) for value in spec["bundle_outputs"]
                ),
                predecessor_bundle=predecessor_bundle,
            )
        except (BundleError, OSError) as exc:
            bundle.unlink(missing_ok=True)
            return _action_error(
                result_path,
                spec,
                status="output_error",
                duration=time.monotonic() - started,
                error=str(exc),
                started_at=action_started_at,
                finished_at=utc_now(),
            )

        action_finished_at = utc_now()
        duration = time.monotonic() - started
        _write_json(
            result_path,
            {
                "key": spec["key"],
                "status": "pass",
                "action_executed": True,
                "action_type": "copy",
                "started_at": action_started_at,
                "finished_at": action_finished_at,
                "duration_seconds": round(duration, 3),
                "exit_code": None,
                "timeout_seconds": None,
                "bundle_sha256": bundle_sha256(bundle),
            },
        )
        print(f"CAD CI copied: {spec['key']}", flush=True)
        return 0

    started = time.monotonic()
    try:
        # Cumulative predecessor bundles restore outputs owned by earlier steps.
        # Command actions additionally receive target-private complete snapshots
        # for each direct dependency.
        for dependency_key in spec["materialize_before"]:
            if str(dependency_key) not in direct_dependency_keys:
                _materialize_spec(SPECS[str(dependency_key)])

        dependency_context = _dependency_context(spec)
        output_root.mkdir(parents=True, exist_ok=True)
        remove_outputs(
            output_root,
            tuple(str(value) for value in spec["outputs"]),
        )
    except (BundleError, OSError) as exc:
        return _action_error(
            result_path,
            spec,
            status="materialization_error",
            duration=time.monotonic() - started,
            error=str(exc),
        )

    command = spec["run"]
    action_started_at = utc_now()
    try:
        completed = subprocess.run(
            command,
            cwd=(
                ROOT
                if spec.get("internal")
                else ROOT / Path(spec["item_path"])
            ),
            env=_command_environment(spec, dependency_context),
            shell=bool(spec["shell"]),
            check=False,
            timeout=spec["timeout_seconds"],
        )
    except subprocess.TimeoutExpired:
        return _action_error(
            result_path,
            spec,
            status="timeout",
            duration=time.monotonic() - started,
            started_at=action_started_at,
            finished_at=utc_now(),
        )
    except OSError as exc:
        return _action_error(
            result_path,
            spec,
            status="fail",
            duration=time.monotonic() - started,
            error=str(exc),
            started_at=action_started_at,
            finished_at=utc_now(),
        )

    action_finished_at = utc_now()
    duration = time.monotonic() - started
    if completed.returncode != 0:
        return _action_error(
            result_path,
            spec,
            status="fail",
            duration=duration,
            exit_code=completed.returncode,
            started_at=action_started_at,
            finished_at=action_finished_at,
        )

    try:
        write_bundle(
            bundle,
            output_root,
            tuple(str(value) for value in spec["bundle_outputs"]),
        )
    except BundleError as exc:
        bundle.unlink(missing_ok=True)
        return _action_error(
            result_path,
            spec,
            status="output_error",
            duration=duration,
            exit_code=completed.returncode,
            error=str(exc),
            started_at=action_started_at,
            finished_at=action_finished_at,
        )

    _write_json(
        result_path,
        {
            "key": spec["key"],
            "status": "pass",
            "action_executed": True,
            "action_type": "command",
            "started_at": action_started_at,
            "finished_at": action_finished_at,
            "duration_seconds": round(duration, 3),
            "exit_code": completed.returncode,
            "timeout_seconds": spec["timeout_seconds"],
            "bundle_sha256": bundle_sha256(bundle),
        },
    )
    print(f"CAD CI built: {spec['key']}", flush=True)
    return 0


CacheDir(str(ROOT / Path(MANIFEST["cache_root"])))
sconsign = ROOT / Path(MANIFEST["sconsign"])
sconsign.parent.mkdir(parents=True, exist_ok=True)
SConsignFile(str(sconsign))

active = set(str(value) for value in MANIFEST["active_keys"])
forced = set(str(value) for value in MANIFEST["force_keys"])

# Per-run action observations may never leak from an earlier invocation.
for key in active:
    (ROOT / Path(SPECS[key]["action_result"])).unlink(missing_ok=True)

bundle_nodes = {}
for key, spec in SPECS.items():
    source_nodes = [str(ROOT / Path(value)) for value in spec["sources"]]
    action = Action(_execute_bundle, strfunction=_action_label)
    node = Command(
        str(ROOT / Path(spec["bundle"])),
        source_nodes,
        action,
        CAD_CI_KEY=key,
    )
    Depends(
        node,
        Value(
            json.dumps(
                spec["signature"],
                sort_keys=True,
                separators=(",", ":"),
            )
        ),
    )
    if key in forced or not bool(spec["reuse"]):
        AlwaysBuild(node)
        # Explicit force means execute the action, not restore the same target
        # from CacheDir. reuse=false has the same no-cache contract.
        NoCache(node)
    bundle_nodes[key] = node

for key, spec in SPECS.items():
    for dependency_key in spec["dependencies"]:
        Depends(bundle_nodes[key], bundle_nodes[str(dependency_key)])

Default(
    [
        bundle_nodes[str(key)]
        for key in MANIFEST["requested_keys"]
    ]
)
