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
    configured_pages_site,
    fetch_durable_scope_state,
    publish_durable_pages,
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
                missing_ok=True,
            )

    def test_fetch_uses_selected_generated_build_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            out = root / "generated"

            with patch(
                "cad_ci.durable.materialize_generated_branch",
                return_value=None,
            ) as materialize:
                state = fetch_durable_scope_state(
                    repo=repo,
                    generated_build=out,
                    scope="dev-ci",
                    source_sha=SHA_A,
                    branch="test-output/build",
                )

            self.assertTrue(state.full_run)
            materialize.assert_called_once_with(
                source_repo=repo.resolve(),
                branch="test-output/build",
                out=out.resolve(),
                remote="origin",
                missing_ok=True,
            )

    def test_fetch_missing_generated_branch_allows_first_main_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            out = root / "generated"

            with patch(
                "cad_ci.durable.materialize_generated_branch",
                return_value=None,
            ):
                state = fetch_durable_scope_state(
                    repo=repo,
                    generated_build=out,
                    scope="main",
                    source_sha=SHA_A,
                )

            self.assertEqual(
                state,
                DurableScopeState(
                    scope="main",
                    base_sha=SHA_A,
                    full_run=True,
                    exists=False,
                ),
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
                    build_branch="test-output/build",
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
            self.assertEqual(publish_args["branch"], "test-output/build")

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

    def test_first_main_scope_prepares_complete_processed_membership(self):
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
            state = DurableScopeState("main", SHA_A, True, False)
            with (
                patch("cad_ci.durable.load_repository", return_value=items),
                patch("cad_ci.durable.affected_items", return_value={"a", "b"}),
                patch("cad_ci.durable.prepare_main") as prepare_main,
                patch("cad_ci.durable.update_main") as update_main,
                patch("cad_ci.durable.publish_build_scope", return_value=SHA_C),
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

            update_main.assert_not_called()
            prepare_main.assert_called_once()
            self.assertEqual(
                prepare_main.call_args.kwargs["items"],
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
            self.assertEqual(publish.call_args.kwargs["branch"], "build")

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


class PublishDurablePagesTests(unittest.TestCase):
    def repository(self, *, pages=True):
        from types import SimpleNamespace

        return SimpleNamespace(
            items={"site": SimpleNamespace(path=Path("site"))},
            pages=(
                SimpleNamespace(item="site", output="site")
                if pages
                else None
            ),
        )

    def test_configured_pages_site_resolves_complete_scope_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = root / "scope"
            site = scope / "site" / "site"
            site.mkdir(parents=True)

            with patch(
                "cad_ci.durable.load_repository_config",
                return_value=self.repository(),
            ):
                self.assertEqual(
                    configured_pages_site(root / "repo", scope),
                    site.resolve(),
                )

    def test_stable_pages_preserves_valid_named_build_scopes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            prepared = root / "prepared"
            site = prepared / "site" / "site"
            site.mkdir(parents=True)
            (site / "index.html").write_text("stable", encoding="utf-8")

            generated = root / "generated"
            for name in ("dev-cad", "dev-ci"):
                scope = generated / name
                scope.mkdir(parents=True)
                (scope / "build.json").write_text(
                    json.dumps(
                        {
                            "schema": 1,
                            "scope": "named",
                            "name": name,
                            "source_commit": SHA_B,
                            "items": {},
                        }
                    ),
                    encoding="utf-8",
                )

            def publish(**kwargs):
                provenance = json.loads(
                    (kwargs["site"] / "provenance.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(provenance["source_commit"], SHA_A)
                self.assertEqual(provenance["build_commit"], SHA_C)
                self.assertEqual(provenance["build_scope"], "main")
                self.assertEqual(
                    kwargs["preserve_subtrees"],
                    ("dev-cad", "dev-ci"),
                )
                self.assertIsNone(kwargs["name"])
                self.assertEqual(kwargs["branch"], "test-output/gh-pages")
                return SHA_B

            with (
                patch(
                    "cad_ci.durable.load_repository_config",
                    return_value=self.repository(),
                ),
                patch("cad_ci.durable.publish_pages", side_effect=publish),
            ):
                result = publish_durable_pages(
                    repo=repo,
                    generated_build=generated,
                    prepared_scope=prepared,
                    state=DurableScopeState("main", SHA_B, False, True),
                    source_sha=SHA_A,
                    source_ref="main",
                    build_commit=SHA_C,
                    pages_branch="test-output/gh-pages",
                )

            self.assertEqual(result, SHA_B)

    def test_named_pages_replaces_only_named_subtree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            prepared = root / "prepared"
            site = prepared / "site" / "site"
            site.mkdir(parents=True)
            (site / "index.html").write_text("dev", encoding="utf-8")

            with (
                patch(
                    "cad_ci.durable.load_repository_config",
                    return_value=self.repository(),
                ),
                patch(
                    "cad_ci.durable.publish_pages",
                    return_value=SHA_B,
                ) as publish,
            ):
                result = publish_durable_pages(
                    repo=repo,
                    generated_build=root / "generated",
                    prepared_scope=prepared,
                    state=DurableScopeState("dev-ci", SHA_A, True, False),
                    source_sha=SHA_A,
                    source_ref="dev-ci",
                    build_commit=SHA_C,
                )

            self.assertEqual(result, SHA_B)
            kwargs = publish.call_args.kwargs
            self.assertEqual(kwargs["name"], "dev-ci")
            self.assertEqual(kwargs["preserve_subtrees"], ())
            self.assertEqual(kwargs["branch"], "gh-pages")

    def test_no_configured_pages_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()

            with (
                patch(
                    "cad_ci.durable.load_repository_config",
                    return_value=self.repository(pages=False),
                ),
                patch("cad_ci.durable.publish_pages") as publish,
            ):
                result = publish_durable_pages(
                    repo=repo,
                    generated_build=root / "generated",
                    prepared_scope=root / "prepared",
                    state=DurableScopeState("main", SHA_A, True, False),
                    source_sha=SHA_A,
                    source_ref="main",
                    build_commit=SHA_C,
                )

            self.assertIsNone(result)
            publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
