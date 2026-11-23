"""Tests for SCons-supplied direct dependency runtime context."""

from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from cad_ci.config import load_repository
from cad_ci.context import ContextError, current_context
from cad_ci.scons.bundle import bundle_sha256
from cad_ci.scons.engine import (
    resolve_request,
    run_scons,
    target_specs,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class DependencyContextTests(unittest.TestCase):
    def make_repo(self, root: Path):
        _write(
            root / "cad-ci.yml",
            "schema: 1\nitems: [producer, consumer]\n",
        )
        _write(
            root / "producer" / "run.py",
            """import os
from pathlib import Path
out = Path(os.environ["CAD_CI_OUTPUT"])
out.mkdir(parents=True, exist_ok=True)
(out / "result.txt").write_text("ok\\n")
""",
        )
        _write(
            root / "producer" / "ci.yml",
            "id: producer\n"
            "steps:\n"
            "  - id: run\n"
            "    inputs: [producer/run.py]\n"
            "    run: [python, run.py]\n"
            "    outputs: [result.txt]\n",
        )
        _write(
            root / "consumer" / "run.py",
            "print('consumer')\n",
        )
        _write(
            root / "consumer" / "ci.yml",
            "id: consumer\n"
            "needs: [producer]\n"
            "steps:\n"
            "  - id: run\n"
            "    inputs: [consumer/run.py]\n"
            "    run: [python, run.py]\n"
            "    outputs: []\n",
        )
        return load_repository(root)

    def producer_context_row(self, root: Path, items: dict) -> dict:
        specs = target_specs(root, items)
        producer = next(
            spec
            for spec in specs
            if spec["key"] == "producer:run"
        )
        bundle = root / producer["bundle"]
        return {
            "output_root": str((root / "build/producer").resolve()),
            "outputs": ["result.txt"],
            "final_bundle": str(bundle.resolve()),
            "final_bundle_sha256": bundle_sha256(bundle),
        }

    def prepare(self, root: Path) -> tuple[dict, dict]:
        items = self.make_repo(root)
        request = resolve_request(
            items,
            {"producer"},
            item_id="producer",
        )
        run_scons(root, items, request)
        return items, self.producer_context_row(root, items)

    def environment(self, root: Path, row: dict) -> dict[str, str]:
        return {
            "CAD_CI_REPO": str(root),
            "CAD_CI_ITEM": "consumer",
            "CAD_CI_OUTPUT": str(root / "build/consumer"),
            "CAD_CI_DEPENDENCIES_JSON": json.dumps(
                {"producer": row}
            ),
        }

    def test_context_exposes_only_declared_dependency_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, row = self.prepare(root)
            with patch.dict(
                os.environ,
                self.environment(root, row),
                clear=False,
            ):
                context = current_context()
                dependency = context.dependency("producer")
                self.assertEqual(
                    dependency.output("result.txt").read_text(),
                    "ok\n",
                )
                self.assertEqual(
                    dependency.bundle_sha256,
                    row["final_bundle_sha256"],
                )
                with self.assertRaisesRegex(
                    ContextError,
                    "does not declare",
                ):
                    dependency.output("other.txt")

    def test_context_rejects_undeclared_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, row = self.prepare(root)
            with patch.dict(
                os.environ,
                self.environment(root, row),
                clear=False,
            ):
                context = current_context()
                with self.assertRaisesRegex(
                    ContextError,
                    "does not directly depend",
                ):
                    context.dependency("consumer")

    def test_context_rejects_tampered_dependency_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, row = self.prepare(root)
            (root / "build/producer/result.txt").write_text(
                "tampered\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                self.environment(root, row),
                clear=False,
            ):
                with self.assertRaisesRegex(
                    ContextError,
                    "does not match its SCons bundle",
                ):
                    current_context()

    def test_context_rejects_wrong_bundle_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, row = self.prepare(root)
            row["final_bundle_sha256"] = "0" * 64
            with patch.dict(
                os.environ,
                self.environment(root, row),
                clear=False,
            ):
                with self.assertRaisesRegex(
                    ContextError,
                    "bundle digest does not match",
                ):
                    current_context()

    def test_context_requires_runtime_dependency_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare(root)
            with patch.dict(
                os.environ,
                {
                    "CAD_CI_REPO": str(root),
                    "CAD_CI_ITEM": "consumer",
                    "CAD_CI_DEPENDENCIES_JSON": "",
                },
                clear=False,
            ):
                with self.assertRaisesRegex(
                    ContextError,
                    "CAD_CI_DEPENDENCIES_JSON is required",
                ):
                    current_context()


if __name__ == "__main__":
    unittest.main()
