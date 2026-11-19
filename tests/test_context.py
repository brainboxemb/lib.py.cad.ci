"""Tests for validated consumer dependency context."""

from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from cad_ci.config import load_repository
from cad_ci.context import ContextError, current_context
from cad_ci.runner import run_item


def write_item(
    repo: Path,
    path: str,
    item_id: str,
    *,
    needs: tuple[str, ...] = (),
    output: str = "result.txt",
) -> None:
    """Create one tiny item whose step writes a declared text output."""

    folder = repo / path
    folder.mkdir(parents=True)
    needs_yaml = (
        "needs:\n" + "".join(f"  - {value}\n" for value in needs)
        if needs else ""
    )
    (folder / "ci.yml").write_text(
        f"id: {item_id}\n"
        f"{needs_yaml}"
        "steps:\n"
        "  - id: run\n"
        "    run: [python, run.py]\n"
        f"    outputs: [{output}]\n",
        encoding="utf-8",
    )
    (folder / "run.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "out = Path(os.environ['CAD_CI_OUTPUT'])\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        f"(out / {output!r}).write_text('ok\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )


class DependencyContextTests(unittest.TestCase):
    def make_repo(self, root: Path):
        (root / "cad-ci.yml").write_text(
            "schema: 1\nitems: [producer, consumer]\n",
            encoding="utf-8",
        )
        write_item(root, "producer", "producer")
        write_item(root, "consumer", "consumer", needs=("producer",), output="summary.txt")
        return load_repository(root)

    def test_context_exposes_only_declared_dependency_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            items = self.make_repo(repo)
            run_item(repo, items["producer"], items)
            context = current_context(repo=repo, item_id="consumer")
            self.assertEqual(context.output, repo / "build/consumer")
            dependency = context.dependency("producer")
            self.assertEqual(
                dependency.output("result.txt").read_text(encoding="utf-8"),
                "ok\n",
            )
            with self.assertRaisesRegex(ContextError, "does not declare"):
                dependency.output("item.json")

    def test_context_rejects_undeclared_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            items = self.make_repo(repo)
            run_item(repo, items["producer"], items)
            context = current_context(repo=repo, item_id="consumer")
            with self.assertRaisesRegex(ContextError, "does not directly depend"):
                context.dependency("consumer")

    def test_context_rejects_stale_dependency_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            items = self.make_repo(repo)
            run_item(repo, items["producer"], items)
            (repo / "build/producer/result.txt").write_text(
                "tampered\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ContextError, "current result"):
                current_context(repo=repo, item_id="consumer")

    def test_environment_is_used_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            items = self.make_repo(repo)
            run_item(repo, items["producer"], items)
            with patch.dict(
                os.environ,
                {"CAD_CI_REPO": str(repo), "CAD_CI_ITEM": "consumer"},
                clear=False,
            ):
                context = current_context()
            self.assertEqual(context.item.id, "consumer")


if __name__ == "__main__":
    unittest.main()
