"""In-runtime executor for one built-in CAD builder batch.

The main runtime owns aggregate orchestration and verification. Built-in engines
that the immutable runtime intentionally isolates in another Python interpreter
are executed as one build-only child batch per engine/interpreter pair.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import traceback
from typing import Any


def _execute_source(source: Path):
    """Execute one model.py with its folder and repository importable."""

    previous_cwd = Path.cwd()
    original_path = list(sys.path)
    try:
        os.chdir(source.parent)
        sys.path.insert(0, str(source.parent))
        sys.path.insert(1, "/repo")
        namespace = runpy.run_path(str(source), run_name="__cad_ci_model__")
    finally:
        os.chdir(previous_cwd)
        sys.path[:] = original_path

    if "model" not in namespace:
        raise RuntimeError(f"{source} did not expose required global 'model'")
    return namespace["model"]


def _export(builder: str, model, output: Path) -> None:
    """Export one model using the selected generic CAD engine."""

    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)

    if builder == "build123d":
        from build123d import export_stl

        export_stl(getattr(model, "part", model), str(output))
    elif builder == "cadquery":
        from cadquery import Assembly, exporters

        # Assembly owns its STL export path. Workplane/Shape-style values can
        # also expose an export method, so callable(model.export) is not a safe
        # discriminator; those values remain on the normal exporters module.
        if isinstance(model, Assembly):
            model.export(str(output), exportType="STL")
        else:
            exporters.export(model, str(output))
    else:
        raise RuntimeError(f"unsupported built-in CAD builder: {builder}")

    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError(f"{builder} did not create non-empty STL: {output}")


def _build_row(row: dict[str, Any]) -> dict[str, Any]:
    """Execute and export one row, returning structured build evidence."""

    item_id = str(row.get("item_id", ""))
    builder = str(row.get("builder", ""))
    source = Path(str(row.get("source", "")))
    output = Path(str(row.get("output", "")))
    try:
        model = _execute_source(source)
        _export(builder, model, output)
        return {
            "item_id": item_id,
            "builder": builder,
            "status": "pass",
            "error": None,
        }
    except Exception as exc:
        error = "".join(
            traceback.format_exception_only(type(exc), exc)
        ).strip()
        print(
            f"{item_id} {builder} build: error: {error}",
            flush=True,
        )
        return {
            "item_id": item_id,
            "builder": builder,
            "status": "error",
            "error": error,
        }


def _write_report(path: Path, value: dict[str, Any]) -> None:
    """Write one deterministic runtime JSON report."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def execute_engine_batch(
    manifest_path: Path,
    report_path: Path,
    builder: str,
) -> int:
    """Build/export all rows for one isolated engine interpreter."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = manifest.get("models")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("engine batch manifest has no models")

    results: list[dict[str, Any]] = []
    failed = False
    for raw in rows:
        if not isinstance(raw, dict):
            result = {
                "item_id": "",
                "builder": builder,
                "status": "error",
                "error": "engine batch model row must be an object",
            }
        elif str(raw.get("builder", "")) != builder:
            result = {
                "item_id": str(raw.get("item_id", "")),
                "builder": str(raw.get("builder", "")),
                "status": "error",
                "error": (
                    "engine batch builder mismatch: "
                    f"expected {builder!r}, got {raw.get('builder')!r}"
                ),
            }
        else:
            result = _build_row(raw)
        failed = failed or result["status"] != "pass"
        results.append(result)

    _write_report(
        report_path,
        {
            "schema": 1,
            "builder": builder,
            "status": "fail" if failed else "pass",
            "models": results,
        },
    )
    summary = ", ".join(
        f"{row['item_id']}={row['status']}" for row in results
    )
    print(f"CAD CI {builder} engine batch: {summary}", flush=True)
    return 1 if failed else 0


def _group_error(
    rows: list[dict[str, Any]],
    message: str,
) -> dict[str, dict[str, Any]]:
    """Return one error result for every row in an isolated engine group."""

    return {
        str(row.get("item_id", "")): {
            "item_id": str(row.get("item_id", "")),
            "builder": str(row.get("builder", "")),
            "status": "error",
            "error": message,
        }
        for row in rows
    }


def _run_engine_group(
    rows: list[dict[str, Any]],
    *,
    builder: str,
    engine_python: str,
    aggregate_report: Path,
    process: Any,
) -> dict[str, dict[str, Any]]:
    """Run one isolated interpreter once for all rows in its engine group."""

    token = "".join(
        char if char.isalnum() or char in "-_" else "_"
        for char in builder
    )
    manifest_path = aggregate_report.parent / f".{token}-engine-manifest.json"
    report_path = aggregate_report.parent / f".{token}-engine-report.json"
    manifest_path.unlink(missing_ok=True)
    report_path.unlink(missing_ok=True)

    _write_report(
        manifest_path,
        {
            "schema": 1,
            "builder": builder,
            "models": rows,
        },
    )

    try:
        try:
            completed = process.run(
                [
                    engine_python,
                    str(Path(__file__).resolve()),
                    "--manifest",
                    str(manifest_path),
                    "--report",
                    str(report_path),
                    "--engine-builder",
                    builder,
                ],
                check=False,
            )
        except Exception as exc:
            error = (
                f"{builder} engine process could not start: "
                f"{type(exc).__name__}: {exc}"
            )
            return _group_error(rows, error)

        if not report_path.is_file():
            return _group_error(
                rows,
                f"{builder} engine process exited {completed.returncode} "
                "without a structured report",
            )
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return _group_error(
                rows,
                f"{builder} engine report is invalid: {exc}",
            )
        values = payload.get("models")
        if not isinstance(values, list):
            return _group_error(
                rows,
                f"{builder} engine report has no model results",
            )

        expected = {str(row.get("item_id", "")) for row in rows}
        result: dict[str, dict[str, Any]] = {}
        for value in values:
            if not isinstance(value, dict):
                continue
            item_id = str(value.get("item_id", ""))
            if item_id not in expected or item_id in result:
                continue
            status = str(value.get("status", "error"))
            if status not in {"pass", "error"}:
                status = "error"
            result[item_id] = {
                "item_id": item_id,
                "builder": str(value.get("builder", builder)),
                "status": status,
                "error": value.get("error"),
            }

        missing = expected - set(result)
        for item_id in missing:
            source = next(
                row for row in rows
                if str(row.get("item_id", "")) == item_id
            )
            result[item_id] = {
                "item_id": item_id,
                "builder": str(source.get("builder", builder)),
                "status": "error",
                "error": f"{builder} engine report omitted model result",
            }
        return result
    finally:
        manifest_path.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)


def _build_results(
    rows: list[dict[str, Any]],
    report_path: Path,
    process: Any,
) -> dict[str, dict[str, Any]]:
    """Build all rows, grouping isolated engines without per-model processes."""

    result: dict[str, dict[str, Any]] = {}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for row in rows:
        engine_python = row.get("engine_python")
        if engine_python is None:
            built = _build_row(row)
            result[built["item_id"]] = built
            continue
        if not isinstance(engine_python, str) or not engine_python.startswith("/"):
            item_id = str(row.get("item_id", ""))
            result[item_id] = {
                "item_id": item_id,
                "builder": str(row.get("builder", "")),
                "status": "error",
                "error": "engine_python must be an absolute runtime path",
            }
            continue
        key = (str(row.get("builder", "")), engine_python)
        groups.setdefault(key, []).append(row)

    for (builder, engine_python), grouped in groups.items():
        result.update(
            _run_engine_group(
                grouped,
                builder=builder,
                engine_python=engine_python,
                aggregate_report=report_path,
                process=process,
            )
        )
    return result


def _verification_result(
    row: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Run configured verification after a successful model export."""

    verification = row.get("verification")
    if verification is None:
        return None, None
    if not isinstance(verification, dict):
        raise RuntimeError(
            f"{row.get('item_id', '')}: verification manifest row "
            "must be an object"
        )

    from cad_ci.verification.runtime import run_verification

    report = run_verification(
        adapter=str(verification.get("adapter", "")),
        model_output=Path(str(row.get("output", ""))),
        definition=Path(str(verification.get("definition", ""))),
        output_dir=Path(str(verification.get("output", ""))),
        verification_id=str(verification.get("verification_id", "")),
    )
    status = str(report.get("status", "error"))
    if status not in {"pass", "fail", "error"}:
        status = "error"
    error = None
    if status != "pass":
        first = next(
            (
                check
                for check in report.get("checks", ())
                if isinstance(check, dict)
                and check.get("status") in {"fail", "error"}
            ),
            None,
        )
        if first is not None:
            error = str(first.get("error") or "") or None
    return status, error


def execute_manifest(
    manifest_path: Path,
    report_path: Path,
    *,
    process: Any | None = None,
) -> int:
    """Build all rows in engine batches, then verify successful exports."""

    from cad_ci.execution.process import DEFAULT_PROCESS_RUNNER

    runner = DEFAULT_PROCESS_RUNNER if process is None else process
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_rows = manifest.get("models")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise RuntimeError("built-in CAD batch manifest has no models")
    if not all(isinstance(row, dict) for row in raw_rows):
        raise RuntimeError("built-in CAD batch manifest model rows must be objects")
    rows: list[dict[str, Any]] = list(raw_rows)

    built = _build_results(rows, report_path, runner)
    results: list[dict[str, Any]] = []
    failed = False

    for row in rows:
        item_id = str(row.get("item_id", ""))
        builder = str(row.get("builder", ""))
        build = built.get(
            item_id,
            {
                "status": "error",
                "error": "runtime produced no build result",
            },
        )
        build_status = str(build.get("status", "error"))
        verification_status = None
        status = "pass" if build_status == "pass" else "error"
        error = build.get("error")

        if build_status == "pass":
            try:
                verification_status, verification_error = (
                    _verification_result(row)
                )
                if verification_status is not None:
                    status = verification_status
                    error = verification_error
            except Exception as exc:
                verification_status = "error"
                status = "error"
                error = "".join(
                    traceback.format_exception_only(type(exc), exc)
                ).strip()
                print(
                    f"{item_id} {builder} verification: error: {error}",
                    flush=True,
                )

        failed = failed or status != "pass"
        results.append(
            {
                "item_id": item_id,
                "builder": builder,
                "build_status": build_status,
                "verification_status": verification_status,
                "status": status,
                "error": error,
            }
        )

    _write_report(
        report_path,
        {
            "schema": 1,
            "runtime": manifest.get("runtime"),
            "batch_contract": manifest.get("batch_contract"),
            "status": "fail" if failed else "pass",
            "models": results,
        },
    )
    summary = ", ".join(
        f"{row['item_id']}={row['status']}" for row in results
    )
    print(f"CAD CI built-in batch: {summary}", flush=True)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch main runtime orchestration or isolated engine-build mode."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--engine-builder")
    args = parser.parse_args(argv)
    if args.engine_builder:
        return execute_engine_batch(
            args.manifest,
            args.report,
            args.engine_builder,
        )
    return execute_manifest(args.manifest, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
