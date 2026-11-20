"""Tests for the thin public SCons-backed execution API."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from cad_ci.config import load_repository
from cad_ci.git import changed_files
from cad_ci.planner import affected_items
from cad_ci.runner import RunError, run_repository


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class RunnerTests(unittest.TestCase):
    def require_scons(self) -> None:
        if shutil.which("scons") is None:
            self.skipTest("SCons execution dependency is not installed")

    def make_repo(self, root: Path) -> dict:
        _write(root / "cad-ci.yml", "schema: 1\nitems: [item]\n")
        for step, output in (("build", "built.txt"), ("verify", "verified.txt")):
            prerequisite = (
                ""
                if step == "build"
                else "assert (out / 'built.txt').is_file()\n"
            )
            _write(
                root / "item" / f"{step}.py",
                "import os\n"
                "from pathlib import Path\n"
                "out = Path(os.environ['CAD_CI_OUTPUT'])\n"
                "out.mkdir(parents=True, exist_ok=True)\n"
                + prerequisite
                + f"(out / {output!r}).write_text({step!r})\n",
            )
        _write(
            root / "item" / "ci.yml",
            "id: item\n"
            "steps:\n"
            "  - id: build\n"
            "    inputs: [item/build.py]\n"
            "    run: [python, build.py]\n"
            "    outputs: [built.txt]\n"
            "  - id: verify\n"
            "    inputs: [item/verify.py]\n"
            "    run: [python, verify.py]\n"
            "    outputs: [verified.txt]\n",
        )
        return load_repository(root)

    def test_repository_run_uses_one_scons_target_graph(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = self.make_repo(root)

            first = run_repository(root, items, {"item"})
            self.assertEqual(
                [row["outcome"] for row in first["targets"]],
                ["BUILT", "BUILT"],
            )

            second = run_repository(root, items, {"item"})
            self.assertEqual(
                [row["outcome"] for row in second["targets"]],
                ["CURRENT", "CURRENT"],
            )


    def test_fresh_clone_runs_only_git_affected_item(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            source = workspace / "source"
            source.mkdir()

            subprocess.run(
                ["git", "init", "--quiet"],
                cwd=source,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "cad-ci-test"],
                cwd=source,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "cad-ci-test@example.invalid"],
                cwd=source,
                check=True,
            )

            _write(source / "cad-ci.yml", "schema: 1\nitems: [a, b]\n")
            for item in ("a", "b"):
                _write(source / item / "input.txt", "base\n")
                _write(
                    source / item / "run.py",
                    "import os\n"
                    "from pathlib import Path\n"
                    "out = Path(os.environ['CAD_CI_OUTPUT'])\n"
                    "out.mkdir(parents=True, exist_ok=True)\n"
                    "(out / 'result.txt').write_text("
                    "Path(__file__).with_name('input.txt').read_text())\n",
                )
                _write(
                    source / item / "ci.yml",
                    f"id: {item}\n"
                    f"watch: [{item}/**]\n"
                    "steps:\n"
                    "  - id: build\n"
                    f"    inputs: [{item}/input.txt, {item}/run.py]\n"
                    "    run: [python, run.py]\n"
                    "    outputs: [result.txt]\n",
                )

            subprocess.run(
                ["git", "add", "."],
                cwd=source,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "--quiet", "-m", "base"],
                cwd=source,
                check=True,
            )
            base = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=source,
                text=True,
            ).strip()

            _write(source / "a" / "input.txt", "changed\n")
            subprocess.run(
                ["git", "add", "a/input.txt"],
                cwd=source,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "--quiet", "-m", "change a"],
                cwd=source,
                check=True,
            )
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=source,
                text=True,
            ).strip()

            runner = workspace / "runner"
            subprocess.run(
                ["git", "clone", "--quiet", str(source), str(runner)],
                check=True,
            )

            self.assertFalse((runner / "build").exists())
            self.assertFalse((runner / ".cache" / "cad-ci").exists())

            changed = changed_files(runner, base, head)
            self.assertEqual(changed, ("a/input.txt",))

            items = load_repository(runner)
            selected = affected_items(items, changed)
            self.assertEqual(selected, {"a"})

            report = run_repository(runner, items, selected)
            self.assertEqual(
                [(row["key"], row["outcome"]) for row in report["targets"]],
                [("a:build", "BUILT")],
            )
            self.assertEqual(
                (runner / "build" / "a" / "result.txt").read_text(),
                "changed\n",
            )
            self.assertFalse((runner / "build" / "b").exists())

    def test_partial_selectors_are_mutually_exclusive(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = self.make_repo(root)

            with self.assertRaisesRegex(
                RunError,
                "mutually exclusive",
            ):
                run_repository(
                    root,
                    items,
                    {"item"},
                    item_id="item",
                    step="build",
                    until="verify",
                )

    def test_execution_error_exposes_structured_report(self):
        self.require_scons()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "cad-ci.yml", "schema: 1\nitems: [item]\n")
            _write(
                root / "item" / "ci.yml",
                "id: item\n"
                "steps:\n"
                "  - id: fail\n"
                "    inputs: []\n"
                "    run: [python, -c, 'raise SystemExit(4)']\n",
            )
            items = load_repository(root)

            with self.assertRaises(RunError) as caught:
                run_repository(root, items, {"item"})
            self.assertIsNotNone(caught.exception.report)
            row = caught.exception.report["targets"][0]
            self.assertEqual(row["outcome"], "ERROR")
            self.assertEqual(row["exit_code"], 4)


if __name__ == "__main__":
    unittest.main()
