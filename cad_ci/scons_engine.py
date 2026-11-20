"""Translate CAD CI configuration into the specified SCons target graph.

SCons is the only rebuild/cache engine. This module owns target specification,
request selection, post-run materialization and public evidence. Evidence is an
observation of the SCons run and never feeds back into target freshness.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from .model import Item, Step
from .paths import PathDiscoveryError, files_for_patterns
from .scons_bundle import (
    BundleError,
    bundle_sha256,
    materialize_bundle,
    read_bundle_manifest,
)
from .timing import utc_now


ENGINE_SCHEMA = 1
MANIFEST_SCHEMA = 1
REPORT_SCHEMA = "cad-ci.scons-results"
REPORT_SCHEMA_VERSION = 3
OUTCOMES = ("BUILT", "CACHE_RESTORED", "CURRENT", "ERROR")

CACHE_ROOT = Path(".cache/cad-ci/scons/cache")
STATE_ROOT = Path(".cache/cad-ci/scons/state")
TARGET_ROOT = Path(".cache/cad-ci/scons/targets")
RUN_ROOT = Path(".cache/cad-ci/scons/run")
MANIFEST_PATH = RUN_ROOT / "manifest.json"
REPORT_PATH = RUN_ROOT / "result.json"


class SConsRunError(RuntimeError):
    """Raised when target selection, SCons execution or materialization fails."""

    def __init__(self, message: str, *, report: dict | None = None):
        super().__init__(message)
        self.report = report


@dataclass(frozen=True)
class RunRequest:
    """Top-level SCons targets plus targets explicitly forced by the operator."""

    requested_keys: tuple[str, ...]
    force_keys: frozenset[str]


def _json_digest(value: object) -> str:
    """Return a stable SHA-256 digest for JSON-compatible evidence."""

    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def step_key(item: Item, step: Step) -> str:
    """Return the stable logical key for one configured step."""

    return f"{item.id}:{step.id}"


def final_key(item: Item) -> str:
    """Return the logical key of one item's final step."""

    return step_key(item, item.steps[-1])


def _step_index(item: Item, step_id: str) -> int:
    """Resolve a step ID to its configured index."""

    for index, step in enumerate(item.steps):
        if step.id == step_id:
            return index
    raise SConsRunError(f"unknown step for {item.id}: {step_id}")


def resolve_request(
    items: dict[str, Item],
    selected: set[str],
    *,
    item_id: str | None = None,
    step: str | None = None,
    start: str | None = None,
    until: str | None = None,
) -> RunRequest:
    """Resolve public run selectors to requested and explicitly forced targets."""

    selectors = [value for value in (step, start, until) if value is not None]
    if len(selectors) > 1:
        raise SConsRunError("--step, --from and --until are mutually exclusive")
    if selectors and item_id is None:
        raise SConsRunError("--step/--from/--until require --item")

    if item_id is not None:
        try:
            item = items[item_id]
        except KeyError as exc:
            raise SConsRunError(f"unknown item: {item_id}") from exc

        if not item.process:
            raise SConsRunError(f"item is not processed: {item_id}")

        if step is not None:
            index = _step_index(item, step)
            key = step_key(item, item.steps[index])
            return RunRequest((key,), frozenset({key}))

        if until is not None:
            index = _step_index(item, until)
            return RunRequest(
                (step_key(item, item.steps[index]),),
                frozenset(),
            )

        if start is not None:
            index = _step_index(item, start)
            forced = frozenset(
                step_key(item, configured_step)
                for configured_step in item.steps[index:]
            )
            return RunRequest((final_key(item),), forced)

        return RunRequest((final_key(item),), frozenset())

    excluded = sorted(
        item_id_value
        for item_id_value in selected
        if item_id_value in items and not items[item_id_value].process
    )
    if excluded:
        raise SConsRunError(
            "item is not processed: " + ", ".join(excluded)
        )

    requested = tuple(
        final_key(item)
        for item_id_value, item in items.items()
        if item_id_value in selected and item.process
    )
    return RunRequest(requested, frozenset())


def requested_keys(
    items: dict[str, Item],
    selected: set[str],
    **kwargs: Any,
) -> tuple[str, ...]:
    """Compatibility helper returning only top-level target keys."""

    return resolve_request(items, selected, **kwargs).requested_keys


def _effective_inputs(item: Item, step: Step) -> tuple[str, ...]:
    """Return explicit step inputs or the item's coarse watch paths."""

    return item.watch if step.inputs is None else step.inputs


def _resolved_inputs(repo: Path, item: Item, step: Step) -> tuple[str, ...]:
    """Resolve stable source paths for one step target."""

    config_relative = tuple(
        path.as_posix()
        for path in (
            item.config_paths
            if item.config_paths
            else (item.config_path.relative_to(repo),)
        )
    )
    try:
        files = files_for_patterns(
            repo,
            _effective_inputs(item, step),
            exclude=config_relative,
        )
    except PathDiscoveryError as exc:
        raise SConsRunError(str(exc)) from exc
    return tuple(path.relative_to(repo).as_posix() for path in files)


def _bundle_path(item: Item, step: Step) -> str:
    """Return the private repository-relative target-bundle path."""

    return (
        TARGET_ROOT / item.path / f"{step.id}.tar"
    ).as_posix()


def _action_result_path(item: Item, step: Step) -> str:
    """Return the private per-run action observation path."""

    return (
        RUN_ROOT / "actions" / item.path / f"{step.id}.json"
    ).as_posix()


def _dependency_descriptor(
    dependency: Item,
) -> dict[str, Any]:
    """Describe one direct item dependency without workspace-specific paths."""

    return {
        "item_id": dependency.id,
        "item_path": dependency.path.as_posix(),
        "step_keys": [
            step_key(dependency, configured_step)
            for configured_step in dependency.steps
        ],
        "final_key": final_key(dependency),
        "outputs": sorted(
            output
            for configured_step in dependency.steps
            for output in configured_step.outputs
        ),
    }


def target_specs(
    repo: Path,
    items: dict[str, Item],
) -> list[dict[str, Any]]:
    """Translate every configured step to one stable SCons target specification."""

    repo = repo.resolve()
    specs: list[dict[str, Any]] = []

    for item in items.values():
        if not item.process:
            continue
        direct_dependencies = [
            _dependency_descriptor(items[dependency_id])
            for dependency_id in item.needs
        ]
        cumulative_outputs: list[str] = []

        for index, configured_step in enumerate(item.steps):
            key = step_key(item, configured_step)
            resolved_inputs = _resolved_inputs(repo, item, configured_step)
            cumulative_outputs.extend(configured_step.outputs)

            if index == 0:
                dependencies = [
                    final_key(items[dependency_id])
                    for dependency_id in item.needs
                ]
                materialize_before = list(dependencies)
            else:
                previous = step_key(item, item.steps[index - 1])
                dependencies = [previous]
                materialize_before = [previous]
                # Direct dependency output must also be available to every step
                # because current_context() is valid throughout the item flow.
                materialize_before.extend(
                    final_key(items[dependency_id])
                    for dependency_id in item.needs
                )

            materialize_before = list(dict.fromkeys(materialize_before))

            command: str | list[str]
            shell = isinstance(configured_step.run, str)
            command = (
                str(configured_step.run)
                if shell
                else list(configured_step.run)
            )

            signature = {
                "schema": 1,
                "engine_schema": ENGINE_SCHEMA,
                "item_id": item.id,
                "item_path": item.path.as_posix(),
                "step_id": configured_step.id,
                "run": command,
                "shell": shell,
                "outputs": list(configured_step.outputs),
                "bundle_outputs": list(cumulative_outputs),
                "timeout_seconds": configured_step.timeout_seconds,
                "reuse": item.reuse,
                "variables": dict(item.variables),
                "resolved_inputs": list(resolved_inputs),
                "needs": list(item.needs),
            }

            bundle_rel = _bundle_path(item, configured_step)
            bundle = repo / bundle_rel
            specs.append(
                {
                    "key": key,
                    "item_id": item.id,
                    "item_path": item.path.as_posix(),
                    "step_id": configured_step.id,
                    "run": command,
                    "shell": shell,
                    "outputs": list(configured_step.outputs),
                    "bundle_outputs": list(cumulative_outputs),
                    "timeout_seconds": configured_step.timeout_seconds,
                    "reuse": item.reuse,
                    "variables": dict(item.variables),
                    "sources": list(resolved_inputs),
                    "dependencies": dependencies,
                    "materialize_before": materialize_before,
                    "direct_dependencies": direct_dependencies,
                    "bundle": bundle_rel,
                    "action_result": _action_result_path(
                        item,
                        configured_step,
                    ),
                    "signature": signature,
                    "target_spec_digest": _json_digest(signature),
                    "bundle_existed_before": bundle.is_file(),
                    "bundle_sha_before": (
                        bundle_sha256(bundle)
                        if bundle.is_file()
                        else None
                    ),
                }
            )

    return specs


def _active_keys(
    specs: dict[str, dict[str, Any]],
    requested: tuple[str, ...],
) -> tuple[str, ...]:
    """Return requested targets plus the dependency closure, in manifest order."""

    active: set[str] = set()

    def visit(key: str) -> None:
        if key in active:
            return
        try:
            spec = specs[key]
        except KeyError as exc:
            raise SConsRunError(f"unknown SCons target: {key}") from exc
        for dependency in spec["dependencies"]:
            visit(str(dependency))
        active.add(key)

    for key in requested:
        visit(key)

    return tuple(key for key in specs if key in active)


def write_manifest(
    repo: Path,
    items: dict[str, Item],
    request: RunRequest,
) -> Path:
    """Write the private manifest consumed by the SCons driver."""

    repo = repo.resolve()
    specs_list = target_specs(repo, items)
    specs = {str(spec["key"]): spec for spec in specs_list}
    active = _active_keys(specs, request.requested_keys)

    payload = {
        "schema": MANIFEST_SCHEMA,
        "engine_schema": ENGINE_SCHEMA,
        "cache_root": CACHE_ROOT.as_posix(),
        "sconsign": (STATE_ROOT / ".sconsign.dblite").as_posix(),
        "targets": specs_list,
        "requested_keys": list(request.requested_keys),
        "force_keys": sorted(request.force_keys),
        "active_keys": list(active),
    }

    path = repo / MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read one JSON object, returning None for missing/invalid observations."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _valid_bundle(bundle: Path) -> bool:
    """Return whether a target bundle exists and has a supported manifest."""

    try:
        read_bundle_manifest(bundle)
    except BundleError:
        return False
    return True


def _scons_outcome(
    repo: Path,
    spec: dict[str, Any],
) -> tuple[str, dict[str, Any] | None, str | None]:
    """Classify one target using explicit action records and target state."""

    action = _read_json(repo / spec["action_result"])
    bundle = repo / spec["bundle"]
    if action is not None and action.get("status") != "pass":
        return "ERROR", action, str(
            action.get("error")
            or action.get("status")
            or "action failed"
        )

    if not _valid_bundle(bundle):
        return "ERROR", action, "target bundle is missing or invalid"

    if action is not None:
        return "BUILT", action, None

    digest_after = bundle_sha256(bundle)
    if (
        not bool(spec["bundle_existed_before"])
        or spec.get("bundle_sha_before") != digest_after
    ):
        return "CACHE_RESTORED", None, None
    return "CURRENT", None, None


def _materialize_active(
    repo: Path,
    specs_list: list[dict[str, Any]],
    active: set[str],
    outcomes: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Materialize valid active bundles in graph/config order."""

    result: dict[str, dict[str, Any]] = {}
    for spec in specs_list:
        key = str(spec["key"])
        if key not in active:
            continue
        if outcomes[key] == "ERROR":
            result[key] = {
                "result": "ERROR",
                "error": "no valid target bundle",
            }
            continue

        try:
            materialization = materialize_bundle(
                repo / spec["bundle"],
                repo / "build" / Path(spec["item_path"]),
                tuple(str(value) for value in spec["bundle_outputs"]),
            )
            result[key] = {
                "result": materialization,
                "error": None,
            }
        except (BundleError, OSError) as exc:
            result[key] = {
                "result": "ERROR",
                "error": str(exc),
            }
    return result


def write_report(
    repo: Path,
    manifest: Path,
    *,
    run_started_at: str,
) -> dict[str, Any]:
    """Materialize active output and write one machine-readable run report."""

    repo = repo.resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    specs_list = list(payload["targets"])
    active = set(str(value) for value in payload["active_keys"])

    outcomes: dict[str, str] = {}
    actions: dict[str, dict[str, Any] | None] = {}
    outcome_errors: dict[str, str | None] = {}
    for spec in specs_list:
        key = str(spec["key"])
        if key not in active:
            continue
        outcome, action, error = _scons_outcome(repo, spec)
        outcomes[key] = outcome
        actions[key] = action
        outcome_errors[key] = error

    materialized = _materialize_active(
        repo,
        specs_list,
        active,
        outcomes,
    )

    rows: list[dict[str, Any]] = []
    for spec in specs_list:
        key = str(spec["key"])
        if key not in active:
            continue

        action = actions[key]
        outcome = outcomes[key]
        materialization = materialized[key]["result"]

        if outcome == "ERROR":
            status = (
                str(action.get("status"))
                if action is not None and action.get("status")
                else "fail"
            )
        elif materialization == "ERROR":
            status = "output_restore_error"
        else:
            status = "pass"

        bundle = repo / spec["bundle"]
        bundle_digest = (
            bundle_sha256(bundle)
            if _valid_bundle(bundle)
            else None
        )
        output_manifest: dict[str, Any] = {}
        if bundle_digest is not None:
            bundle_outputs = read_bundle_manifest(bundle).get("outputs", {})
            output_manifest = {
                name: bundle_outputs[name]
                for name in spec["outputs"]
                if name in bundle_outputs
            }

        rows.append(
            {
                "key": key,
                "item": spec["item_id"],
                "item_path": spec["item_path"],
                "step": spec["step_id"],
                "status": status,
                "outcome": outcome,
                "output_state": materialization,
                "error": (
                    outcome_errors[key]
                    or materialized[key].get("error")
                ),
                "action_executed": (
                    False
                    if action is None
                    else bool(action.get("action_executed", True))
                ),
                "action_status": (
                    None if action is None else action.get("status")
                ),
                "started_at": (
                    None if action is None else action.get("started_at")
                ),
                "finished_at": (
                    None if action is None else action.get("finished_at")
                ),
                "duration_seconds": (
                    None if action is None else action.get("duration_seconds")
                ),
                "exit_code": (
                    None if action is None else action.get("exit_code")
                ),
                "timeout_seconds": spec["timeout_seconds"],
                "target_spec_digest": spec["target_spec_digest"],
                "bundle": spec["bundle"],
                "bundle_sha256": bundle_digest,
                "outputs": output_manifest,
                "sources": list(spec["sources"]),
            }
        )

    counts = Counter(row["outcome"] for row in rows)
    run_finished_at = utc_now()
    report = {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "engine": "scons",
        "engine_schema": ENGINE_SCHEMA,
        "started_at": run_started_at,
        "finished_at": run_finished_at,
        "requested_keys": list(payload["requested_keys"]),
        "force_keys": list(payload["force_keys"]),
        "target_count": len(rows),
        "outcome_counts": {
            outcome: counts.get(outcome, 0)
            for outcome in OUTCOMES
        },
        "targets": rows,
    }

    report_path = repo / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Write stable human-readable public evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_public_evidence(
    repo: Path,
    items: dict[str, Item],
    report: dict[str, Any],
) -> None:
    """Write publishable evidence without creating a second freshness engine."""

    repo = repo.resolve()
    rows = {str(row["key"]): row for row in report["targets"]}
    active_items = {
        str(row["item"])
        for row in report["targets"]
    }

    for row in report["targets"]:
        item = items[str(row["item"])]
        evidence = (
            repo
            / "build"
            / item.path
            / ".cad-ci"
            / "steps"
            / f"{row['step']}.json"
        )
        _write_json(
            evidence,
            {
                "schema": 3,
                "engine": "scons",
                "engine_schema": ENGINE_SCHEMA,
                "item": row["item"],
                "step": row["step"],
                "status": row["status"],
                "outcome": row["outcome"],
                "output_state": row["output_state"],
                "error": row["error"],
                "action_executed": row["action_executed"],
                "run_started_at": report["started_at"],
                "run_finished_at": report["finished_at"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "duration_seconds": row["duration_seconds"],
                "exit_code": row["exit_code"],
                "timeout_seconds": row["timeout_seconds"],
                "target_spec_digest": row["target_spec_digest"],
                "bundle_sha256": row["bundle_sha256"],
                "outputs": row["outputs"],
            },
        )

    for item_id in active_items:
        item = items[item_id]
        item_evidence = (
            repo / "build" / item.path / ".cad-ci" / "item.json"
        )
        final = rows.get(final_key(item))
        item_rows = [
            row
            for row in report["targets"]
            if row["item"] == item_id
        ]
        if (
            final is None
            or final["status"] != "pass"
            or any(row["status"] != "pass" for row in item_rows)
        ):
            item_evidence.unlink(missing_ok=True)
            continue

        _write_json(
            item_evidence,
            {
                "schema": 2,
                "engine": "scons",
                "engine_schema": ENGINE_SCHEMA,
                "item": item.id,
                "status": "pass",
                "run_started_at": report["started_at"],
                "run_finished_at": report["finished_at"],
                "final_step": item.steps[-1].id,
                "final_target_spec_digest": final["target_spec_digest"],
                "final_bundle_sha256": final["bundle_sha256"],
            },
        )


def print_summary(report: dict[str, Any]) -> None:
    """Print concise target decisions from the structured report."""

    counts = report["outcome_counts"]
    print(
        "SCons: "
        f"targets={report['target_count']} "
        f"built={counts['BUILT']} "
        f"cache-restored={counts['CACHE_RESTORED']} "
        f"current={counts['CURRENT']} "
        f"error={counts['ERROR']}"
    )
    for target in report["targets"]:
        print(
            f"  {target['outcome'].lower()}: {target['key']} "
            f"output={target['output_state'].lower()}"
        )


def _empty_report(
    run_started_at: str,
    run_finished_at: str,
) -> dict[str, Any]:
    """Return the standard no-target run report."""

    return {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "engine": "scons",
        "engine_schema": ENGINE_SCHEMA,
        "started_at": run_started_at,
        "finished_at": run_finished_at,
        "requested_keys": [],
        "force_keys": [],
        "target_count": 0,
        "outcome_counts": {outcome: 0 for outcome in OUTCOMES},
        "targets": [],
    }


def run_scons(
    repo: Path,
    items: dict[str, Item],
    request: RunRequest | tuple[str, ...],
) -> dict[str, Any]:
    """Run one selected graph through SCons and produce output/evidence."""

    repo = repo.resolve()
    run_started_at = utc_now()
    if isinstance(request, tuple):
        request = RunRequest(request, frozenset())

    if not request.requested_keys:
        report = _empty_report(run_started_at, utc_now())
        path = repo / REPORT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report

    if shutil.which("scons") is None:
        raise SConsRunError("SCons is required but 'scons' is not installed")

    manifest = write_manifest(repo, items, request)
    driver = Path(__file__).with_name("scons_driver.py").resolve()
    completed = subprocess.run(
        [
            "scons",
            "-Q",
            "-f",
            str(driver),
            f"CAD_CI_MANIFEST={MANIFEST_PATH.as_posix()}",
        ],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="")

    report = write_report(
        repo,
        manifest,
        run_started_at=run_started_at,
    )
    write_public_evidence(repo, items, report)
    print_summary(report)

    failed = any(
        row["status"] != "pass"
        for row in report["targets"]
    )
    if completed.returncode != 0 or failed:
        raise SConsRunError(
            f"SCons run failed with exit code {completed.returncode}",
            report=report,
        )
    return report
