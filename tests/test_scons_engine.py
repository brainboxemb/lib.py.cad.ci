"""Real-SCons acceptance tests for the specified CAD CI execution engine."""

from __future__ import annotations

from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cad_ci.config import load_repository
from cad_ci.scons_engine import (
    CACHE_ROOT,
    DEPENDENCY_RUN_ROOT,
    REPORT_PATH,
    RUN_ROOT,
    STATE_ROOT,
    TARGET_ROOT,
    MANIFEST_PATH,
    SConsRunError,
    resolve_request,
    run_scons,
    target_specs,
    write_manifest,
)
from cad_ci.paths import source_inventory


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


UTC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


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
        jobs = request_kwargs.pop("jobs", 1)
        request = resolve_request(
            items,
            selected,
            **request_kwargs,
        )
        return run_scons(root, items, request, jobs=jobs)

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

    def test_manifest_preparation_resolves_only_active_target_closure(self):
        """Selective preparation scans once and ignores unrelated target inputs."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "cad-ci.yml",
                "schema: 1\n"
                "items: [library, selected, unrelated]\n",
            )
            _write(root / "library" / "input.txt", "library\n")
            _write(
                root / "library" / "ci.yml",
                "id: library\n"
                "steps:\n"
                "  - id: build\n"
                "    inputs: [library/input.txt]\n"
                "    run: [python, -c, 'print(1)']\n",
            )
            _write(root / "selected" / "prepare.txt", "prepare\n")
            _write(root / "selected" / "verify.txt", "verify\n")
            _write(
                root / "selected" / "ci.yml",
                "id: selected\n"
                "needs: [library]\n"
                "steps:\n"
                "  - id: prepare\n"
                "    inputs: [selected/prepare.txt]\n"
                "    run: [python, -c, 'print(1)']\n"
                "  - id: verify\n"
                "    inputs: [selected/verify.txt]\n"
                "    run: [python, -c, 'print(1)']\n",
            )
            _write(root / "unrelated" / "input.txt", "unrelated\n")
            _write(
                root / "unrelated" / "ci.yml",
                "id: unrelated\n"
                "steps:\n"
                "  - id: build\n"
                "    inputs: [unrelated/**]\n"
                "    run: [python, -c, 'print(1)']\n",
            )

            items = load_repository(root)
            request = resolve_request(items, {"selected"})
            with patch(
                "cad_ci.scons_engine.source_inventory",
                wraps=source_inventory,
            ) as inventory:
                manifest_path = write_manifest(root, items, request)
            self.assertEqual(inventory.call_count, 1)

            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["active_keys"],
                ["library:build", "selected:prepare", "selected:verify"],
            )
            self.assertEqual(
                [row["key"] for row in manifest["targets"]],
                manifest["active_keys"],
            )

            # Active signatures remain identical to complete-graph preparation.
            complete = {
                row["key"]: row
                for row in target_specs(root, items)
            }
            for row in manifest["targets"]:
                self.assertEqual(
                    row["target_spec_digest"],
                    complete[row["key"]]["target_spec_digest"],
                )

            link = root / "unrelated" / "matched-link.txt"
            try:
                link.symlink_to(root / "unrelated" / "input.txt")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")

            # The inactive matched symlink does not block the selective run.
            selective = write_manifest(root, items, request)
            self.assertTrue(selective.is_file())

            # Selecting the owning item retains the existing safety failure.
            unrelated = resolve_request(items, {"unrelated"})
            with self.assertRaisesRegex(
                SConsRunError,
                "configured source input is a symlink",
            ):
                write_manifest(root, items, unrelated)

    def test_simple_inputs_and_step_config_are_selective(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_simple_repo(root)

            cold = self.run_selected(root, {"item"})
            self.assertEqual(cold["jobs"], 1)
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


    def test_execution_output_streams_and_uses_concise_action_label(self):
        """Expose live consumer output without leaking SCons function arguments."""

        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "cad-ci.yml", "schema: 1\nitems: [item]\n")
            _write(
                root / "item" / "run.py",
                "import os\n"
                "import time\n"
                "from pathlib import Path\n"
                "print('consumer-start', flush=True)\n"
                "time.sleep(0.5)\n"
                "out = Path(os.environ['CAD_CI_OUTPUT'])\n"
                "out.mkdir(parents=True, exist_ok=True)\n"
                "(out / 'result.txt').write_text('ok\\n')\n"
                "print('consumer-end', flush=True)\n",
            )
            _write(
                root / "item" / "ci.yml",
                "id: item\n"
                "steps:\n"
                "  - id: build\n"
                "    inputs: [item/run.py]\n"
                "    run: [python, run.py]\n"
                "    outputs: [result.txt]\n",
            )

            script = (
                "import sys\n"
                "from pathlib import Path\n"
                "from cad_ci.config import load_repository\n"
                "from cad_ci.scons_engine import resolve_request, run_scons\n"
                "repo = Path(sys.argv[1])\n"
                "items = load_repository(repo)\n"
                "request = resolve_request(items, {'item'})\n"
                "run_scons(repo, items, request)\n"
            )
            env = os.environ.copy()
            process = subprocess.Popen(
                [sys.executable, "-c", script, str(root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            assert process.stdout is not None

            lines: list[str] = []
            while True:
                line = process.stdout.readline()
                if line:
                    lines.append(line)
                    if "consumer-start" in line:
                        self.assertIsNone(
                            process.poll(),
                            "consumer output was buffered until process exit",
                        )
                        break
                    continue
                if process.poll() is not None:
                    self.fail(
                        "consumer-start was not visible before process exit"
                    )

            remainder, _ = process.communicate(timeout=10)
            output = "".join(lines) + remainder
            self.assertEqual(process.returncode, 0, output)
            self.assertIn("CAD CI run: item:build", output)
            self.assertIn("consumer-start", output)
            self.assertIn("consumer-end", output)
            self.assertNotIn("_execute_bundle(", output)
            self.assertNotIn("item/run.py\"]", output)

    def test_non_processed_item_cannot_be_requested(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "cad-ci.yml", "schema: 1\nitems: [item]\n")
            _write(
                root / "item" / "ci.yml",
                "id: item\n"
                "process: false\n"
                "steps:\n"
                "  - id: build\n"
                "    inputs: []\n"
                "    run: [python, -c, 'print(1)']\n",
            )
            items = load_repository(root)
            with self.assertRaisesRegex(SConsRunError, "item is not processed"):
                self.run_selected(root, {"item"})
            with self.assertRaisesRegex(SConsRunError, "item is not processed"):
                self.run_selected(root, {"item"}, item_id="item")

    def test_repository_variables_reach_commands_and_invalidate_targets(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "cad-ci.yml",
                "schema: 1\n"
                "variables: {MODEL_MODE: first}\n"
                "items: [item]\n",
            )
            _write(
                root / "item" / "run.py",
                """import os
from pathlib import Path
out = Path(os.environ["CAD_CI_OUTPUT"])
out.mkdir(parents=True, exist_ok=True)
(out / "mode.txt").write_text(os.environ["MODEL_MODE"])
""",
            )
            _write(
                root / "item" / "ci.yml",
                "id: item\n"
                "steps:\n"
                "  - id: build\n"
                "    inputs: [item/run.py]\n"
                "    run: [python, run.py]\n"
                "    outputs: [mode.txt]\n",
            )

            with patch.dict("os.environ", {"MODEL_MODE": "caller"}):
                cold = self.run_selected(root, {"item"})
                self.assertEqual(_outcomes(cold), {"item:build": "BUILT"})
                self.assertEqual(
                    (root / "build/item/mode.txt").read_text(),
                    "first",
                )

                current = self.run_selected(root, {"item"})
                self.assertEqual(_outcomes(current), {"item:build": "CURRENT"})

                root_config = root / "cad-ci.yml"
                root_config.write_text(
                    root_config.read_text(encoding="utf-8").replace(
                        "MODEL_MODE: first",
                        "MODEL_MODE: second",
                    ),
                    encoding="utf-8",
                )
                changed_variable = self.run_selected(root, {"item"})
                self.assertEqual(
                    _outcomes(changed_variable),
                    {"item:build": "BUILT"},
                )
                self.assertEqual(
                    (root / "build/item/mode.txt").read_text(),
                    "second",
                )

                unchanged = self.run_selected(root, {"item"})
                self.assertEqual(
                    _outcomes(unchanged),
                    {"item:build": "CURRENT"},
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

    def test_parallel_consumers_use_private_dependency_snapshots(self):
        """Two consumers may overlap without sharing dependency output roots."""

        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "cad-ci.yml",
                "schema: 1\nitems: [library, consumer-a, consumer-b]\n",
            )
            _write(root / "library" / "input.txt", "library-bytes\n")
            _write(
                root / "library" / "build.py",
                """import os
from pathlib import Path
out = Path(os.environ["CAD_CI_OUTPUT"])
out.mkdir(parents=True, exist_ok=True)
(out / "lib.txt").write_text(Path(__file__).with_name("input.txt").read_text())
""",
            )
            _write(
                root / "library" / "ci.yml",
                "id: library\n"
                "steps:\n"
                "  - id: build\n"
                "    inputs: [library/input.txt, library/build.py]\n"
                "    run: [python, build.py]\n"
                "    outputs: [lib.txt]\n",
            )

            consumer_script = """import json
import os
from pathlib import Path
import time
from cad_ci.context import current_context

ctx = current_context()
dependency = ctx.dependency("library")
before = dependency.output("lib.txt").read_text()
started = time.time()
time.sleep(0.4)
after = dependency.output("lib.txt").read_text()
finished = time.time()
ctx.output.mkdir(parents=True, exist_ok=True)
(ctx.output / "result.json").write_text(json.dumps({
    "before": before,
    "after": after,
    "started": started,
    "finished": finished,
    "dependency_root": str(dependency.root),
}))
"""
            for name in ("consumer-a", "consumer-b"):
                _write(root / name / "trigger.txt", "one\n")
                _write(root / name / "run.py", consumer_script)
                _write(
                    root / name / "ci.yml",
                    f"id: {name}\n"
                    "needs: [library]\n"
                    "steps:\n"
                    "  - id: run\n"
                    f"    inputs: [{name}/trigger.txt, {name}/run.py]\n"
                    "    run: [python, run.py]\n"
                    "    outputs: [result.json]\n",
                )

            parallel = self.run_selected(
                root,
                {"library", "consumer-a", "consumer-b"},
                jobs=2,
            )
            self.assertEqual(parallel["jobs"], 2)
            self.assertEqual(
                _outcomes(parallel),
                {
                    "library:build": "BUILT",
                    "consumer-a:run": "BUILT",
                    "consumer-b:run": "BUILT",
                },
            )

            results = []
            for name in ("consumer-a", "consumer-b"):
                result = json.loads(
                    (
                        root / "build" / name / "result.json"
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(result["before"], "library-bytes\n")
                self.assertEqual(result["after"], "library-bytes\n")
                results.append(result)

            self.assertNotEqual(
                results[0]["dependency_root"],
                results[1]["dependency_root"],
            )
            self.assertIn(
                DEPENDENCY_RUN_ROOT.as_posix(),
                results[0]["dependency_root"].replace("\\", "/"),
            )
            self.assertLess(
                max(result["started"] for result in results),
                min(result["finished"] for result in results),
            )
            self.assertEqual(
                (root / "build" / "library" / "lib.txt").read_text(),
                "library-bytes\n",
            )

            (root / "build" / "library" / "lib.txt").unlink()
            _write(root / "consumer-a" / "trigger.txt", "two\n")
            _write(root / "consumer-b" / "trigger.txt", "two\n")
            repaired = self.run_selected(
                root,
                {"consumer-a", "consumer-b"},
                jobs=2,
            )
            self.assertEqual(repaired["jobs"], 2)
            self.assertEqual(
                _outcomes(repaired),
                {
                    "library:build": "CURRENT",
                    "consumer-a:run": "BUILT",
                    "consumer-b:run": "BUILT",
                },
            )
            self.assertEqual(
                (root / "build" / "library" / "lib.txt").read_text(),
                "library-bytes\n",
            )

    def test_jobs_default_one_and_invalid_values_fail(self):
        """Parallelism is explicit and the compatibility default remains one."""

        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_simple_repo(root)
            items = load_repository(root)
            request = resolve_request(items, {"item"})

            report = run_scons(root, items, request)
            self.assertEqual(report["jobs"], 1)

            for value in (0, -1, True, 1.5):
                with self.subTest(value=value):
                    with self.assertRaisesRegex(
                        SConsRunError,
                        "jobs must be a positive integer",
                    ):
                        run_scons(root, items, request, jobs=value)

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
            self.assertTrue(row["action_executed"])
            self.assertRegex(row["started_at"], UTC_TIMESTAMP)
            self.assertRegex(row["finished_at"], UTC_TIMESTAMP)

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
            self.assertEqual(row["output_state"], "UNCHANGED")

            current = self.run_selected(root, {"item"})
            row = _rows(current)["item:build"]
            self.assertEqual(row["outcome"], "CURRENT")
            self.assertEqual(row["output_state"], "UNCHANGED")

            generated = root / "build/item/generated"
            shutil.rmtree(generated)
            restored_local = self.run_selected(root, {"item"})
            row = _rows(restored_local)["item:build"]
            self.assertEqual(row["outcome"], "CURRENT")
            self.assertEqual(row["output_state"], "RESTORED")

            nested = generated / "nested/value.txt"
            nested.write_text("tampered\n", encoding="utf-8")
            repaired = self.run_selected(root, {"item"})
            row = _rows(repaired)["item:build"]
            self.assertEqual(row["outcome"], "CURRENT")
            self.assertEqual(row["output_state"], "REPAIRED")
            self.assertEqual(nested.read_text(), "one\n")

            _write(generated / "extra.txt", "extra\n")
            repaired_extra = self.run_selected(root, {"item"})
            row = _rows(repaired_extra)["item:build"]
            self.assertEqual(row["output_state"], "REPAIRED")
            self.assertFalse((generated / "extra.txt").exists())

            self.assertTrue((root / CACHE_ROOT).is_dir())
            self.clean_runner_keep_cache(root)
            fresh = self.run_selected(root, {"item"})
            row = _rows(fresh)["item:build"]
            self.assertEqual(row["outcome"], "CACHE_RESTORED")
            self.assertEqual(row["output_state"], "RESTORED")
            self.assertFalse(row["action_executed"])
            self.assertIsNone(row["started_at"])
            self.assertIsNone(row["finished_at"])
            restored_step = json.loads(
                (root / "build/item/.cad-ci/steps/build.json").read_text()
            )
            self.assertIsNone(restored_step["started_at"])
            self.assertIsNone(restored_step["finished_at"])
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
            cold = self.run_selected(root, {"item"})

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

            report = json.loads((root / REPORT_PATH).read_text())
            self.assertEqual(report["schema_version"], 4)
            self.assertEqual(report["jobs"], 1)
            self.assertRegex(report["started_at"], UTC_TIMESTAMP)
            self.assertRegex(report["finished_at"], UTC_TIMESTAMP)
            self.assertLessEqual(report["started_at"], report["finished_at"])
            self.assertIn("output_state", report["targets"][0])
            self.assertNotIn("materialization", report["targets"][0])

            built = _rows(cold)["item:build"]
            self.assertTrue(built["action_executed"])
            self.assertRegex(built["started_at"], UTC_TIMESTAMP)
            self.assertRegex(built["finished_at"], UTC_TIMESTAMP)
            self.assertLessEqual(built["started_at"], built["finished_at"])
            self.assertIsNotNone(built["duration_seconds"])

            step_path = root / "build/item/.cad-ci/steps/build.json"
            step = json.loads(step_path.read_text())
            self.assertEqual(step["schema"], 3)
            self.assertEqual(step["run_started_at"], report["started_at"])
            self.assertEqual(step["run_finished_at"], report["finished_at"])
            self.assertEqual(step["started_at"], built["started_at"])
            self.assertEqual(step["finished_at"], built["finished_at"])
            self.assertIn("output_state", step)
            self.assertNotIn("materialization", step)

            item = json.loads(
                (root / "build/item/.cad-ci/item.json").read_text()
            )
            self.assertEqual(item["schema"], 2)
            self.assertEqual(item["run_started_at"], report["started_at"])
            self.assertEqual(item["run_finished_at"], report["finished_at"])

            current = self.run_selected(root, {"item"})
            current_row = _rows(current)["item:build"]
            self.assertEqual(current_row["outcome"], "CURRENT")
            self.assertFalse(current_row["action_executed"])
            self.assertIsNone(current_row["started_at"])
            self.assertIsNone(current_row["finished_at"])

            current_step = json.loads(step_path.read_text())
            self.assertIsNone(current_step["started_at"])
            self.assertIsNone(current_step["finished_at"])
            self.assertRegex(current_step["run_started_at"], UTC_TIMESTAMP)
            self.assertRegex(current_step["run_finished_at"], UTC_TIMESTAMP)

            self.assertFalse(
                (root / "build/item/.cache").exists()
            )


if __name__ == "__main__":
    unittest.main()
