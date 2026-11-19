"""Tests for the thin public SCons-backed execution API."""

from pathlib import Path
import shutil
import tempfile
import unittest

from cad_ci.config import load_repository
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
