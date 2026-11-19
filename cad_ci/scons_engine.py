"""Translate CAD CI items to SCons targets and report build decisions.

The public configuration stays repository-local YAML. This module converts the
loaded Item/Step objects into a small manifest consumed by scons_driver.py.

SCons is the only component that decides whether a step target is current,
dirty or restorable from CacheDir. The result report records those decisions
and output materialization without making a second rebuild decision.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from .model import Item, Step
from .paths import files_for_patterns
from .scons_bundle import bundle_sha256, outputs_match_bundle


MANIFEST_SCHEMA = 1
REPORT_SCHEMA = "cad-ci.scons-results"
REPORT_SCHEMA_VERSION = 1
OUTCOMES = ("BUILT", "CACHE_RESTORED", "CURRENT", "ERROR")
CACHE_ROOT = ".cache/cad-ci/scons-cache"
STATE_ROOT = ".cache/cad-ci/state"
WORK_ROOT = ".cache/cad-ci/work"


class SConsRunError(RuntimeError):
    """Raised when SCons or one of its consumer step actions fails."""

    def __init__(self, message: str, *, report: dict | None = None):
        super().__init__(message)
        self.report = report


def _json_digest(value: object) -> str:
    """Return a stable SHA-256 digest for JSON-compatible data."""

    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _backend_signature() -> str:
    """Hash the execution adapter so engine changes invalidate step targets."""

    digest = hashlib.sha256()
    package_root = Path(__file__).resolve().parent
    for name in ("scons_engine.py", "scons_driver.py", "scons_bundle.py"):
        path = package_root / name
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def step_key(item: Item, step: Step) -> str:
    """Return the stable internal key for one item step."""

    return f"{item.id}:{step.id}"


def _final_key(item: Item) -> str:
    """Return the key of an item's final step."""

    return step_key(item, item.steps[-1])


def _step_by_id(item: Item, step_id: str) -> Step:
    """Resolve one configured step ID or raise a clear execution error."""

    for step in item.steps:
        if step.id == step_id:
            return step
    raise SConsRunError(f"unknown step for {item.id}: {step_id}")


def requested_keys(
    items: dict[str, Item],
    selected: set[str],
    *,
    item_id: str | None = None,
    step: str | None = None,
    start: str | None = None,
    until: str | None = None,
) -> tuple[str, ...]:
    """Resolve CLI-style selection to the SCons targets that should be ensured.

    Exact step and --until select that step target. --from selects the final
    step; SCons checks/rebuilds the requested step chain as needed. There is no
    custom force-rerun layer: a previously failed/missing target is dirty, while
    a current prerequisite stays current.
    """

    partial = step is not None or start is not None or until is not None
    if partial:
        if item_id is None:
            raise SConsRunError("--step/--from/--until require --item")
        try:
            item = items[item_id]
        except KeyError as exc:
            raise SConsRunError(f"unknown item: {item_id}") from exc

        if step is not None:
            return (step_key(item, _step_by_id(item, step)),)
        if until is not None:
            return (step_key(item, _step_by_id(item, until)),)
        assert start is not None
        _step_by_id(item, start)
        return (_final_key(item),)

    if item_id is not None:
        if item_id not in items:
            raise SConsRunError(f"unknown item: {item_id}")
        return (_final_key(items[item_id]),)

    return tuple(_final_key(items[item_id]) for item_id in items if item_id in selected)


def _dependency_context(repo: Path, item: Item, items: dict[str, Item]) -> dict:
    """Describe direct dependency outputs for CAD_CI_DEPENDENCIES_JSON."""

    result: dict[str, dict[str, Any]] = {}
    for dependency_id in item.needs:
        dependency = items[dependency_id]
        outputs = sorted(
            {
                output
                for configured_step in dependency.steps
                for output in configured_step.outputs
            }
        )
        result[dependency_id] = {
            "output_root": str((repo / "build" / dependency.path).resolve()),
            "outputs": outputs,
            "bundle": str(
                (
                    repo
                    / WORK_ROOT
                    / "bundles"
                    / dependency.path
                    / f"{dependency.steps[-1].id}.tar"
                ).resolve()
            ),
        }
    return result


def target_specs(repo: Path, items: dict[str, Item]) -> list[dict[str, Any]]:
    """Translate every configured item step to one SCons bundle target."""

    repo = repo.resolve()
    backend_signature = _backend_signature()
    result: list[dict[str, Any]] = []

    for item in items.values():
        sources = [
            str(path.resolve())
            for path in files_for_patterns(repo, item.watch)
        ]
        dependency_context = _dependency_context(repo, item, items)

        for index, configured_step in enumerate(item.steps):
            key = step_key(item, configured_step)
            if index == 0:
                dependencies = [
                    _final_key(items[dependency_id])
                    for dependency_id in item.needs
                ]
            else:
                dependencies = [
                    step_key(item, item.steps[index - 1])
                ]

            bundle = (
                repo
                / WORK_ROOT
                / "bundles"
                / item.path
                / f"{configured_step.id}.tar"
            ).resolve()
            materialize_stamp = (
                repo
                / WORK_ROOT
                / "materialized"
                / item.path
                / f"{configured_step.id}.stamp"
            ).resolve()
            result_dir = (
                repo
                / STATE_ROOT
                / "results"
                / item.path
            ).resolve()

            command: str | list[str]
            shell = isinstance(configured_step.run, str)
            if shell:
                command = str(configured_step.run)
            else:
                command = list(configured_step.run)

            result.append(
                {
                    "key": key,
                    "item_id": item.id,
                    "step_id": configured_step.id,
                    "repo": str(repo),
                    "item_path": str((repo / item.path).resolve()),
                    "output_root": str(
                        (repo / "build" / item.path).resolve()
                    ),
                    "run": command,
                    "shell": shell,
                    "outputs": list(configured_step.outputs),
                    "timeout_seconds": configured_step.timeout_seconds,
                    "reuse": item.reuse,
                    "sources": sources,
                    "dependencies": dependencies,
                    "dependency_context": dependency_context,
                    "bundle": str(bundle),
                    "materialize_stamp": str(materialize_stamp),
                    "execution_result": str(
                        result_dir / f"{configured_step.id}.execution.json"
                    ),
                    "materialize_result": str(
                        result_dir / f"{configured_step.id}.materialize.json"
                    ),
                    "config": item.config_data,
                    "backend_signature": backend_signature,
                    "bundle_existed_before": bundle.is_file(),
                }
            )
    return result


def _active_keys(
    specs: dict[str, dict[str, Any]],
    requested: tuple[str, ...],
) -> tuple[str, ...]:
    """Return requested targets plus their complete SCons dependency closure."""

    active: set[str] = set()

    def visit(key: str) -> None:
        if key in active:
            return
        try:
            spec = specs[key]
        except KeyError as exc:
            raise SConsRunError(f"unknown SCons target: {key}") from exc
        for dependency in spec.get("dependencies", []):
            visit(str(dependency))
        active.add(key)

    for key in requested:
        visit(key)

    # Preserve manifest target order so reports remain stable and readable.
    return tuple(key for key in specs if key in active)


def write_manifest(
    repo: Path,
    items: dict[str, Item],
    requested: tuple[str, ...],
) -> Path:
    """Write one complete SCons manifest for the requested target graph."""

    repo = repo.resolve()
    specs_list = target_specs(repo, items)
    specs = {str(spec["key"]): spec for spec in specs_list}
    active = _active_keys(specs, requested)

    state_root = (repo / STATE_ROOT).resolve()
    state_root.mkdir(parents=True, exist_ok=True)
    manifest = state_root / "manifest.json"
    payload = {
        "schema": MANIFEST_SCHEMA,
        "repo": str(repo),
        "cache_root": str((repo / CACHE_ROOT).resolve()),
        "sconsign": str((state_root / ".sconsign.dblite").resolve()),
        "targets": specs_list,
        "requested_keys": list(requested),
        "active_keys": list(active),
    }
    manifest.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _read_result(path: str) -> dict | None:
    """Read one per-target action observation, returning None when absent."""

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _signature_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Return the exact target specification that participates in SCons Value."""

    return {
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


def write_report(repo: Path, manifest: Path) -> dict:
    """Write machine-readable outcomes for every active SCons step target."""

    repo = repo.resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    active = set(str(value) for value in payload["active_keys"])
    reports: list[dict[str, Any]] = []

    for spec in payload["targets"]:
        if spec["key"] not in active:
            continue

        action = _read_result(spec["execution_result"])
        materialized = _read_result(spec["materialize_result"])
        bundle = Path(spec["bundle"])
        bundle_exists = bundle.is_file()
        output_ok = (
            bundle_exists
            and outputs_match_bundle(
                bundle,
                Path(spec["output_root"]),
                tuple(str(value) for value in spec.get("outputs", [])),
            )
        )
        materialize_ok = (
            materialized is not None
            and materialized.get("status") == "pass"
        )

        if action is not None:
            if (
                action.get("status") == "pass"
                and bundle_exists
                and output_ok
                and materialize_ok
            ):
                outcome = "BUILT"
                reason = None
            else:
                outcome = "ERROR"
                reason = action.get("status") or action.get("error") or "action failed"
        elif bundle_exists and output_ok and materialize_ok:
            if bool(spec.get("bundle_existed_before")):
                outcome = "CURRENT"
            else:
                outcome = "CACHE_RESTORED"
            reason = None
        else:
            outcome = "ERROR"
            reason = (
                (materialized or {}).get("error")
                or "target bundle/output was not materialized"
            )

        reports.append(
            {
                "key": spec["key"],
                "item": spec["item_id"],
                "step": spec["step_id"],
                "outcome": outcome,
                "reason": reason,
                "action_executed": action is not None,
                "action_status": None if action is None else action.get("status"),
                "duration_seconds": (
                    None if action is None else action.get("duration_seconds")
                ),
                "exit_code": None if action is None else action.get("exit_code"),
                "timeout_seconds": spec.get("timeout_seconds"),
                "bundle_existed_before": bool(spec.get("bundle_existed_before")),
                "bundle_exists_after": bundle_exists,
                "bundle_sha256": (
                    bundle_sha256(bundle) if bundle_exists else None
                ),
                "outputs_materialized": bool(
                    materialized is not None
                    and materialized.get("changed", False)
                ),
                "outputs_valid": output_ok,
                "sources": list(spec.get("sources", [])),
                "target_spec_digest": _json_digest(_signature_spec(spec)),
            }
        )

    counts = Counter(row["outcome"] for row in reports)
    report = {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "manifest_schema": payload.get("schema"),
        "engine": "scons",
        "requested_keys": list(payload["requested_keys"]),
        "target_count": len(reports),
        "outcome_counts": {
            outcome: counts.get(outcome, 0)
            for outcome in OUTCOMES
        },
        "targets": reports,
    }
    report_path = repo / STATE_ROOT / "last-run.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def print_summary(report: dict) -> None:
    """Print the same concise outcome vocabulary stored in the JSON report."""

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
        print(f"  {target['outcome'].lower()}: {target['key']}")


def run_scons(
    repo: Path,
    items: dict[str, Item],
    requested: tuple[str, ...],
) -> dict:
    """Run the requested target graph through the real SCons engine."""

    repo = repo.resolve()
    if not requested:
        report = {
            "schema": REPORT_SCHEMA,
            "schema_version": REPORT_SCHEMA_VERSION,
            "manifest_schema": MANIFEST_SCHEMA,
            "engine": "scons",
            "requested_keys": [],
            "target_count": 0,
            "outcome_counts": {outcome: 0 for outcome in OUTCOMES},
            "targets": [],
        }
        state_root = repo / STATE_ROOT
        state_root.mkdir(parents=True, exist_ok=True)
        (state_root / "last-run.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report

    if shutil.which("scons") is None:
        raise SConsRunError("SCons is required but 'scons' is not installed")

    manifest = write_manifest(repo, items, requested)
    driver = Path(__file__).with_name("scons_driver.py").resolve()
    completed = subprocess.run(
        [
            "scons",
            "-Q",
            "-f",
            str(driver),
            f"CAD_CI_MANIFEST={manifest}",
        ],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="")

    report = write_report(repo, manifest)
    print_summary(report)
    if completed.returncode != 0 or report["outcome_counts"]["ERROR"]:
        raise SConsRunError(
            f"SCons run failed with exit code {completed.returncode}",
            report=report,
        )
    return report
