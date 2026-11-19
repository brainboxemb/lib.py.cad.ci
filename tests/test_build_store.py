"""Build-store tests for complete baselines, sparse overlays and promotion."""

from pathlib import Path
import json
import tempfile
import unittest

from cad_ci.build_store import (
    BuildStoreError,
    install_scope,
    load_manifest,
    prepare_main,
    prepare_overlay,
    promote_overlay,
    remove_pr,
    resolve_view,
    update_main,
)
from cad_ci.model import Item, Step


def configured_item(path: str, item_id: str) -> Item:
    """Create the minimal current configuration needed for store validation."""

    rel = Path(path)
    return Item(
        id=item_id,
        path=rel,
        kind="case",
        needs=(),
        watch=(f"{rel.as_posix()}/**",),
        affected="changed",
        reuse=True,
        steps=(
            Step(
                id="verify",
                run=("python", "-c", "print(1)"),
                outputs=("result.txt",),
            ),
        ),
        config_path=rel / "ci.yml",
        config_data={"id": item_id},
    )


def evidence(item: Item, value: str) -> dict:
    """Return complete-item SCons evidence tied to one current Item."""

    return {
        "schema": 1,
        "engine": "scons",
        "engine_schema": 1,
        "item": item.id,
        "status": "pass",
        "final_step": item.steps[-1].id,
        "final_target_spec_digest": f"spec-{value}",
        "final_bundle_sha256": f"bundle-{value}",
    }


def manifest_row(item: Item, value: str, source_commit: str) -> dict:
    """Return the durable row corresponding to evidence()."""

    state = evidence(item, value)
    return {
        "source_commit": source_commit,
        "item_id": item.id,
        "engine": "scons",
        "engine_schema": 1,
        "final_step": state["final_step"],
        "final_target_spec_digest": state["final_target_spec_digest"],
        "final_bundle_sha256": state["final_bundle_sha256"],
    }


def write_item(root: Path, item: Item, value: str) -> None:
    """Create one complete candidate item with public SCons evidence."""

    folder = root / item.path
    folder.mkdir(parents=True)
    (folder / "result.txt").write_text(value, encoding="utf-8")
    evidence_path = folder / ".cad-ci" / "item.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        json.dumps(evidence(item, value)),
        encoding="utf-8",
    )


def write_main(
    root: Path,
    rows: list[tuple[Item, str]],
    *,
    source_commit: str = "main-old",
) -> None:
    """Create one valid complete durable main baseline."""

    for item, value in rows:
        write_item(root, item, value)
    manifest = {
        "schema": 1,
        "scope": "main",
        "source_commit": source_commit,
        "items": {
            item.path.as_posix(): manifest_row(
                item,
                value,
                source_commit,
            )
            for item, value in rows
        },
    }
    (root / "build.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


class BuildStoreTests(unittest.TestCase):
    def setUp(self):
        self.item_a = configured_item("cases/item-a", "item-a")
        self.item_b = configured_item("cases/item-b", "item-b")

    def test_prepare_main_bootstraps_complete_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate"
            write_item(candidate, self.item_a, "a")
            write_item(candidate, self.item_b, "b")

            main = root / "main"
            manifest = prepare_main(
                candidate_root=candidate,
                out=main,
                items=[self.item_a, self.item_b],
                source_commit="main-1",
            )

            self.assertEqual(manifest["scope"], "main")
            self.assertEqual(
                set(manifest["items"]),
                {"cases/item-a", "cases/item-b"},
            )
            self.assertEqual(
                manifest["items"]["cases/item-a"]["item_id"],
                "item-a",
            )
            self.assertFalse((main / ".cache").exists())

    def test_overlay_is_sparse_and_keeps_source_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate"
            write_item(candidate, self.item_a, "new-a")
            write_item(candidate, self.item_b, "new-b")

            overlay = root / "overlay"
            manifest = prepare_overlay(
                candidate_root=candidate,
                out=overlay,
                items=[self.item_a],
                source_commit="head-1",
                pull_request=7,
            )

            self.assertEqual(set(manifest["items"]), {"cases/item-a"})
            self.assertTrue((overlay / "cases/item-a/result.txt").is_file())
            self.assertFalse((overlay / "cases/item-b").exists())

    def test_resolve_overlays_only_selected_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "main"
            write_main(
                main,
                [
                    (self.item_a, "old-a"),
                    (self.item_b, "old-b"),
                ],
            )

            candidate = root / "candidate"
            write_item(candidate, self.item_a, "new-a")
            overlay = root / "overlay"
            prepare_overlay(
                candidate_root=candidate,
                out=overlay,
                items=[self.item_a],
                source_commit="head-1",
                pull_request=7,
            )

            resolved = root / "resolved"
            resolve_view(main=main, overlay=overlay, out=resolved)
            self.assertEqual(
                (resolved / "cases/item-a/result.txt").read_text(),
                "new-a",
            )
            self.assertEqual(
                (resolved / "cases/item-b/result.txt").read_text(),
                "old-b",
            )

    def test_promotion_preserves_unaffected_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "main"
            write_main(
                main,
                [
                    (self.item_a, "old-a"),
                    (self.item_b, "old-b"),
                ],
            )

            candidate = root / "candidate"
            write_item(candidate, self.item_a, "new-a")
            overlay = root / "overlay"
            prepare_overlay(
                candidate_root=candidate,
                out=overlay,
                items=[self.item_a],
                source_commit="head-1",
                pull_request=7,
            )

            promoted = root / "promoted"
            manifest = promote_overlay(
                main=main,
                overlay=overlay,
                out=promoted,
                source_commit="main-new",
            )
            self.assertEqual(
                (promoted / "cases/item-a/result.txt").read_text(),
                "new-a",
            )
            self.assertEqual(
                (promoted / "cases/item-b/result.txt").read_text(),
                "old-b",
            )
            self.assertEqual(manifest["source_commit"], "main-new")

    def test_update_main_replaces_only_selected_item(self):
        """A partial main update preserves the unrelated baseline bytes."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "main"
            write_main(
                main,
                [
                    (self.item_a, "old-a"),
                    (self.item_b, "old-b"),
                ],
            )
            sibling_before = (
                main / "cases/item-b/result.txt"
            ).read_bytes()

            candidate = root / "candidate"
            write_item(candidate, self.item_a, "new-a")

            updated = root / "updated"
            manifest = update_main(
                main=main,
                candidate_root=candidate,
                out=updated,
                items=[self.item_a],
                source_commit="main-new",
            )

            self.assertEqual(
                (updated / "cases/item-a/result.txt").read_text(),
                "new-a",
            )
            self.assertEqual(
                (updated / "cases/item-b/result.txt").read_bytes(),
                sibling_before,
            )
            self.assertEqual(
                manifest["items"]["cases/item-b"],
                load_manifest(main)["items"]["cases/item-b"],
            )
            self.assertEqual(
                manifest["items"]["cases/item-a"]["source_commit"],
                "main-new",
            )

    def test_update_main_validates_all_replacements_before_writing(self):
        """A missing selected result leaves the existing output untouched."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "main"
            write_main(main, [(self.item_a, "old-a")])

            out = root / "updated"
            out.mkdir()
            (out / "sentinel.txt").write_text(
                "untouched",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                BuildStoreError,
                "missing candidate item",
            ):
                update_main(
                    main=main,
                    candidate_root=root / "candidate",
                    out=out,
                    items=[self.item_a],
                    source_commit="main-new",
                )

            self.assertEqual(
                (out / "sentinel.txt").read_text(),
                "untouched",
            )

    def test_install_and_cleanup_pr_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate"
            write_item(candidate, self.item_a, "new-a")

            overlay = root / "overlay"
            prepare_overlay(
                candidate_root=candidate,
                out=overlay,
                items=[self.item_a],
                source_commit="head-1",
                pull_request=7,
            )

            store = root / "store"
            target = install_scope(
                candidate=overlay,
                store=store,
                scope="pr",
                pull_request=7,
            )
            self.assertEqual(load_manifest(target)["pull_request"], 7)
            self.assertTrue(remove_pr(store=store, pull_request=7))
            self.assertFalse(remove_pr(store=store, pull_request=7))

    def test_rejects_candidate_without_complete_item_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate" / self.item_a.path
            candidate.mkdir(parents=True)
            evidence_path = candidate / ".cad-ci" / "item.json"
            evidence_path.parent.mkdir(parents=True)
            broken = evidence(self.item_a, "x")
            broken["status"] = "fail"
            evidence_path.write_text(
                json.dumps(broken),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                BuildStoreError,
                "not complete/pass",
            ):
                prepare_overlay(
                    candidate_root=root / "candidate",
                    out=root / "overlay",
                    items=[self.item_a],
                    source_commit="x",
                    pull_request=1,
                )

    def test_rejects_candidate_when_final_step_no_longer_matches_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate"
            write_item(candidate, self.item_a, "x")
            path = candidate / self.item_a.path / ".cad-ci/item.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["final_step"] = "old-step"
            path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(
                BuildStoreError,
                "final step does not match config",
            ):
                prepare_main(
                    candidate_root=candidate,
                    out=root / "main",
                    items=[self.item_a],
                    source_commit="x",
                )

    def test_load_manifest_rejects_row_evidence_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_main(root, [(self.item_a, "a")])
            manifest_path = root / "build.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["items"]["cases/item-a"][
                "final_bundle_sha256"
            ] = "wrong"
            manifest_path.write_text(json.dumps(manifest))

            with self.assertRaisesRegex(
                BuildStoreError,
                "does not match evidence",
            ):
                load_manifest(root)


if __name__ == "__main__":
    unittest.main()
