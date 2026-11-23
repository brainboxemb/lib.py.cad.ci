"""Acceptance tests for reusable built-in CAD builder batches."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from cad_ci.builders.catalog import runtime_catalog_signature
from cad_ci.builders.batch import run_batch
from cad_ci.builders.runtime import execute_manifest
from cad_ci.config import ConfigError, load_repository
from cad_ci.execution.process import ProcessResult
from cad_ci.scons.engine import resolve_request, write_manifest


def _write(path: Path, text: str) -> None:
    """Write one minimal fixture file while creating its parent directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class RecordingProcessRunner:
    """Fake the owned process boundary and retain commands for assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path | None, bool]] = []

    def run(self, command, *, cwd=None, check=False):
        """Record one external-process request without starting a process."""

        self.calls.append((list(command), cwd, check))
        return ProcessResult(returncode=0)


class EngineBatchProcessRunner:
    """Simulate one isolated engine batch and write its structured result."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, command, *, cwd=None, check=False):
        """Materialize every requested STL and one engine report."""

        argv = list(command)
        self.calls.append(argv)
        manifest = Path(argv[argv.index("--manifest") + 1])
        report = Path(argv[argv.index("--report") + 1])
        data = json.loads(manifest.read_text(encoding="utf-8"))
        results = []
        for row in data["models"]:
            output = Path(row["output"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("isolated-build123d\n", encoding="utf-8")
            results.append(
                {
                    "item_id": row["item_id"],
                    "builder": row["builder"],
                    "status": "pass",
                    "error": None,
                }
            )
        report.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "builder": "build123d",
                    "status": "pass",
                    "models": results,
                }
            ),
            encoding="utf-8",
        )
        return ProcessResult(returncode=0)


class BuiltinBuilderConfigTests(unittest.TestCase):
    """Conformance tests for built-in builder lowering and configuration."""

    def make_repo(self, root: Path) -> None:
        """Create three model items sharing the reference runtime group."""

        _write(
            root / "cad-ci.yml",
            "schema: 1\n"
            "runtimes:\n"
            "  reference: ghcr.io/example/cad-reference:v1.2.3\n"
            "items: [models/*]\n",
        )
        for item_id, builder in (
            ("a", "build123d"),
            ("b", "build123d"),
            ("c", "cadquery"),
        ):
            _write(
                root / "models" / item_id / "ci.yml",
                f"id: {item_id}\n"
                f"builder: {builder}\n",
            )
            _write(
                root / "models" / item_id / "model.py",
                "model = object()\n",
            )

    def test_models_lower_to_one_shared_runtime_producer(self):
        """Built-in model config lowers to one shared producer + projections."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_repo(root)

            items = load_repository(root)
            self.assertEqual(
                set(items),
                {"a", "b", "c", "cad-ci-runtime-reference"},
            )

            for item_id, builder in (
                ("a", "build123d"),
                ("b", "build123d"),
                ("c", "cadquery"),
            ):
                item = items[item_id]
                self.assertEqual(item.builder, builder)
                self.assertIsNone(item.builder_path)
                self.assertEqual(item.runtime_role, "reference")
                self.assertEqual(
                    item.runtime_image,
                    "ghcr.io/example/cad-reference:v1.2.3",
                )
                self.assertIn("cad-ci-runtime-reference", item.needs)
                self.assertEqual(len(item.steps), 1)
                step = item.steps[0]
                self.assertIsNone(step.run)
                self.assertEqual(
                    step.copy.dependency,
                    "cad-ci-runtime-reference",
                )
                self.assertEqual(
                    step.copy.source,
                    f"items/models/{item_id}",
                )
                self.assertEqual(step.outputs, ("model.stl",))

            producer = items["cad-ci-runtime-reference"]
            self.assertTrue(producer.internal)
            self.assertEqual(producer.runtime_role, "reference")
            self.assertEqual(
                producer.runtime_image,
                "ghcr.io/example/cad-reference:v1.2.3",
            )
            self.assertEqual(producer.steps[0].selection_context, "direct_dependents")
            self.assertEqual(
                producer.steps[0].outputs,
                ("items", "batch-manifest.json", "batch-report.json"),
            )

    def test_active_models_feed_signature_safe_shared_batch_context(self):
        """Acceptance Case 32: active dependents define shared-batch identity."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_repo(root)
            items = load_repository(root)

            request = resolve_request(items, {"a", "c"})
            manifest_path = write_manifest(root, items, request)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            specs = {row["key"]: row for row in manifest["targets"]}

            producer = specs["cad-ci-runtime-reference:build"]
            self.assertEqual(producer["active_dependents"], ["a", "c"])
            self.assertEqual(producer["runtime"], "reference")
            self.assertEqual(
                producer["runtime_image"],
                "ghcr.io/example/cad-reference:v1.2.3",
            )
            self.assertEqual(
                producer["signature"]["active_dependents"],
                ["a", "c"],
            )
            self.assertEqual(specs["a:build"]["action_type"], "copy")
            self.assertEqual(specs["c:build"]["action_type"], "copy")
            self.assertEqual(
                specs["a:build"]["dependencies"],
                ["cad-ci-runtime-reference:build"],
            )

    def test_builtin_names_are_reserved_for_library_owned_builders(self):
        """Consumer aliases must never shadow library-owned built-in names."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "cad-ci.yml",
                "schema: 1\n"
                "builders: {build123d: ci/builders/local}\n"
                "items: [a]\n",
            )
            _write(
                root / "a" / "ci.yml",
                "id: a\nsteps: [{id: x, run: [python, -c, 'print(1)']}]\n",
            )
            with self.assertRaisesRegex(ConfigError, "reserved"):
                load_repository(root)

    def test_all_disabled_builtin_models_disable_internal_producer(self):
        """The internal batch stays inactive when all consumers are disabled."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "cad-ci.yml",
                "schema: 1\n"
                "runtimes: {reference: ghcr.io/example/cad-reference:v1}\n"
                "items: [a]\n",
            )
            _write(
                root / "a" / "ci.yml",
                "id: a\nprocess: false\nbuilder: build123d\n",
            )
            _write(root / "a" / "model.py", "model = object()\n")

            items = load_repository(root)
            producer = items["cad-ci-runtime-reference"]
            self.assertFalse(producer.process)
            self.assertEqual(producer.steps[0].inputs, ())

    def test_builtin_requires_runtime_and_model_source(self):
        """Invalid built-in runtime/source contracts fail during config load."""

        cases = (
            (
                "schema: 1\nitems: [a]\n",
                True,
                "requires runtime role",
            ),
            (
                "schema: 1\n"
                "runtimes: {reference: ghcr.io/example/cad-reference:v1}\n"
                "items: [a]\n",
                False,
                "requires regular item-local model.py",
            ),
            (
                "schema: 1\n"
                "runtimes: {reference: ghcr.io/example/cad-reference:latest}\n"
                "items: [a]\n",
                True,
                "non-latest",
            ),
        )
        for root_yaml, write_model, expected in cases:
            with self.subTest(expected=expected):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    _write(root / "cad-ci.yml", root_yaml)
                    _write(root / "a" / "ci.yml", "id: a\nbuilder: build123d\n")
                    if write_model:
                        _write(root / "a" / "model.py", "model = object()\n")
                    with self.assertRaisesRegex(ConfigError, expected):
                        load_repository(root)


class BuiltinBuilderBatchTests(unittest.TestCase):
    """Unit/conformance tests for one shared built-in runtime batch."""

    def make_repo(self, root: Path) -> None:
        """Create build123d and CadQuery consumers sharing one runtime batch."""

        _write(
            root / "cad-ci.yml",
            "schema: 1\n"
            "runtimes: {reference: ghcr.io/example/cad-reference:v1.2.3}\n"
            "items: [a, b]\n",
        )
        for item_id, builder in (("a", "build123d"), ("b", "cadquery")):
            _write(
                root / item_id / "ci.yml",
                f"id: {item_id}\nbuilder: {builder}\n",
            )
            _write(root / item_id / "model.py", "model = object()\n")

    def test_host_collects_compatible_builders_into_one_container_run(self):
        """Compatible active engines result in exactly one runtime start."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_repo(root)
            output = root / "build" / ".cad-ci-runtime" / "reference"
            env = {
                "CAD_CI_REPO": str(root),
                "CAD_CI_OUTPUT": str(output),
                "CAD_CI_RUNTIME": "reference",
                "CAD_CI_RUNTIME_IMAGE": "ghcr.io/example/cad-reference:v1.2.3",
                "CAD_CI_ACTIVE_DEPENDENTS_JSON": '["a","b"]',
            }

            # Runtime-start cardinality is the performance contract here;
            # Docker itself belongs to outer released-stack acceptance.
            process = RecordingProcessRunner()
            self.assertEqual(
                run_batch(
                    "reference",
                    3,
                    runtime_catalog_signature("reference"),
                    environ=env,
                    process=process,
                ),
                0,
            )

            docker_runs = [
                command
                for command, _cwd, _check in process.calls
                if len(command) >= 2 and command[:2] == ["docker", "run"]
            ]
            self.assertEqual(len(docker_runs), 1)
            command = docker_runs[0]
            user_index = command.index("--user")
            self.assertEqual(
                command[user_index + 1],
                f"{os.getuid()}:{os.getgid()}",
            )
            self.assertIn("HOME=/tmp", command)

            manifest = json.loads(
                (output / "batch-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                [
                    (row["item_id"], row["builder"])
                    for row in manifest["models"]
                ],
                [("a", "build123d"), ("b", "cadquery")],
            )
            self.assertEqual(
                [
                    row.get("engine_python")
                    for row in manifest["models"]
                ],
                ["/opt/build123d/bin/python", None],
            )

    def test_isolated_build123d_rows_share_one_engine_process(self):
        """N build123d rows use one runtime-owned interpreter process."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            for item_id in ("a", "b"):
                source = root / item_id / "model.py"
                output = root / "out" / item_id / "model.stl"
                _write(source, "model = object()\n")
                rows.append(
                    {
                        "item_id": item_id,
                        "builder": "build123d",
                        "engine_python": "/opt/build123d/bin/python",
                        "source": str(source),
                        "output": str(output),
                    }
                )

            cad_source = root / "c" / "model.py"
            cad_output = root / "out" / "c" / "model.stl"
            _write(cad_source, "model = object()\n")
            rows.append(
                {
                    "item_id": "c",
                    "builder": "cadquery",
                    "engine_python": None,
                    "source": str(cad_source),
                    "output": str(cad_output),
                }
            )

            manifest = root / "manifest.json"
            report = root / "report.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "runtime": "reference",
                        "batch_contract": 3,
                        "models": rows,
                    }
                ),
                encoding="utf-8",
            )

            cadquery = types.ModuleType("cadquery")
            cadquery.exporters = types.SimpleNamespace(
                export=lambda model, path: Path(path).write_text(
                    "cadquery\n",
                    encoding="utf-8",
                )
            )
            process = EngineBatchProcessRunner()
            with patch.dict(sys.modules, {"cadquery": cadquery}):
                self.assertEqual(
                    execute_manifest(
                        manifest,
                        report,
                        process=process,
                    ),
                    0,
                )

            self.assertEqual(len(process.calls), 1)
            self.assertEqual(
                process.calls[0][0],
                "/opt/build123d/bin/python",
            )
            self.assertEqual(
                process.calls[0][-2:],
                ["--engine-builder", "build123d"],
            )
            self.assertEqual(
                (root / "out/a/model.stl").read_text(encoding="utf-8"),
                "isolated-build123d\n",
            )
            self.assertEqual(
                (root / "out/b/model.stl").read_text(encoding="utf-8"),
                "isolated-build123d\n",
            )
            self.assertEqual(cad_output.read_text(encoding="utf-8"), "cadquery\n")
            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(
                [row["status"] for row in result["models"]],
                ["pass", "pass", "pass"],
            )

    def test_runtime_executes_all_models_and_writes_per_model_results(self):
        """One runtime process executes and reports every manifest model."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_a = root / "a" / "model.py"
            source_b = root / "b" / "model.py"
            output_a = root / "out" / "a" / "model.stl"
            output_b = root / "out" / "b" / "model.stl"
            _write(source_a, "model = object()\n")
            _write(source_b, "model = object()\n")

            # Fake engine modules isolate batch semantics from engine installs.
            build123d = types.ModuleType("build123d")

            def export_stl(model, path):
                Path(path).write_text("build123d\n", encoding="utf-8")

            build123d.export_stl = export_stl
            cadquery = types.ModuleType("cadquery")
            cadquery.exporters = types.SimpleNamespace(
                export=lambda model, path: Path(path).write_text(
                    "cadquery\n",
                    encoding="utf-8",
                )
            )

            manifest = root / "manifest.json"
            report = root / "report.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "runtime": "reference",
                        "batch_contract": 3,
                        "models": [
                            {
                                "item_id": "a",
                                "builder": "build123d",
                                "source": str(source_a),
                                "output": str(output_a),
                            },
                            {
                                "item_id": "b",
                                "builder": "cadquery",
                                "source": str(source_b),
                                "output": str(output_b),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(
                sys.modules,
                {"build123d": build123d, "cadquery": cadquery},
            ):
                self.assertEqual(execute_manifest(manifest, report), 0)

            self.assertEqual(output_a.read_text(), "build123d\n")
            self.assertEqual(output_b.read_text(), "cadquery\n")
            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "pass")
            self.assertEqual(
                [row["status"] for row in result["models"]],
                ["pass", "pass"],
            )

    def test_runtime_keeps_later_models_observable_after_one_failure(self):
        """One failed model must not hide results for later batch models."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / "bad" / "model.py"
            good = root / "good" / "model.py"
            good_output = root / "out" / "good" / "model.stl"
            _write(bad, "not_model = object()\n")
            _write(good, "model = object()\n")

            build123d = types.ModuleType("build123d")
            build123d.export_stl = lambda model, path: Path(path).write_text(
                "ok\n",
                encoding="utf-8",
            )

            manifest = root / "manifest.json"
            report = root / "report.json"
            manifest.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "item_id": "bad",
                                "builder": "build123d",
                                "source": str(bad),
                                "output": str(root / "out" / "bad" / "model.stl"),
                            },
                            {
                                "item_id": "good",
                                "builder": "build123d",
                                "source": str(good),
                                "output": str(good_output),
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(sys.modules, {"build123d": build123d}):
                self.assertEqual(execute_manifest(manifest, report), 1)

            self.assertTrue(good_output.is_file())
            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "fail")
            self.assertEqual(
                [row["status"] for row in result["models"]],
                ["error", "pass"],
            )


if __name__ == "__main__":
    unittest.main()
