"""Tests for generic durable complete-scope orchestration."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cad_ci.build_store import BuildStoreError
from cad_ci.durable import (
    DurableScopeState,
    fetch_durable_scope_state,
    publish_durable_scope,
    resolve_durable_scope_state,
)


SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


class ResolveDurableScopeTests(unittest.TestCase):
    def test_missing_named_scope_requires_full_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = resolve_durable_scope_state(
                generated_build=Path(tmp),
                scope="dev-cad",
                source_sha=SHA_A,
            )
        self.assertEqual(
            state,
            DurableScopeState(
                scope="dev-cad",
                base_sha=SHA_A,
                full_run=True,
                exists=False,
            ),
        )

    def test_missing_main_scope_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(BuildStoreError, "main scope is missing"):
                resolve_durable_scope_state(
                    generated_build=Path(tmp),
                    scope="main",
                    source_sha=SHA_A,
                )

    def test_reserved_pr_scope_uses_build_store_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(BuildStoreError, "unsafe scope name"):
                resolve_durable_scope_state(
                    generated_build=Path(tmp),
                    scope="pr",
                    source_sha=SHA_A,
                )

    def test_existing_named_scope_uses_manifest_source_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dev-ci"
            root.mkdir()
            (root / "build.json").write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "scope": "named",
                        "name": "dev-ci",
                        "source_commit": SHA_B,
                        "items": {},
                    }
                ),
                encoding="utf-8",
            )
            state = resolve_durable_scope_state(
                generated_build=Path(tmp),
                scope="dev-ci",
                source_sha=SHA_A,
            )
        self.assertEqual(state.scope, "dev-ci")
        self.assertEqual(state.base_sha, SHA_B)
        self.assertFalse(state.full_run)
        self.assertTrue(state.exists)

    def test_existing_scope_rejects_invalid_source_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dev"
            root.mkdir()
            (root / "build.json").write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "scope": "named",
                        "name": "dev",
                        "source_commit": "main",
                        "items": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(BuildStoreError, "stored source_commit"):
                resolve_durable_scope_state(
                    generated_build=Path(tmp),
                    scope="dev",
                    source_sha=SHA_A,
                )

    def test_fetch_materializes_branch_then_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            out = Path(tmp) / "generated"
            out.mkdir()
            (out / "stale").write_text("stale", encoding="utf-8")

            def materialize(**kwargs):
                self.assertFalse((kwargs["out"] / "stale").exists())
                root = kwargs["out"] / "lane"
                root.mkdir(parents=True)
                (root / "build.json").write_text(
                    json.dumps(
                        {
                            "schema": 1,
                            "scope": "named",
                            "name": "lane",
                            "source_commit": SHA_B,
                            "items": {},
                        }
                    ),
                    encoding="utf-8",
                )
                return SHA_C

            with patch("cad_ci.durable.materialize_generated_branch", side_effect=materialize) as call:
                state = fetch_durable_scope_state(
                    repo=repo,
                    generated_build=out,
                    scope="lane",
                    source_sha=SHA_A,
                )
            self.assertEqual(state.base_sha, SHA_B)
            call.assert_called_once_with(
                source_repo=repo.resolve(),
                branch="build",
                out=out.resolve(),
                remote="origin",
            )


class PublishDurableScopeTests(unittest.TestCase):
    def test_existing_named_scope_updates_selected_items_then_publishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            generated = root / "generated"
            (generated / "lane").mkdir(parents=True)
            candidate = root / "build"
            candidate.mkdir()
            prepared = root / "prepared"

            items = {"a": "ITEM-A", "b": "ITEM-B"}
            state = DurableScopeState("lane", SHA_B, False, True)
            with (
                patch("cad_ci.durable.load_repository", return_value=items),
                patch("cad_ci.durable.changed_files", return_value=("models/a.sc",)) as changed,
                patch("cad_ci.durable.affected_items", side_effect=[{"a"}, {"a", "b"}]),
                patch("cad_ci.durable.update_named") as update_named,
                patch("cad_ci.durable.update_main") as update_main,
                patch("cad_ci.durable.prepare_named") as prepare_named,
                patch("cad_ci.durable.publish_build_scope", return_value=SHA_C) as publish,
            ):
                result = publish_durable_scope(
                    repo=repo,
                    generated_build=generated,
                    prepared_scope=prepared,
                    candidate_root=candidate,
                    state=state,
                    source_sha=SHA_A,
                    source_ref="dev-cad",
                )

            self.assertEqual(result, SHA_C)
            changed.assert_called_once_with(repo.resolve(), SHA_B, SHA_A)
            update_main.assert_not_called()
            prepare_named.assert_not_called()
            update_named.assert_called_once()
            kwargs = update_named.call_args.kwargs
            self.assertEqual(kwargs["items"], ("ITEM-A",))
            self.assertEqual(kwargs["current_items"], ("ITEM-A", "ITEM-B"))
            self.assertEqual(kwargs["name"], "lane")
            publish.assert_called_once()
            publish_args = publish.call_args.kwargs
            self.assertEqual(publish_args["scope"], "named")
            self.assertEqual(publish_args["scope_name"], "lane")
            self.assertEqual(publish_args["expected_source"], SHA_A)
            self.assertEqual(publish_args["source_ref"], "dev-cad")

    def test_first_named_scope_prepares_complete_processed_membership(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            generated = root / "generated"
            generated.mkdir()
            candidate = root / "build"
            candidate.mkdir()
            prepared = root / "prepared"

            items = {"a": "ITEM-A", "b": "ITEM-B"}
            state = DurableScopeState("lane", SHA_A, True, False)
            with (
                patch("cad_ci.durable.load_repository", return_value=items),
                patch("cad_ci.durable.affected_items", return_value={"a", "b"}),
                patch("cad_ci.durable.prepare_named") as prepare_named,
                patch("cad_ci.durable.update_named") as update_named,
                patch("cad_ci.durable.publish_build_scope", return_value=SHA_C),
            ):
                publish_durable_scope(
                    repo=repo,
                    generated_build=generated,
                    prepared_scope=prepared,
                    candidate_root=candidate,
                    state=state,
                    source_sha=SHA_A,
                    source_ref="dev-ci",
                )

            update_named.assert_not_called()
            prepare_named.assert_called_once()
            self.assertEqual(
                prepare_named.call_args.kwargs["items"],
                ("ITEM-A", "ITEM-B"),
            )

    def test_main_scope_uses_main_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            generated = root / "generated"
            (generated / "main").mkdir(parents=True)
            candidate = root / "build"
            candidate.mkdir()
            prepared = root / "prepared"

            state = DurableScopeState("main", SHA_B, False, True)
            with (
                patch("cad_ci.durable.load_repository", return_value={"a": "ITEM-A"}),
                patch("cad_ci.durable.changed_files", return_value=("x",)),
                patch("cad_ci.durable.affected_items", side_effect=[{"a"}, {"a"}]),
                patch("cad_ci.durable.update_main") as update_main,
                patch("cad_ci.durable.update_named") as update_named,
                patch("cad_ci.durable.publish_build_scope", return_value=SHA_C) as publish,
            ):
                publish_durable_scope(
                    repo=repo,
                    generated_build=generated,
                    prepared_scope=prepared,
                    candidate_root=candidate,
                    state=state,
                    source_sha=SHA_A,
                    source_ref="main",
                )

            update_main.assert_called_once()
            update_named.assert_not_called()
            self.assertEqual(publish.call_args.kwargs["scope"], "main")
            self.assertIsNone(publish.call_args.kwargs["scope_name"])

    def test_inconsistent_state_fails_before_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            state = DurableScopeState("lane", SHA_A, True, True)
            with patch("cad_ci.durable.publish_build_scope") as publish:
                with self.assertRaisesRegex(BuildStoreError, "cannot require a full run"):
                    publish_durable_scope(
                        repo=repo,
                        generated_build=root / "generated",
                        prepared_scope=root / "prepared",
                        candidate_root=root / "build",
                        state=state,
                        source_sha=SHA_A,
                        source_ref="lane",
                    )
            publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
