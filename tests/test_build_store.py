"""Build-store tests for complete baselines, sparse overlays and promotion."""

from pathlib import Path
import json
import tempfile
import unittest

from cad_ci.publication.build_store import (
    BuildStoreError,
    install_scope,
    load_manifest,
    prepare_main,
    prepare_named,
    prepare_overlay,
    promote_overlay,
    remove_pr,
    resolve_view,
    update_main,
    update_named,
)
from cad_ci.model import Item, Step
from cad_ci.scons.engine import ENGINE_SCHEMA as SCONS_ENGINE_SCHEMA


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


def evidence(item: Item, value: str, *, schema: int = 2) -> dict:
    """Return complete-item SCons evidence tied to one current Item."""

    return {
        "schema": schema,
        "engine": "scons",
        "engine_schema": SCONS_ENGINE_SCHEMA,
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
        "engine_schema": SCONS_ENGINE_SCHEMA,
        "final_step": state["final_step"],
        "final_target_spec_digest": state["final_target_spec_digest"],
        "final_bundle_sha256": state["final_bundle_sha256"],
        "outputs": sorted(
            {
                output
                for step in item.steps
                for output in step.outputs
            }
        ),
    }


def write_item(
    root: Path,
    item: Item,
    value: str,
    *,
    schema: int = 2,
) -> None:
    """Create one complete item with public SCons evidence."""

    folder = root / item.path
    folder.mkdir(parents=True)
    (folder / "result.txt").write_text(value, encoding="utf-8")
    evidence_path = folder / ".cad-ci" / "item.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        json.dumps(evidence(item, value, schema=schema)),
        encoding="utf-8",
    )


def write_main(
    root: Path,
    rows: list[tuple[Item, str]],
    *,
    source_commit: str = "main-old",
    evidence_schema: int = 2,
) -> None:
    """Create one valid complete durable main baseline."""

    for item, value in rows:
        write_item(root, item, value, schema=evidence_schema)
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

    def test_build_store_uses_current_scons_engine_schema(self):
        from cad_ci.publication import build_store
        from cad_ci.scons import engine as scons_engine

        self.assertEqual(
            build_store.ENGINE_SCHEMA,
            scons_engine.ENGINE_SCHEMA,
        )

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

    def test_update_main_removes_item_absent_from_current_configuration(self):
        """A removed configured item disappears without rebuilding survivors."""

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
            survivor_before = (
                main / "cases/item-b/result.txt"
            ).read_bytes()

            updated = root / "updated"
            manifest = update_main(
                main=main,
                candidate_root=root / "candidate",
                out=updated,
                items=[],
                current_items=[self.item_b],
                source_commit="main-new",
            )

            self.assertFalse((updated / "cases/item-a").exists())
            self.assertEqual(
                (updated / "cases/item-b/result.txt").read_bytes(),
                survivor_before,
            )
            self.assertEqual(
                set(manifest["items"]),
                {"cases/item-b"},
            )
            self.assertEqual(manifest["source_commit"], "main-new")

    def test_update_main_replaces_selected_and_removes_deleted(self):
        """Replacement and deletion happen in one validated main update."""

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

            updated = root / "updated"
            manifest = update_main(
                main=main,
                candidate_root=candidate,
                out=updated,
                items=[self.item_a],
                current_items=[self.item_a],
                source_commit="main-new",
            )

            self.assertEqual(
                (updated / "cases/item-a/result.txt").read_text(),
                "new-a",
            )
            self.assertFalse((updated / "cases/item-b").exists())
            self.assertEqual(
                set(manifest["items"]),
                {"cases/item-a"},
            )

    def test_update_main_requires_complete_current_baseline(self):
        """A current unselected item needs either baseline or replacement."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "main"
            write_main(main, [(self.item_a, "old-a")])
            out = root / "updated"
            out.mkdir()
            (out / "sentinel.txt").write_text("untouched", encoding="utf-8")

            with self.assertRaisesRegex(
                BuildStoreError,
                "current main item has no baseline or replacement",
            ):
                update_main(
                    main=main,
                    candidate_root=root / "candidate",
                    out=out,
                    items=[],
                    current_items=[self.item_a, self.item_b],
                    source_commit="main-new",
                )

            self.assertEqual(
                (out / "sentinel.txt").read_text(),
                "untouched",
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

    def test_rejects_legacy_schema_for_new_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate"
            write_item(candidate, self.item_a, "a", schema=1)

            with self.assertRaisesRegex(
                BuildStoreError,
                "unsupported current item evidence schema",
            ):
                prepare_main(
                    candidate_root=candidate,
                    out=root / "main",
                    items=[self.item_a],
                    source_commit="main-1",
                )

    def test_load_manifest_accepts_legacy_stored_item_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_main(
                root,
                [(self.item_a, "a")],
                evidence_schema=1,
            )
            manifest = load_manifest(root, expected_scope="main")
            self.assertEqual(
                manifest["items"]["cases/item-a"]["item_id"],
                "item-a",
            )

    def test_load_manifest_rejects_unknown_stored_item_evidence_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_main(root, [(self.item_a, "a")])
            path = root / self.item_a.path / ".cad-ci/item.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["schema"] = 99
            path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaisesRegex(
                BuildStoreError,
                "unsupported stored item evidence schema",
            ):
                load_manifest(root, expected_scope="main")

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


    def test_nested_parent_and_child_prepare_without_collision(self):
        """Complete main and PR scopes can contain parent and child items."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = configured_item("cases/model", "parent")
            child = configured_item("cases/model/reference", "child")
            candidate = root / "candidate"
            write_item(candidate, parent, "parent")
            write_item(candidate, child, "child")

            main = root / "main"
            main_manifest = prepare_main(
                candidate_root=candidate,
                out=main,
                items=[parent, child],
                source_commit="main-new",
            )
            self.assertEqual(
                set(main_manifest["items"]),
                {"cases/model", "cases/model/reference"},
            )
            self.assertEqual(
                main_manifest["items"]["cases/model"]["outputs"],
                ["result.txt"],
            )
            self.assertEqual(
                (main / "cases/model/result.txt").read_text(),
                "parent",
            )
            self.assertEqual(
                (main / "cases/model/reference/result.txt").read_text(),
                "child",
            )

            overlay = root / "overlay"
            overlay_manifest = prepare_overlay(
                candidate_root=candidate,
                out=overlay,
                items=[parent, child],
                source_commit="head-new",
                pull_request=7,
            )
            self.assertEqual(
                set(overlay_manifest["items"]),
                {"cases/model", "cases/model/reference"},
            )
            self.assertTrue(
                (overlay / "cases/model/.cad-ci/item.json").is_file()
            )
            self.assertTrue(
                (
                    overlay
                    / "cases/model/reference/.cad-ci/item.json"
                ).is_file()
            )

    def test_nested_child_only_overlay_does_not_import_parent(self):
        """A sparse child overlay contains no parent-owned output/evidence."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = configured_item("cases/model", "parent")
            child = configured_item("cases/model/reference", "child")
            candidate = root / "candidate"
            write_item(candidate, parent, "parent")
            write_item(candidate, child, "child")

            overlay = root / "overlay"
            prepare_overlay(
                candidate_root=candidate,
                out=overlay,
                items=[child],
                source_commit="head-new",
                pull_request=7,
            )

            self.assertFalse(
                (overlay / "cases/model/result.txt").exists()
            )
            self.assertFalse(
                (overlay / "cases/model/.cad-ci").exists()
            )
            self.assertEqual(
                (
                    overlay
                    / "cases/model/reference/result.txt"
                ).read_text(),
                "child",
            )

    def test_nested_parent_only_prepare_ignores_child_candidate_output(self):
        """Preparing a parent never copies descendant item output implicitly."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = configured_item("cases/model", "parent")
            child = configured_item("cases/model/reference", "child")
            candidate = root / "candidate"
            write_item(candidate, parent, "parent")
            write_item(candidate, child, "child")

            overlay = root / "overlay"
            prepare_overlay(
                candidate_root=candidate,
                out=overlay,
                items=[parent],
                source_commit="head-new",
                pull_request=7,
            )

            self.assertEqual(
                (overlay / "cases/model/result.txt").read_text(),
                "parent",
            )
            self.assertFalse(
                (overlay / "cases/model/reference").exists()
            )

    def test_nested_main_updates_preserve_unselected_item_bytes(self):
        """Parent-only and child-only updates preserve the nested neighbor."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = configured_item("cases/model", "parent")
            child = configured_item("cases/model/reference", "child")
            main = root / "main"
            write_main(
                main,
                [(parent, "parent-old"), (child, "child-old")],
            )

            child_result_before = (
                main / "cases/model/reference/result.txt"
            ).read_bytes()
            child_evidence_before = (
                main
                / "cases/model/reference/.cad-ci/item.json"
            ).read_bytes()

            parent_candidate = root / "parent-candidate"
            write_item(parent_candidate, parent, "parent-new")
            parent_updated = root / "parent-updated"
            update_main(
                main=main,
                candidate_root=parent_candidate,
                out=parent_updated,
                items=[parent],
                source_commit="parent-new",
            )

            self.assertEqual(
                (
                    parent_updated
                    / "cases/model/reference/result.txt"
                ).read_bytes(),
                child_result_before,
            )
            self.assertEqual(
                (
                    parent_updated
                    / "cases/model/reference/.cad-ci/item.json"
                ).read_bytes(),
                child_evidence_before,
            )

            parent_result_before = (
                parent_updated / "cases/model/result.txt"
            ).read_bytes()
            parent_evidence_before = (
                parent_updated / "cases/model/.cad-ci/item.json"
            ).read_bytes()

            child_candidate = root / "child-candidate"
            write_item(child_candidate, child, "child-new")
            child_updated = root / "child-updated"
            update_main(
                main=parent_updated,
                candidate_root=child_candidate,
                out=child_updated,
                items=[child],
                source_commit="child-new",
            )

            self.assertEqual(
                (child_updated / "cases/model/result.txt").read_bytes(),
                parent_result_before,
            )
            self.assertEqual(
                (
                    child_updated / "cases/model/.cad-ci/item.json"
                ).read_bytes(),
                parent_evidence_before,
            )
            self.assertEqual(
                (
                    child_updated
                    / "cases/model/reference/result.txt"
                ).read_text(),
                "child-new",
            )

    def test_update_main_removed_parent_preserves_current_nested_child(self):
        """Removing a parent item deletes only parent-owned durable paths."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = configured_item("cases/model", "parent")
            child = configured_item("cases/model/reference", "child")
            main = root / "main"
            write_main(
                main,
                [(parent, "parent-old"), (child, "child-old")],
            )
            child_result = (
                main / "cases/model/reference/result.txt"
            ).read_bytes()
            child_evidence = (
                main
                / "cases/model/reference/.cad-ci/item.json"
            ).read_bytes()

            updated = root / "updated"
            manifest = update_main(
                main=main,
                candidate_root=root / "candidate",
                out=updated,
                items=[],
                current_items=[child],
                source_commit="main-new",
            )

            self.assertFalse(
                (updated / "cases/model/result.txt").exists()
            )
            self.assertFalse(
                (updated / "cases/model/.cad-ci").exists()
            )
            self.assertEqual(
                (
                    updated / "cases/model/reference/result.txt"
                ).read_bytes(),
                child_result,
            )
            self.assertEqual(
                (
                    updated
                    / "cases/model/reference/.cad-ci/item.json"
                ).read_bytes(),
                child_evidence,
            )
            self.assertEqual(
                set(manifest["items"]),
                {"cases/model/reference"},
            )

    def test_update_main_rejects_ambiguous_legacy_nested_removal(self):
        """Legacy nested ownership is rejected before output mutation."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = configured_item("cases/model", "parent")
            child = configured_item("cases/model/reference", "child")
            main = root / "main"
            write_main(
                main,
                [(parent, "parent-old"), (child, "child-old")],
            )
            manifest_path = main / "build.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["items"]["cases/model"].pop("outputs")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            out = root / "updated"
            out.mkdir()
            (out / "sentinel.txt").write_text("untouched", encoding="utf-8")

            with self.assertRaisesRegex(
                BuildStoreError,
                "legacy item ownership is ambiguous in nested layout",
            ):
                update_main(
                    main=main,
                    candidate_root=root / "candidate",
                    out=out,
                    items=[],
                    current_items=[child],
                    source_commit="main-new",
                )

            self.assertEqual(
                (out / "sentinel.txt").read_text(),
                "untouched",
            )

    def test_nested_resolve_and_promote_preserve_child(self):
        """Parent overlay replacement does not erase a nested child."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = configured_item("cases/model", "parent")
            child = configured_item("cases/model/reference", "child")
            main = root / "main"
            write_main(
                main,
                [(parent, "parent-old"), (child, "child-old")],
            )

            candidate = root / "candidate"
            write_item(candidate, parent, "parent-new")
            overlay = root / "overlay"
            prepare_overlay(
                candidate_root=candidate,
                out=overlay,
                items=[parent],
                source_commit="head-new",
                pull_request=7,
            )

            resolved = root / "resolved"
            resolve_view(main=main, overlay=overlay, out=resolved)
            self.assertEqual(
                (resolved / "cases/model/result.txt").read_text(),
                "parent-new",
            )
            self.assertEqual(
                (
                    resolved / "cases/model/reference/result.txt"
                ).read_text(),
                "child-old",
            )

            promoted = root / "promoted"
            promote_overlay(
                main=main,
                overlay=overlay,
                out=promoted,
                source_commit="main-new",
            )
            self.assertEqual(
                (promoted / "cases/model/result.txt").read_text(),
                "parent-new",
            )
            self.assertEqual(
                (
                    promoted / "cases/model/reference/result.txt"
                ).read_text(),
                "child-old",
            )

    def test_legacy_nonnested_row_without_outputs_remains_readable(self):
        """Legacy schema-1 rows stay readable when ownership is unambiguous."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_main(root, [(self.item_a, "a")])
            manifest_path = root / "build.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["items"]["cases/item-a"].pop("outputs")
            manifest_path.write_text(json.dumps(manifest))

            loaded = load_manifest(root, expected_scope="main")
            self.assertEqual(
                loaded["items"]["cases/item-a"]["item_id"],
                "item-a",
            )

    def test_legacy_nested_replacement_is_rejected(self):
        """A legacy parent row may not clobber a nested stored child."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent = configured_item("cases/model", "parent")
            child = configured_item("cases/model/reference", "child")
            main = root / "main"
            write_main(
                main,
                [(parent, "parent-old"), (child, "child-old")],
            )

            candidate = root / "candidate"
            write_item(candidate, parent, "parent-new")
            overlay = root / "overlay"
            prepare_overlay(
                candidate_root=candidate,
                out=overlay,
                items=[parent],
                source_commit="head-new",
                pull_request=7,
            )
            manifest_path = overlay / "build.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["items"]["cases/model"].pop("outputs")
            manifest_path.write_text(json.dumps(manifest))

            with self.assertRaisesRegex(
                BuildStoreError,
                "legacy item ownership is ambiguous",
            ):
                resolve_view(
                    main=main,
                    overlay=overlay,
                    out=root / "resolved",
                )

    def test_named_complete_scopes_are_independent_and_reconciled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initial = root / "initial"
            write_item(initial, self.item_a, "old-a")
            write_item(initial, self.item_b, "old-b")

            main = root / "main-candidate"
            prepare_main(
                candidate_root=initial,
                out=main,
                items=[self.item_a, self.item_b],
                source_commit="main-1",
            )
            dev_a = root / "dev-a-candidate"
            manifest = prepare_named(
                candidate_root=initial,
                out=dev_a,
                items=[self.item_a, self.item_b],
                source_commit="dev-a-1",
                name="dev_a",
            )
            dev_b = root / "dev-b-candidate"
            prepare_named(
                candidate_root=initial,
                out=dev_b,
                items=[self.item_a, self.item_b],
                source_commit="dev-b-1",
                name="dev_b",
            )
            self.assertEqual(manifest["scope"], "named")
            self.assertEqual(manifest["name"], "dev_a")

            store = root / "store"
            store.mkdir()
            install_scope(candidate=main, store=store, scope="main")
            install_scope(
                candidate=dev_a,
                store=store,
                scope="named",
                scope_name="dev_a",
            )
            install_scope(
                candidate=dev_b,
                store=store,
                scope="named",
                scope_name="dev_b",
            )

            replacement = root / "replacement"
            write_item(replacement, self.item_a, "new-a")
            updated = root / "updated-dev-a"
            update_named(
                named=store / "dev_a",
                candidate_root=replacement,
                out=updated,
                items=[self.item_a],
                current_items=[self.item_a, self.item_b],
                source_commit="dev-a-2",
                name="dev_a",
            )
            install_scope(
                candidate=updated,
                store=store,
                scope="named",
                scope_name="dev_a",
            )

            self.assertEqual(
                (store / "dev_a/cases/item-a/result.txt").read_text(),
                "new-a",
            )
            self.assertEqual(
                (store / "dev_a/cases/item-b/result.txt").read_text(),
                "old-b",
            )
            self.assertEqual(
                (store / "dev_b/cases/item-a/result.txt").read_text(),
                "old-a",
            )
            self.assertEqual(
                (store / "main/cases/item-a/result.txt").read_text(),
                "old-a",
            )

    def test_named_scope_rejects_unsafe_or_reserved_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate"
            write_item(candidate, self.item_a, "a")
            for name in ("main", "pr", "../escape", "a/b", ""):
                with self.subTest(name=name):
                    with self.assertRaises(BuildStoreError):
                        prepare_named(
                            candidate_root=candidate,
                            out=root / "out",
                            items=[self.item_a],
                            source_commit="head",
                            name=name,
                        )


if __name__ == "__main__":
    unittest.main()
