"""SCons-side driver for CAD CI step targets.

The Python library writes a manifest with one cacheable bundle target per step.
This driver contains only graph wiring and the two small actions needed by
SCons: execute a consumer command into a bundle, then materialize that bundle
back into build/<item>.

SCons owns target signatures, dependency ordering, persistent state and
CacheDir. Result JSON files are observations of what happened; they never
participate in rebuild decisions.
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
    Requires,
    SConsignFile,
    Value,
)

from cad_ci.scons_bundle import (
    BundleError,
    bundle_sha256,
    materialize_bundle,
    write_bundle,
)


def _write_json(path: Path, data: dict) -> None:
    """Write one small action/materialization result atomically enough for CI."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _command_environment(spec: dict) -> dict[str, str]:
    """Build the environment exposed to a consumer step command."""

    env = dict(os.environ)
    env.update(
        {
            "CAD_CI_REPO": str(spec["repo"]),
            "CAD_CI_ITEM": str(spec["item_id"]),
            "CAD_CI_ITEM_PATH": str(spec["item_path"]),
            "CAD_CI_OUTPUT": str(spec["output_root"]),
            "CAD_CI_DEPENDENCIES_JSON": json.dumps(
                spec.get("dependency_context", {}),
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
    )
    return env


def _execute_bundle(target, source, env) -> int:
    """Run one consumer step and package its declared output on success."""

    spec = json.loads(str(env["CAD_CI_SPEC"]))
    bundle = Path(str(target[0])).resolve()
    result_path = Path(str(spec["execution_result"])).resolve()
    output_root = Path(str(spec["output_root"])).resolve()
    cwd = Path(str(spec["item_path"])).resolve()
    command = spec["run"]
    shell = bool(spec.get("shell", False))
    timeout = spec.get("timeout_seconds")

    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.unlink(missing_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=_command_environment(spec),
            shell=shell,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - started
        _write_json(
            result_path,
            {
                "key": spec["key"],
                "status": "timeout",
                "duration_seconds": round(duration, 3),
                "exit_code": None,
                "timeout_seconds": timeout,
            },
        )
        print(
            f"CAD CI timeout: {spec['key']} after {timeout}s",
            flush=True,
        )
        return 1
    except OSError as exc:
        duration = time.monotonic() - started
        _write_json(
            result_path,
            {
                "key": spec["key"],
                "status": "fail",
                "duration_seconds": round(duration, 3),
                "exit_code": None,
                "timeout_seconds": timeout,
                "error": str(exc),
            },
        )
        print(f"CAD CI command error: {spec['key']}: {exc}", flush=True)
        return 1

    duration = time.monotonic() - started
    if completed.returncode != 0:
        _write_json(
            result_path,
            {
                "key": spec["key"],
                "status": "fail",
                "duration_seconds": round(duration, 3),
                "exit_code": completed.returncode,
                "timeout_seconds": timeout,
            },
        )
        return completed.returncode or 1

    try:
        write_bundle(
            bundle,
            output_root,
            tuple(str(value) for value in spec.get("outputs", [])),
        )
    except BundleError as exc:
        bundle.unlink(missing_ok=True)
        _write_json(
            result_path,
            {
                "key": spec["key"],
                "status": "fail",
                "duration_seconds": round(duration, 3),
                "exit_code": completed.returncode,
                "timeout_seconds": timeout,
                "error": str(exc),
            },
        )
        print(f"CAD CI output error: {spec['key']}: {exc}", flush=True)
        return 1

    _write_json(
        result_path,
        {
            "key": spec["key"],
            "status": "pass",
            "duration_seconds": round(duration, 3),
            "exit_code": completed.returncode,
            "timeout_seconds": timeout,
            "bundle_sha256": bundle_sha256(bundle),
        },
    )
    print(f"CAD CI built: {spec['key']}", flush=True)
    return 0


def _materialize(target, source, env) -> int:
    """Ensure build/<item> contains the exact output stored in the bundle."""

    spec = json.loads(str(env["CAD_CI_SPEC"]))
    stamp = Path(str(target[0])).resolve()
    bundle = Path(str(source[0])).resolve()
    result_path = Path(str(spec["materialize_result"])).resolve()
    output_root = Path(str(spec["output_root"])).resolve()

    try:
        changed = materialize_bundle(
            bundle,
            output_root,
            tuple(str(value) for value in spec.get("outputs", [])),
        )
        digest = bundle_sha256(bundle)
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(digest + "\n", encoding="utf-8")
        _write_json(
            result_path,
            {
                "key": spec["key"],
                "status": "pass",
                "changed": changed,
                "bundle_sha256": digest,
            },
        )
        return 0
    except (BundleError, OSError) as exc:
        stamp.unlink(missing_ok=True)
        _write_json(
            result_path,
            {
                "key": spec["key"],
                "status": "fail",
                "changed": False,
                "error": str(exc),
            },
        )
        print(f"CAD CI materialization error: {spec['key']}: {exc}", flush=True)
        return 1


manifest_path = Path(ARGUMENTS["CAD_CI_MANIFEST"]).resolve()
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

CacheDir(str(Path(manifest["cache_root"]).resolve()))
sconsign = Path(manifest["sconsign"]).resolve()
sconsign.parent.mkdir(parents=True, exist_ok=True)
SConsignFile(str(sconsign))

specs = {str(spec["key"]): spec for spec in manifest["targets"]}
active = set(str(value) for value in manifest["active_keys"])

# Per-run observations must not survive from a previous invocation. Only active
# targets can participate in this run's result report.
for key in active:
    Path(specs[key]["execution_result"]).unlink(missing_ok=True)
    Path(specs[key]["materialize_result"]).unlink(missing_ok=True)

bundle_nodes = {}
for key, spec in specs.items():
    signature_spec = {
        field: value
        for field, value in spec.items()
        if field
        not in {
            "bundle_existed_before",
            "execution_result",
            "materialize_result",
            "materialize_stamp",
        }
    }
    spec_json = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    signature_json = json.dumps(
        signature_spec,
        sort_keys=True,
        separators=(",", ":"),
    )

    source_nodes = [str(Path(value).resolve()) for value in spec.get("sources", [])]
    node = Command(
        str(Path(spec["bundle"]).resolve()),
        source_nodes,
        _execute_bundle,
        CAD_CI_SPEC=spec_json,
    )
    Depends(node, Value(signature_json))
    if not bool(spec.get("reuse", True)):
        AlwaysBuild(node)
        NoCache(node)
    bundle_nodes[key] = node

materialize_nodes = {}
for key, spec in specs.items():
    spec_json = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    node = Command(
        str(Path(spec["materialize_stamp"]).resolve()),
        bundle_nodes[key],
        _materialize,
        CAD_CI_SPEC=spec_json,
    )
    # Materialization is cheap integrity/transport work. It must run on every
    # requested graph so a fresh runner receives files restored by CacheDir,
    # but it must never affect dependent target signatures.
    AlwaysBuild(node)
    NoCache(node)
    materialize_nodes[key] = node

for key, spec in specs.items():
    for dependency in spec.get("dependencies", []):
        dependency = str(dependency)
        Depends(bundle_nodes[key], bundle_nodes[dependency])
        Requires(bundle_nodes[key], materialize_nodes[dependency])

Default([materialize_nodes[str(key)] for key in manifest["requested_keys"]])
