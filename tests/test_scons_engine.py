"""Real-SCons acceptance tests for the specified CAD CI execution engine."""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from cad_ci.config import load_repository
from cad_ci.scons_engine import (
    CACHE_ROOT,
    REPORT_PATH,
    RUN_ROOT,
    STATE_ROOT,
    TARGET_ROOT,
    SConsRunError,
    resolve_request,
    run_scons,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _rows(report: dict) -> dict[str, dict]:
    return {str(row["key"]): row for row in report["targets"]}


def _outcomes(report: dict) -> dict[str, str]:
    return {
        key: str(row["outcome"])
        for key, row in _rows(report).items()
    }


class SConsEngineTests(unittest.TestCase):
    def require_scons(self) -> None:
        if shutil.which("scons") is None:
            self.skipTest("SCons acceptance dependency is not installed")

    def run_selected(
        self,
        root: Path,
        selected: set[str],
        **request_kwargs,
    ) -> dict:
        items = load_repository(root)
        request = resolve_request(
            items,
            selected,
            **request_kwargs,
        )
        return run_scons(root, items, request)

    def make_simple_repo(self, root: Path) -> None:
        _write(
            root / "cad-ci.yml",
            "schema: 1\n"
            "defaults: {timeout_seconds: 10}\n"
            "items: [item]\n",
        )
        _write(root / "item" / "input" / "a.txt", "one\n")
        _write(
            root / "item" / "build.py",
            """import os
from pathlib import Path
item = Path(__file__).parent
out = Path(os.environ["CAD_CI_OUTPUT"])
out.mkdir(parents=True, exist_ok=True)
text = "".join(
    path.read_text()
    for path in sorted((item / "input").glob("*.txt"))
)
(out / "build.json").write_text(text)
""",
        )
        _write(
            root / "item" / "verify.py",
            """import os
from pathlib import Path
out = Path(os.environ["CAD_CI_OUTPUT"])
assert (out / "build.json").read_text()
(out / "verify.json").write_text("verified\\n")
""",
        )
        _write(
            root / "item" / "ci.yml",
            "id: item\n"
            "kind: example\n"
            "watch: [item/**]\n"
            "steps:\n"
            "  - id: build\n"
            "    inputs: [item/build.py, item/input/**]\n"
            "    run: [python, build.py]\n"
            "    outputs: [build.json]\n"
            "  - id: verify\n"
            "    inputs: [item/verify.py]\n"
            "    run: [python, verify.py]\n"
            "    outputs: [verify.json]\n",
        )

    def clean_runner_keep_cache(self, root: Path) -> None:
        """Simulate a fresh CI runner while preserving only SCons CacheDir."""

        shutil.rmtree(root / "build", ignore_errors=True)
        shutil.rmtree(root / STATE_ROOT, ignore_errors=True)
        shutil.rmtree(root / TARGET_ROOT, ignore_errors=True)
        shutil.rmtree(root / RUN_ROOT, ignore_errors=True)

    def test_simple_inputs_and_step_config_are_selective(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_simple_repo(root)

            cold = self.run_selected(root, {"item"})
            self.assertEqual(
                _outcomes(cold),
                {"item:build": "BUILT", "item:verify": "BUILT"},
            )

            current = self.run_selected(root, {"item"})
            self.assertEqual(
                _outcomes(current),
                {"item:build": "CURRENT", "item:verify": "CURRENT"},
            )

            _write(root / "item" / "input" / "a.txt", "two\n")
            changed_input = self.run_selected(root, {"item"})
            self.assertEqual(
                _outcomes(changed_input),
                {"item:build": "BUILT", "item:verify": "BUILT"},
            )

            with (root / "item" / "verify.py").open(
                "a",
                encoding="utf-8",
            ) as handle:
                handle.write("# verify-only change\n")
            verify_only = self.run_selected(root, {"item"})
            self.assertEqual(
                _outcomes(verify_only),
                {"item:build": "CURRENT", "item:verify": "BUILT"},
            )

            ci = root / "item" / "ci.yml"
            ci.write_text(
                ci.read_text(encoding="utf-8").replace(
                    "    run: [python, verify.py]\n"
                    "    outputs: [verify.json]\n",
                    "    run: [python, verify.py]\n"
                    "    outputs: [verify.json]\n"
                    "    timeout_seconds: 9\n",
                ),
                encoding="utf-8",
            )
            verify_config = self.run_selected(root, {"item"})
            self.assertEqual(
                _outcomes(verify_config),
                {"item:build": "CURRENT", "item:verify": "BUILT"},
            )

            ci.write_text(
                ci.read_text(encoding="utf-8").replace(
                    "kind: example",
                    "kind: documentation-only-change",
                ),
                encoding="utf-8",
            )
            descriptive = self.run_selected(root, {"item"})
            self.assertEqual(
                _outcomes(descriptive),
                {"item:build": "CURRENT", "item:verify": "CURRENT"},
            )

    def test_input_pattern_membership_invalidates_build(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_simple_repo(root)
            self.run_selected(root, {"item"})
            self.run_selected(root, {"item"})

            shutil.rmtree(root / CACHE_ROOT, ignore_errors=True)
            _write(root / "item" / "input" / "b.txt", "second\n")
            added = self.run_selected(root, {"item"})
            self.assertEqual(
                _outcomes(added),
                {"item:build": "BUILT", "item:verify": "BUILT"},
            )

            shutil.rmtree(root / CACHE_ROOT, ignore_errors=True)
            (root / "item" / "input" / "b.txt").unlink()
            removed = self.run_selected(root, {"item"})
            self.assertEqual(
                _outcomes(removed),
                {"item:build": "BUILT", "item:verify": "BUILT"},
            )

    def test_cumulative_dependency_bundle_propagates_earlier_output(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "cad-ci.yml",
                "schema: 1\nitems: [dependency, consumer]\n",
            )

            _write(root / "dependency" / "input.txt", "one\n")
            _write(
                root / "dependency" / "prepare.py",
                """import os
from pathlib import Path
out = Path(os.environ["CAD_CI_OUTPUT"])
out.mkdir(parents=True, exist_ok=True)
(out / "data.txt").write_text(Path(__file__).with_name("input.txt").read_text())
""",
            )
            _write(
                root / "dependency" / "finish.py",
                """import os
from pathlib import Path
out = Path(os.environ["CAD_CI_OUTPUT"])
(out / "done.txt").write_text("constant\\n")
""",
            )
            _write(
                root / "dependency" / "ci.yml",
                "id: dependency\n"
                "watch: [dependency/**]\n"
                "steps:\n"
                "  - id: prepare\n"
                "    inputs: [dependency/input.txt, dependency/prepare.py]\n"
                "    run: [python, prepare.py]\n"
                "    outputs: [data.txt]\n"
                "  - id: finish\n"
                "    inputs: [dependency/finish.py]\n"
                "    run: [python, finish.py]\n"
                "    outputs: [done.txt]\n",
            )

            _write(
                root / "consumer" / "run.py",
                """from pathlib import Path
from cad_ci.context import current_context
ctx = current_context()
dependency = ctx.dependency("dependency")
text = dependency.output("data.txt").read_text()
(ctx.output / "result.txt").write_text(text)
""",
            )
            _write(
                root / "consumer" / "ci.yml",
                "id: consumer\n"
                "needs: [dependency]\n"
                "watch: [consumer/**]\n"
                "steps:\n"
                "  - id: build\n"
                "    inputs: [consumer/run.py]\n"
                "    run: [python, run.py]\n"
                "    outputs: [result.txt]\n",
            )

            cold = self.run_selected(
                root,
                {"dependency", "consumer"},
            )
            self.assertEqual(
                _outcomes(cold),
                {
                    "dependency:prepare": "BUILT",
                    "dependency:finish": "BUILT",
                    "consumer:build": "BUILT",
                },
            )

            current = self.run_selected(
                root,
                {"dependency", "consumer"},
            )
            self.assertEqual(
                _outcomes(current),
                {
                    "dependency:prepare": "CURRENT",
                    "dependency:finish": "CURRENT",
                    "consumer:build": "CURRENT",
                },
            )

            _write(root / "dependency" / "input.txt", "two\n")
            changed = self.run_selected(
                root,
                {"dependency", "consumer"},
            )
            self.assertEqual(
                _outcomes(changed),
                {
                    "dependency:prepare": "BUILT",
                    "dependency:finish": "BUILT",
                    "consumer:build": "BUILT",
                },
            )
            self.assertEqual(
                (root / "build" / "consumer" / "result.txt").read_text(),
                "two\n",
            )

    def make_three_step_repo(self, root: Path) -> None:
        _write(root / "cad-ci.yml", "schema: 1\nitems: [item]\n")
        scripts = {
            "prepare": (
                "prepare.txt",
                "prepared\\n",
                None,
            ),
            "build": (
                "build.txt",
                "built\\n",
                "prepare.txt",
            ),
            "verify": (
                "verify.txt",
                "verified\\n",
                "build.txt",
            ),
        }
        for step, (output, text, prerequisite) in scripts.items():
            check = (
                ""
                if prerequisite is None
                else f"assert (out / {prerequisite!r}).read_text()\n"
            )
            _write(
                root / "item" / f"{step}.py",
                "import os\n"
                "from pathlib import Path\n"
                "out = Path(os.environ['CAD_CI_OUTPUT'])\n"
                "out.mkdir(parents=True, exist_ok=True)\n"
                + check
                + f"(out / {output!r}).write_text({text!r})\n",
            )

        _write(
            root / "item" / "ci.yml",
            "id: item\n"
            "steps:\n"
            "  - id: prepare\n"
            "    inputs: [item/prepare.py]\n"
            "    run: [python, prepare.py]\n"
            "    outputs: [prepare.txt]\n"
            "  - id: build\n"
            "    inputs: [item/build.py]\n"
            "    run: [python, build.py]\n"
            "    outputs: [build.txt]\n"
            "  - id: verify\n"
            "    inputs: [item/verify.py]\n"
            "    run: [python, verify.py]\n"
            "    outputs: [verify.txt]\n",
        )

    def test_partial_step_until_and_from_have_fixed_semantics(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_three_step_repo(root)
            self.run_selected(root, {"item"})

            exact = self.run_selected(
                root,
                {"item"},
                item_id="item",
                step="build",
            )
            self.assertEqual(
                _outcomes(exact),
                {"item:prepare": "CURRENT", "item:build": "BUILT"},
            )
            self.assertFalse(
                (root / "build/item/.cad-ci/item.json").exists()
            )

            # Restore complete evidence through a normal final-target run.
            self.run_selected(root, {"item"})

            until = self.run_selected(
                root,
                {"item"},
                item_id="item",
                until="build",
            )
            self.assertEqual(
                _outcomes(until),
                {"item:prepare": "CURRENT", "item:build": "CURRENT"},
            )
            self.assertFalse(
                (root / "build/item/.cad-ci/item.json").exists()
            )

            self.run_selected(root, {"item"})
            from_build = self.run_selected(
                root,
                {"item"},
                item_id="item",
                start="build",
            )
            self.assertEqual(
                _outcomes(from_build),
                {
                    "item:prepare": "CURRENT",
                    "item:build": "BUILT",
                    "item:verify": "BUILT",
                },
            )
            self.assertTrue(
                (root / "build/item/.cad-ci/item.json").is_file()
            )

    def test_timeout_failure_and_missing_output_are_distinct(self):
        self.require_scons()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "cad-ci.yml",
                "schema: 1\n"
                "defaults: {timeout_seconds: 1}\n"
                "items: [item]\n",
            )
            _write(
                root / "item" / "ci.yml",
                "id: item\n"
                "steps:\n"
                "  - id: run\n"
                "    inputs: []\n"
                "    run: [python, -c, 'import time; time.sleep(5)']\n",
            )
            with self.assertRaises(SConsRunError) as caught:
                self.run_selected(root, {"item"})
            row = caught.exception.report["targets"][0]
            self.assertEqual(row["outcome"], "ERROR")
            self.assertEqual(row["status"], "timeout")
            self.assertIsNone(row["exit_code"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "cad-ci.yml", "schema: 1\nitems: [item]\n")
            _write(
                root / "item" / "ci.yml",
                "id: item\n"
                "steps:\n"
                "  - id: run\n"
                "    inputs: []\n"
                "    run: [python, -c, 'raise SystemExit(3)']\n",
            )
            with self.assertRaises(SConsRunError) as caught:
                self.run_selected(root, {"item"})
            row = caught.exception.report["targets"][0]
            self.assertEqual(row["status"], "fail")
            self.assertEqual(row["exit_code"], 3)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "cad-ci.yml", "schema: 1\nitems: [item]\n")
            _write(
                root / "item" / "ci.yml",
                "id: item\n"
                "steps:\n"
                "  - id: run\n"
                "    inputs: []\n"
                "    run: [python, -c, 'print(1)']\n"
                "    outputs: [missing.txt]\n",
            )
            with self.assertRaises(SConsRunError) as caught:
                self.run_selected(root, {"item"})
            row = caught.exception.report["targets"][0]
            self.assertEqual(row["status"], "output_error")
            self.assertIn("missing declared output", row["error"])

    def test_directory_output_repair_and_fresh_cache_restore(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "cad-ci.yml", "schema: 1\nitems: [item]\n")
            _write(root / "item" / "input.txt", "one\n")
            _write(
                root / "item" / "run.py",
                """import os
from pathlib import Path
out = Path(os.environ["CAD_CI_OUTPUT"]) / "generated"
(out / "nested").mkdir(parents=True, exist_ok=True)
(out / "empty").mkdir(parents=True, exist_ok=True)
(out / "nested" / "value.txt").write_text(
    Path(__file__).with_name("input.txt").read_text()
)
""",
            )
            _write(
                root / "item" / "ci.yml",
                "id: item\n"
                "steps:\n"
                "  - id: build\n"
                "    inputs: [item/input.txt, item/run.py]\n"
                "    run: [python, run.py]\n"
                "    outputs: [generated]\n",
            )

            cold = self.run_selected(root, {"item"})
            row = _rows(cold)["item:build"]
            self.assertEqual(row["outcome"], "BUILT")
            self.assertEqual(row["materialization"], "UNCHANGED")

            current = self.run_selected(root, {"item"})
            row = _rows(current)["item:build"]
            self.assertEqual(row["outcome"], "CURRENT")
            self.assertEqual(row["materialization"], "UNCHANGED")

            generated = root / "build/item/generated"
            shutil.rmtree(generated)
            restored_local = self.run_selected(root, {"item"})
            row = _rows(restored_local)["item:build"]
            self.assertEqual(row["outcome"], "CURRENT")
            self.assertEqual(row["materialization"], "RESTORED")

            nested = generated / "nested/value.txt"
            nested.write_text("tampered\n", encoding="utf-8")
            repaired = self.run_selected(root, {"item"})
            row = _rows(repaired)["item:build"]
            self.assertEqual(row["outcome"], "CURRENT")
            self.assertEqual(row["materialization"], "REPAIRED")
            self.assertEqual(nested.read_text(), "one\n")

            _write(generated / "extra.txt", "extra\n")
            repaired_extra = self.run_selected(root, {"item"})
            row = _rows(repaired_extra)["item:build"]
            self.assertEqual(row["materialization"], "REPAIRED")
            self.assertFalse((generated / "extra.txt").exists())

            self.assertTrue((root / CACHE_ROOT).is_dir())
            self.clean_runner_keep_cache(root)
            fresh = self.run_selected(root, {"item"})
            row = _rows(fresh)["item:build"]
            self.assertEqual(row["outcome"], "CACHE_RESTORED")
            self.assertEqual(row["materialization"], "RESTORED")
            self.assertTrue((generated / "empty").is_dir())

    def test_reuse_false_executes_again(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "cad-ci.yml", "schema: 1\nitems: [item]\n")
            _write(
                root / "item" / "run.py",
                """import os
from pathlib import Path
out = Path(os.environ["CAD_CI_OUTPUT"])
out.mkdir(parents=True, exist_ok=True)
(out / "result.txt").write_text("same\\n")
""",
            )
            _write(
                root / "item" / "ci.yml",
                "id: item\n"
                "strategy: {reuse: false}\n"
                "steps:\n"
                "  - id: run\n"
                "    inputs: [item/run.py]\n"
                "    run: [python, run.py]\n"
                "    outputs: [result.txt]\n",
            )

            first = self.run_selected(root, {"item"})
            second = self.run_selected(root, {"item"})
            self.assertEqual(
                _outcomes(first),
                {"item:run": "BUILT"},
            )
            self.assertEqual(
                _outcomes(second),
                {"item:run": "BUILT"},
            )

    def test_run_report_is_private_and_public_evidence_is_separate(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_simple_repo(root)
            self.run_selected(root, {"item"})

            self.assertTrue((root / REPORT_PATH).is_file())
            self.assertTrue(
                (root / "build/item/.cad-ci/steps/build.json").is_file()
            )
            self.assertTrue(
                (root / "build/item/.cad-ci/steps/verify.json").is_file()
            )
            self.assertTrue(
                (root / "build/item/.cad-ci/item.json").is_file()
            )
            self.assertFalse(
                (root / "build/item/.cache").exists()
            )


if __name__ == "__main__":
    unittest.main()
