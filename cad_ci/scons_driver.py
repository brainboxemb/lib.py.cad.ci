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
    AlwaysBuild,
    CacheDir,
    Command,
    Default,
    Depends,
    NoCache,
    SConsignFile,
    Value,
)

from cad_ci.scons_bundle import (
    BundleError,
    bundle_sha256,
    materialize_bundle,
    remove_outputs,
    write_bundle,
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


def _dependency_context(spec: dict) -> dict:
    """Build runtime context for direct item dependencies."""

    result: dict[str, dict] = {}
    for dependency in spec["direct_dependencies"]:
        final_spec = SPECS[str(dependency["final_key"])]
        final_bundle = _bundle_path(final_spec)
        if not final_bundle.is_file():
            raise BundleError(
                f"dependency bundle is missing: {dependency['item_id']}"
            )

        result[str(dependency["item_id"])] = {
            "output_root": str(
                (ROOT / "build" / Path(dependency["item_path"])).resolve()
            ),
            "outputs": list(dependency["outputs"]),
            "final_bundle": str(final_bundle.resolve()),
            "final_bundle_sha256": bundle_sha256(final_bundle),
        }
    return result


def _command_environment(spec: dict) -> dict[str, str]:
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
    env.update(
        {
            "CAD_CI_REPO": str(ROOT),
            "CAD_CI_ITEM": str(spec["item_id"]),
            "CAD_CI_ITEM_PATH": str(
                (ROOT / Path(spec["item_path"])).resolve()
            ),
            "CAD_CI_OUTPUT": str(_output_root(spec).resolve()),
            "CAD_CI_DEPENDENCIES_JSON": json.dumps(
                _dependency_context(spec),
                sort_keys=True,
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


def _execute_bundle(target, source, env) -> int:
    """Materialize prerequisites, execute one step and write its bundle target."""

    key = str(env["CAD_CI_KEY"])
    spec = SPECS[key]
    bundle = Path(str(target[0])).resolve()
    result_path = ROOT / Path(spec["action_result"])
    output_root = _output_root(spec)

    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.unlink(missing_ok=True)
    result_path.unlink(missing_ok=True)

    started = time.monotonic()
    try:
        # Cumulative predecessor/final dependency bundles restore every output
        # the current action may legitimately read.
        for dependency_key in spec["materialize_before"]:
            _materialize_spec(SPECS[str(dependency_key)])

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
            cwd=ROOT / Path(spec["item_path"]),
            env=_command_environment(spec),
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
    node = Command(
        str(ROOT / Path(spec["bundle"])),
        source_nodes,
        _execute_bundle,
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
