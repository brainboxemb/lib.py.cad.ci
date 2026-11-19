"""Real-SCons conformance tests for the generic CAD CI execution engine.

These tests use tiny consumer repositories and the production scons_driver.py.
They prove the decisions that used to be implemented manually by runner.py:
cold/current builds, selective invalidation, dependency execution, CacheDir
restore, directory-output materialization, config invalidation and timeout/error
reporting.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from cad_ci.config import load_repository
from cad_ci.scons_engine import (
    CACHE_ROOT,
    STATE_ROOT,
    WORK_ROOT,
    SConsRunError,
    requested_keys,
    run_scons,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _outcomes(report: dict) -> dict[str, str]:
    return {
        str(target["key"]): str(target["outcome"])
        for target in report["targets"]
    }


class SConsEngineTests(unittest.TestCase):
    def require_scons(self) -> None:
        if shutil.which("scons") is None:
            self.skipTest("SCons conformance dependency is not installed")

    def make_two_item_repo(self, root: Path) -> None:
        _write(
            root / "cad-ci.yml",
            "schema: 1\n"
            "defaults: {timeout_seconds: 10}\n"
            "items: [a, b]\n",
        )
        _write(root / "shared" / "shared.txt", "shared-1\n")

        for name in ("a", "b"):
            _write(root / name / "input.txt", f"{name}-1\n")
            _write(
                root / name / "run.py",
                """import os
from pathlib import Path
repo = Path(os.environ["CAD_CI_REPO"])
out = Path(os.environ["CAD_CI_OUTPUT"])
out.mkdir(parents=True, exist_ok=True)
item = os.environ["CAD_CI_ITEM"]
text = (repo / "shared" / "shared.txt").read_text()
text += (repo / item / "input.txt").read_text()
(out / "result.txt").write_text(text)
""",
            )
            _write(
                root / name / "ci.yml",
                f"id: {name}\n"
                f"watch: [shared/**, {name}/**]\n"
                "steps:\n"
                "  - id: build\n"
                "    run: [python, run.py]\n"
                "    outputs: [result.txt]\n",
            )

    def run_all(self, root: Path) -> dict:
        items = load_repository(root)
        requested = requested_keys(items, set(items))
        return run_scons(root, items, requested)

    def clean_runner_keep_cache(self, root: Path) -> None:
        shutil.rmtree(root / "build", ignore_errors=True)
        shutil.rmtree(root / STATE_ROOT, ignore_errors=True)
        shutil.rmtree(root / WORK_ROOT, ignore_errors=True)

    def test_cold_current_private_and_shared_changes(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_two_item_repo(root)

            cold = self.run_all(root)
            self.assertEqual(
                _outcomes(cold),
                {"a:build": "BUILT", "b:build": "BUILT"},
            )

            unchanged = self.run_all(root)
            self.assertEqual(
                _outcomes(unchanged),
                {"a:build": "CURRENT", "b:build": "CURRENT"},
            )

            _write(root / "a" / "input.txt", "a-2\n")
            private = self.run_all(root)
            self.assertEqual(
                _outcomes(private),
                {"a:build": "BUILT", "b:build": "CURRENT"},
            )

            _write(root / "shared" / "shared.txt", "shared-2\n")
            shared = self.run_all(root)
            self.assertEqual(
                _outcomes(shared),
                {"a:build": "BUILT", "b:build": "BUILT"},
            )

    def test_fresh_runner_restores_bundles_from_cache(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_two_item_repo(root)
            self.run_all(root)

            cache = root / CACHE_ROOT
            self.assertTrue(cache.is_dir())
            self.clean_runner_keep_cache(root)

            restored = self.run_all(root)
            self.assertEqual(
                _outcomes(restored),
                {
                    "a:build": "CACHE_RESTORED",
                    "b:build": "CACHE_RESTORED",
                },
            )
            self.assertEqual(
                (root / "build" / "a" / "result.txt").read_text(),
                "shared-1\na-1\n",
            )

    def test_directory_output_is_materialized_and_repaired_without_rebuild(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "cad-ci.yml", "schema: 1\nitems: [item]\n")
            _write(root / "item" / "input.txt", "one\n")
            _write(
                root / "item" / "run.py",
                """import os
from pathlib import Path
out = Path(os.environ["CAD_CI_OUTPUT"]) / "results"
(out / "nested").mkdir(parents=True, exist_ok=True)
(out / "empty").mkdir(parents=True, exist_ok=True)
source = Path(__file__).with_name("input.txt").read_text()
(out / "nested" / "value.txt").write_text(source)
""",
            )
            _write(
                root / "item" / "ci.yml",
                "id: item\n"
                "steps:\n"
                "  - id: package\n"
                "    run: [python, run.py]\n"
                "    outputs: [results]\n",
            )

            items = load_repository(root)
            requested = requested_keys(items, {"item"})
            cold = run_scons(root, items, requested)
            self.assertEqual(_outcomes(cold), {"item:package": "BUILT"})

            current = run_scons(root, items, requested)
            self.assertEqual(_outcomes(current), {"item:package": "CURRENT"})

            nested = root / "build" / "item" / "results" / "nested" / "value.txt"
            nested.write_text("externally changed\n", encoding="utf-8")
            repaired = run_scons(root, items, requested)
            self.assertEqual(_outcomes(repaired), {"item:package": "CURRENT"})
            self.assertTrue(repaired["targets"][0]["outputs_materialized"])
            self.assertEqual(nested.read_text(encoding="utf-8"), "one\n")

            self.clean_runner_keep_cache(root)
            restored = run_scons(root, items, requested)
            self.assertEqual(
                _outcomes(restored),
                {"item:package": "CACHE_RESTORED"},
            )
            self.assertEqual(nested.read_text(encoding="utf-8"), "one\n")
            self.assertTrue(
                (root / "build" / "item" / "results" / "empty").is_dir()
            )

    def test_dependency_chain_and_exact_step_use_scons_prerequisites(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "cad-ci.yml", "schema: 1\nitems: [dep, item]\n")

            _write(root / "dep" / "input.txt", "dep-1\n")
            _write(
                root / "dep" / "run.py",
                """import os
from pathlib import Path
out = Path(os.environ["CAD_CI_OUTPUT"])
out.mkdir(parents=True, exist_ok=True)
(out / "dep.txt").write_text(Path(__file__).with_name("input.txt").read_text())
""",
            )
            _write(
                root / "dep" / "ci.yml",
                "id: dep\n"
                "steps: [{id: build, run: [python, run.py], outputs: [dep.txt]}]\n",
            )

            _write(root / "item" / "input.txt", "item-1\n")
            _write(
                root / "item" / "build.py",
                """import json, os
from pathlib import Path
out = Path(os.environ["CAD_CI_OUTPUT"])
out.mkdir(parents=True, exist_ok=True)
deps = json.loads(os.environ["CAD_CI_DEPENDENCIES_JSON"])
dep = Path(deps["dep"]["output_root"]) / "dep.txt"
source = Path(__file__).with_name("input.txt").read_text()
(out / "built.txt").write_text(dep.read_text() + source)
""",
            )
            _write(
                root / "item" / "verify.py",
                """import os
from pathlib import Path
out = Path(os.environ["CAD_CI_OUTPUT"])
assert (out / "built.txt").read_text()
(out / "verified.txt").write_text("ok\n")
""",
            )
            _write(
                root / "item" / "ci.yml",
                "id: item\n"
                "needs: [dep]\n"
                "steps:\n"
                "  - id: build\n"
                "    run: [python, build.py]\n"
                "    outputs: [built.txt]\n"
                "  - id: verify\n"
                "    run: [python, verify.py]\n"
                "    outputs: [verified.txt]\n",
            )

            items = load_repository(root)
            exact = requested_keys(
                items,
                {"item"},
                item_id="item",
                step="verify",
            )
            first = run_scons(root, items, exact)
            self.assertEqual(
                _outcomes(first),
                {
                    "dep:build": "BUILT",
                    "item:build": "BUILT",
                    "item:verify": "BUILT",
                },
            )

            second = run_scons(root, items, exact)
            self.assertEqual(
                _outcomes(second),
                {
                    "dep:build": "CURRENT",
                    "item:build": "CURRENT",
                    "item:verify": "CURRENT",
                },
            )

            _write(root / "dep" / "input.txt", "dep-2\n")
            changed = run_scons(root, items, exact)
            self.assertEqual(
                _outcomes(changed),
                {
                    "dep:build": "BUILT",
                    "item:build": "BUILT",
                    "item:verify": "BUILT",
                },
            )

    def test_step_config_change_invalidates_target(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_two_item_repo(root)
            self.run_all(root)

            path = root / "a" / "ci.yml"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "outputs: [result.txt]",
                    "timeout_seconds: 9\n    outputs: [result.txt]",
                ),
                encoding="utf-8",
            )

            changed = self.run_all(root)
            self.assertEqual(
                _outcomes(changed),
                {"a:build": "BUILT", "b:build": "CURRENT"},
            )

    def test_timeout_and_command_failure_are_reported_as_errors(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "cad-ci.yml",
                "schema: 1\n"
                "defaults: {timeout_seconds: 1}\n"
                "items: [wait]\n",
            )
            _write(
                root / "wait" / "ci.yml",
                "id: wait\n"
                "steps:\n"
                "  - id: run\n"
                "    run: [python, -c, 'import time; time.sleep(5)']\n",
            )
            items = load_repository(root)
            requested = requested_keys(items, {"wait"})

            with self.assertRaises(SConsRunError) as caught:
                run_scons(root, items, requested)
            report = caught.exception.report
            self.assertIsNotNone(report)
            self.assertEqual(_outcomes(report), {"wait:run": "ERROR"})
            self.assertEqual(report["targets"][0]["action_status"], "timeout")

            _write(
                root / "wait" / "ci.yml",
                "id: wait\n"
                "steps:\n"
                "  - id: run\n"
                "    run: [python, -c, 'raise SystemExit(3)']\n",
            )
            items = load_repository(root)
            with self.assertRaises(SConsRunError) as failed:
                run_scons(root, items, requested_keys(items, {"wait"}))
            failure = failed.exception.report
            self.assertEqual(_outcomes(failure), {"wait:run": "ERROR"})
            self.assertEqual(failure["targets"][0]["action_status"], "fail")
            self.assertEqual(failure["targets"][0]["exit_code"], 3)


if __name__ == "__main__":
    unittest.main()
