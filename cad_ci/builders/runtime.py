"""In-runtime executor for one built-in CAD builder batch.

This file intentionally uses only the standard library plus the CAD engines
provided by the runtime image. The host mounts this module read-only into the
single shared runtime container.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import traceback


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
        from cadquery import exporters
        exporters.export(model, str(output))
    else:
        raise RuntimeError(f"unsupported built-in CAD builder: {builder}")

    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError(f"{builder} did not create non-empty STL: {output}")


def execute_manifest(manifest_path: Path, report_path: Path) -> int:
    """Execute every case sequentially and retain per-model failure evidence."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = manifest.get("models")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("built-in CAD batch manifest has no models")

    results = []
    failed = False
    for row in rows:
        item_id = str(row.get("item_id", ""))
        builder = str(row.get("builder", ""))
        source = Path(str(row.get("source", "")))
        output = Path(str(row.get("output", "")))
        build_status = "error"
        verification_status = None
        status = "error"
        error = None
        try:
            model = _execute_source(source)
            _export(builder, model, output)
            build_status = "pass"
            status = "pass"

            verification = row.get("verification")
            if verification is not None:
                if not isinstance(verification, dict):
                    raise RuntimeError(
                        f"{item_id}: verification manifest row must be an object"
                    )
                from cad_ci.verification.runtime import run_verification

                report = run_verification(
                    adapter=str(verification.get("adapter", "")),
                    model_output=output,
                    definition=Path(
                        str(verification.get("definition", ""))
                    ),
                    output_dir=Path(
                        str(verification.get("output", ""))
                    ),
                    verification_id=str(
                        verification.get("verification_id", "")
                    ),
                )
                verification_status = str(report.get("status", "error"))
                if verification_status not in {"pass", "fail", "error"}:
                    verification_status = "error"
                if verification_status != "pass":
                    failed = True
                    status = verification_status
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
        except Exception as exc:
            failed = True
            status = "error"
            if build_status == "pass" and verification_status is None:
                verification_status = "error"
            error = "".join(
                traceback.format_exception_only(type(exc), exc)
            ).strip()
            print(
                f"{item_id} {builder} runtime: error: {error}",
                flush=True,
            )

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

    report_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "runtime": manifest.get("runtime"),
                "batch_contract": manifest.get("batch_contract"),
                "status": "fail" if failed else "pass",
                "models": results,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    summary = ", ".join(
        f"{row['item_id']}={row['status']}" for row in results
    )
    print(f"CAD CI built-in batch: {summary}", flush=True)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    return execute_manifest(args.manifest, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
