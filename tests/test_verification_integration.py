"""Conformance tests for reusable verification integration in CAD-CI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
import zipfile
from unittest.mock import patch

import cad_ci.builders.batch as batch_module
from cad_ci.builders.catalog import runtime_catalog_signature
from cad_ci.builders.batch import run_batch
from cad_ci.builders.runtime import execute_manifest
from cad_ci.config import ConfigError, load_repository
from cad_ci.execution.process import ProcessResult
from cad_ci.model import VerificationPackage
from cad_ci.scons.engine import resolve_request, write_manifest
from cad_ci.verification.package import build_package


VERIFY_COMMIT = "c7c145b7be0c602724e8cca874ef29990baaad1e"


def _write(path: Path, text: str) -> None:
    """Write one source fixture with its parent directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class RecordingProcessRunner:
    """Record host process requests without starting Docker."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, command, *, cwd=None, check=False):
        """Record one command and report success."""

        self.calls.append(list(command))
        return ProcessResult(returncode=0)


class WheelProducingRunner:
    """Fake pip wheel while preserving the external-process request boundary."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, command, *, cwd=None, check=False):
        """Record the request and materialize one minimal valid wheel."""

        argv = list(command)
        self.calls.append(argv)
        wheel_dir = Path(argv[argv.index("--wheel-dir") + 1])
        wheel_dir.mkdir(parents=True, exist_ok=True)
        wheel = (
            wheel_dir
            / "brainboxemb_cad_verification_lib-0.16.0-py3-none-any.whl"
        )
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(
                "brainboxemb_cad_verification_lib-0.16.0.dist-info/METADATA",
                "Metadata-Version: 2.1\n"
                "Name: brainboxemb-cad-verification-lib\n"
                "Version: 0.16.0\n",
            )
        return ProcessResult(returncode=0)


class VerificationGraphTests(unittest.TestCase):
    """Prove verification lowers to one package and one shared CAD runtime."""

    def make_repo(self, root: Path) -> None:
        """Create two verified reference models using one root template."""

        _write(
            root / "cad-ci.yml",
            "schema: 1\n"
            "verification:\n"
            "  package:\n"
            "    repository: brainboxemb/lib.py.cad.verification\n"
            "    version: '0.16.0'\n"
            f"    commit: {VERIFY_COMMIT}\n"
            "runtimes:\n"
            "  reference: ghcr.io/example/cad-reference:v1.2.3\n"
            "templates:\n"
            "  verified-reference:\n"
            "    kind: verification\n"
            "    builder: build123d\n"
            "    verification:\n"
            "      adapter: mesh-geometry\n"
            "      definition: ../verification/reference_geometry.json\n"
            "items: [models/*/*]\n",
        )
        for model, builder in (("a", "build123d"), ("b", "cadquery")):
            item = root / "models" / model / builder
            _write(
                item / "ci.yml",
                f"id: {model}-reference\n"
                "template: verified-reference\n"
                + (f"builder: {builder}\n" if builder != "build123d" else ""),
            )
            _write(item / "model.py", "model = object()\n")
            _write(
                root
                / "models"
                / model
                / "verification"
                / "reference_geometry.json",
                "{}\n",
            )

    def test_template_build_and_verification_share_package_and_runtime(self):
        """Two verified models lower to one package and one runtime producer."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_repo(root)
            items = load_repository(root)

            self.assertEqual(
                set(items),
                {
                    "a-reference",
                    "b-reference",
                    "cad-ci-runtime-reference",
                    "cad-ci-verification-package",
                },
            )

            for item_id in ("a-reference", "b-reference"):
                item = items[item_id]
                self.assertIsNotNone(item.verification)
                self.assertEqual(
                    [step.id for step in item.steps],
                    ["build", "verify"],
                )
                self.assertEqual(item.steps[0].outputs, ("model.stl",))
                self.assertEqual(item.steps[1].outputs, ("verification",))
                self.assertEqual(
                    item.needs,
                    ("cad-ci-runtime-reference",),
                )

            package = items["cad-ci-verification-package"]
            self.assertTrue(package.internal)
            self.assertEqual(
                package.steps[0].outputs,
                ("dist", "provenance.json"),
            )

            runtime = items["cad-ci-runtime-reference"]
            self.assertEqual(
                runtime.needs,
                ("cad-ci-verification-package",),
            )
            self.assertEqual(
                runtime.steps[0].selection_context,
                "direct_dependents",
            )

            request = resolve_request(
                items,
                {"a-reference", "b-reference"},
            )
            path = write_manifest(root, items, request)
            manifest = json.loads(path.read_text(encoding="utf-8"))
            specs = {row["key"]: row for row in manifest["targets"]}
            self.assertEqual(
                specs["cad-ci-runtime-reference:build"]["dependencies"],
                ["cad-ci-verification-package:package"],
            )
            self.assertEqual(
                specs["a-reference:build"]["dependencies"],
                ["cad-ci-runtime-reference:build"],
            )
            self.assertEqual(
                specs["a-reference:verify"]["dependencies"],
                ["a-reference:build"],
            )

            first_digest = specs["cad-ci-runtime-reference:build"][
                "target_spec_digest"
            ]
            root_config = root / "cad-ci.yml"
            root_config.write_text(
                root_config.read_text(encoding="utf-8").replace(
                    "      adapter: mesh-geometry\n",
                    "      adapter: mesh-geometry\n"
                    "      id: shared-geometry\n",
                ),
                encoding="utf-8",
            )
            changed_items = load_repository(root)
            changed_request = resolve_request(
                changed_items,
                {"a-reference", "b-reference"},
            )
            changed_path = write_manifest(
                root,
                changed_items,
                changed_request,
            )
            changed_manifest = json.loads(
                changed_path.read_text(encoding="utf-8")
            )
            changed_specs = {
                row["key"]: row for row in changed_manifest["targets"]
            }
            self.assertNotEqual(
                first_digest,
                changed_specs["cad-ci-runtime-reference:build"][
                    "target_spec_digest"
                ],
            )

    def test_invalid_verification_configuration_fails_during_load(self):
        """Missing package or unsupported adapter never reaches runtime."""

        cases = (
            (
                "schema: 1\n"
                "runtimes: {reference: ghcr.io/example/reference:v1}\n"
                "items: [model]\n",
                "adapter: mesh-geometry\ndefinition: geometry.json\n",
                "requires root verification.package",
            ),
            (
                "schema: 1\n"
                "verification:\n"
                "  package:\n"
                "    repository: brainboxemb/lib.py.cad.verification\n"
                "    version: '0.16.0'\n"
                f"    commit: {VERIFY_COMMIT}\n"
                "runtimes: {reference: ghcr.io/example/reference:v1}\n"
                "items: [model]\n",
                "adapter: unknown\ndefinition: geometry.json\n",
                "verification.adapter",
            ),
        )
        for root_yaml, verification_yaml, expected in cases:
            with self.subTest(expected=expected):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    _write(root / "cad-ci.yml", root_yaml)
                    _write(
                        root / "model" / "ci.yml",
                        "id: model\n"
                        "builder: build123d\n"
                        "verification:\n"
                        + "".join(
                            f"  {line}\n"
                            for line in verification_yaml.strip().splitlines()
                        ),
                    )
                    _write(root / "model" / "model.py", "model = object()\n")
                    _write(root / "model" / "geometry.json", "{}\n")
                    with self.assertRaisesRegex(ConfigError, expected):
                        load_repository(root)


class VerificationHostBatchTests(unittest.TestCase):
    """Prove verification does not add another CAD runtime start."""

    def test_verified_batch_mounts_one_wheel_in_one_docker_run(self):
        """Shared verification package is injected into the existing container."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            VerificationGraphTests().make_repo(root)
            output = root / "build" / ".cad-ci-runtime" / "reference"
            wheel = root / "dependency" / "verification.whl"
            wheel.parent.mkdir(parents=True)
            wheel.write_bytes(b"wheel")

            class Dependency:
                def output(self, name):
                    self_name = name
                    if self_name != "dist":
                        raise AssertionError(self_name)
                    return wheel.parent

            class Context:
                def dependency(self, item_id):
                    self_id = item_id
                    if self_id != "cad-ci-verification-package":
                        raise AssertionError(self_id)
                    return Dependency()

            process = RecordingProcessRunner()
            env = {
                "CAD_CI_REPO": str(root),
                "CAD_CI_OUTPUT": str(output),
                "CAD_CI_RUNTIME": "reference",
                "CAD_CI_RUNTIME_IMAGE": "ghcr.io/example/cad-reference:v1.2.3",
                "CAD_CI_ACTIVE_DEPENDENTS_JSON": '["a-reference","b-reference"]',
            }
            with (
                patch.object(batch_module, "current_context", return_value=Context()),
                patch.object(batch_module, "materialized_wheel", return_value=wheel),
            ):
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
                call for call in process.calls if call[:2] == ["docker", "run"]
            ]
            self.assertEqual(len(docker_runs), 1)
            command = docker_runs[0]
            self.assertIn(
                "PYTHONPATH=/cad-verification.whl:/cad-ci-lib",
                command,
            )
            self.assertIn(
                f"{wheel}:/cad-verification.whl:ro",
                command,
            )


class VerificationPackageTests(unittest.TestCase):
    """Prove package materialization is one fakeable external-process action."""

    def test_exact_wheel_is_validated_and_provenance_is_written(self):
        """One package target creates one version-checked wheel and digest."""

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            runner = WheelProducingRunner()
            package = VerificationPackage(
                repository="brainboxemb/lib.py.cad.verification",
                version="0.16.0",
                commit=VERIFY_COMMIT,
            )
            wheel = build_package(
                package,
                environ={"CAD_CI_OUTPUT": str(output)},
                process=runner,
            )

            self.assertEqual(len(runner.calls), 1)
            self.assertIn("pip", runner.calls[0])
            self.assertTrue(wheel.is_file())
            provenance = json.loads(
                (output / "provenance.json").read_text(encoding="utf-8")
            )
            self.assertEqual(provenance["version"], "0.16.0")
            self.assertEqual(provenance["commit"], VERIFY_COMMIT)
            self.assertEqual(
                provenance["sha256"],
                hashlib.sha256(wheel.read_bytes()).hexdigest(),
            )


class VerificationRuntimeTests(unittest.TestCase):
    """Prove several verified models stay inside one runtime executor."""

    def test_failure_keeps_later_verified_model_observable(self):
        """A verification mismatch does not prevent the next model row."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_a = root / "a" / "model.py"
            source_b = root / "b" / "model.py"
            _write(source_a, "model = object()\n")
            _write(source_b, "model = object()\n")

            build123d = types.ModuleType("build123d")
            build123d.export_stl = lambda model, path: Path(path).write_text(
                "stl\n",
                encoding="utf-8",
            )

            verification_module = types.ModuleType("cad_verification")
            verification_module.load_geometry_contract = lambda path: str(path)

            def run_mesh(model_output, output_dir, contract, *, verification_id):
                output_dir = Path(output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                status = "fail" if verification_id == "bad-model" else "pass"
                error = "geometry mismatch" if status == "fail" else None
                report = {
                    "status": status,
                    "checks": [
                        {
                            "id": "geometry",
                            "status": status,
                            "error": error,
                        }
                    ],
                }
                (output_dir / "verification.json").write_text(
                    json.dumps(report),
                    encoding="utf-8",
                )
                return report

            verification_module.run_mesh_geometry_verification = run_mesh

            manifest = root / "manifest.json"
            report = root / "report.json"
            rows = []
            for name, verification_id in (("a", "bad-model"), ("b", "good-model")):
                rows.append(
                    {
                        "item_id": name,
                        "builder": "build123d",
                        "source": str(root / name / "model.py"),
                        "output": str(root / "out" / name / "model.stl"),
                        "verification": {
                            "adapter": "mesh-geometry",
                            "definition": str(root / name / "geometry.json"),
                            "verification_id": verification_id,
                            "output": str(root / "out" / name / "verification"),
                        },
                    }
                )
                _write(root / name / "geometry.json", "{}\n")
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

            with patch.dict(
                sys.modules,
                {
                    "build123d": build123d,
                    "cad_verification": verification_module,
                },
            ):
                self.assertEqual(execute_manifest(manifest, report), 1)

            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(
                [row["status"] for row in result["models"]],
                ["fail", "pass"],
            )
            self.assertEqual(
                [row["verification_status"] for row in result["models"]],
                ["fail", "pass"],
            )
            self.assertTrue(
                (root / "out" / "b" / "verification" / "verification.json").is_file()
            )


if __name__ == "__main__":
    unittest.main()
