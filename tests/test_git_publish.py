"""Git publication tests using a local bare repository as the remote."""

from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import cad_ci.git_publish as git_publish

from cad_ci.build_store import prepare_main, prepare_named, prepare_overlay
from cad_ci.git_publish import (
    publish_build_scope,
    publish_pages,
    publish_pages_preview_cleanup,
    materialize_generated_branch,
)
from cad_ci.pages import Page, build_site
from cad_ci.model import Item, Step


def git(cwd: Path, *args: str) -> str:
    """Return stdout from a Git command used by the test setup."""

    return subprocess.check_output(
        ["git", *args],
        cwd=cwd,
        text=True,
    ).strip()


def init_remote(root: Path) -> tuple[Path, Path]:
    """Create a source checkout with a local bare origin/main branch."""

    remote = root / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", str(remote)],
        check=True,
    )
    source = root / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=source,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=source,
        check=True,
    )
    (source / "README.md").write_text("source\n")
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "source"],
        cwd=source,
        check=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)],
        cwd=source,
        check=True,
    )
    subprocess.run(
        ["git", "push", "-q", "origin", "HEAD:main"],
        cwd=source,
        check=True,
    )
    return source, remote


def configured_item(path: str, item_id: str) -> Item:
    """Create minimal current item configuration for publication tests."""

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


def write_item(root: Path, item: Item, value: str) -> None:
    """Write one complete fake SCons item result."""

    folder = root / item.path
    folder.mkdir(parents=True)
    (folder / "result.txt").write_text(value)
    evidence = folder / ".cad-ci" / "item.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps({
        "schema": 2,
        "engine": "scons",
        "engine_schema": 1,
        "item": item.id,
        "status": "pass",
        "final_step": item.steps[-1].id,
        "final_target_spec_digest": f"spec-{value}",
        "final_bundle_sha256": f"bundle-{value}",
    }))


def branch_file(remote: Path, branch: str, path: str) -> str:
    """Read one file directly from a branch in the bare test remote."""

    return subprocess.check_output(
        [
            "git",
            f"--git-dir={remote}",
            "show",
            f"{branch}:{path}",
        ],
        text=True,
    )


class GitPublishTests(unittest.TestCase):
    def test_build_branch_keeps_independent_pr_scopes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, remote = init_remote(root)

            candidate = root / "candidate"
            item_a = configured_item("cases/a", "a")
            item_b = configured_item("cases/b", "b")
            write_item(candidate, item_a, "a")
            write_item(candidate, item_b, "b")
            main = root / "main-candidate"
            prepare_main(
                candidate_root=candidate,
                out=main,
                items=[item_a, item_b],
                source_commit="main-1",
            )
            publish_build_scope(
                source_repo=source,
                candidate=main,
                scope="main",
                message="main",
            )

            overlay_a = root / "overlay-a"
            prepare_overlay(
                candidate_root=candidate,
                out=overlay_a,
                items=[item_a],
                source_commit="pr-a",
                pull_request=1,
            )
            publish_build_scope(
                source_repo=source,
                candidate=overlay_a,
                scope="pr",
                pull_request=1,
                message="pr1",
            )

            overlay_b = root / "overlay-b"
            prepare_overlay(
                candidate_root=candidate,
                out=overlay_b,
                items=[item_b],
                source_commit="pr-b",
                pull_request=2,
            )
            publish_build_scope(
                source_repo=source,
                candidate=overlay_b,
                scope="pr",
                pull_request=2,
                message="pr2",
            )

            self.assertEqual(
                branch_file(
                    remote,
                    "build",
                    "pr/1/cases/a/result.txt",
                ),
                "a",
            )
            self.assertEqual(
                branch_file(
                    remote,
                    "build",
                    "pr/2/cases/b/result.txt",
                ),
                "b",
            )
            self.assertEqual(
                branch_file(
                    remote,
                    "build",
                    "main/cases/a/result.txt",
                ),
                "a",
            )

    def test_pages_stable_and_preview_share_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, remote = init_remote(root)
            stable = root / "stable"
            preview = root / "preview"
            build_site(
                out=stable,
                site_title="Demo",
                pages=[Page("index.html", "Home", "<p>stable</p>")],
                provenance={"source": "main"},
            )
            build_site(
                out=preview,
                site_title="Demo",
                pages=[Page("index.html", "Home", "<p>preview</p>")],
                provenance={"source": "pr"},
            )

            publish_pages(
                source_repo=source,
                site=stable,
                message="stable",
            )
            publish_pages(
                source_repo=source,
                site=preview,
                pull_request=3,
                message="preview",
            )
            self.assertIn(
                "stable",
                branch_file(remote, "gh-pages", "index.html"),
            )
            self.assertIn(
                "preview",
                branch_file(
                    remote,
                    "gh-pages",
                    "previews/pr-3/index.html",
                ),
            )

            publish_pages_preview_cleanup(
                source_repo=source,
                pull_request=3,
                message="cleanup",
            )
            files = subprocess.check_output(
                [
                    "git",
                    f"--git-dir={remote}",
                    "ls-tree",
                    "-r",
                    "--name-only",
                    "gh-pages",
                ],
                text=True,
            )
            self.assertIn("index.html", files)
            self.assertNotIn("previews/pr-3/index.html", files)

    def test_refuses_stale_source_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, remote = init_remote(root)
            expected = git(source, "rev-parse", "HEAD")
            stable = root / "stable"
            build_site(
                out=stable,
                site_title="Demo",
                pages=[Page("index.html", "Home", "ok")],
                provenance={},
            )

            # Move remote main after the run's expected source was captured.
            (source / "README.md").write_text("new source\n")
            subprocess.run(["git", "add", "."], cwd=source, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "move"],
                cwd=source,
                check=True,
            )
            subprocess.run(
                ["git", "push", "-q", "origin", "HEAD:main"],
                cwd=source,
                check=True,
            )

            with self.assertRaisesRegex(
                git_publish.GitPublishError,
                "source ref main moved",
            ):
                publish_pages(
                    source_repo=source,
                    site=stable,
                    message="stale",
                    source_ref="main",
                    expected_source=expected,
                )

    def test_retries_one_rejected_push(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, remote = init_remote(root)
            stable = root / "stable"
            build_site(
                out=stable,
                site_title="Demo",
                pages=[Page("index.html", "Home", "ok")],
                provenance={},
            )

            real_git = git_publish._git
            rejected = {"done": False}

            def one_rejection(cwd, *args, check=True):
                if args and args[0] == "push" and not rejected["done"]:
                    rejected["done"] = True
                    return subprocess.CompletedProcess(
                        ["git", *args],
                        1,
                        "",
                        "rejected non-fast-forward",
                    )
                return real_git(cwd, *args, check=check)

            with patch.object(
                git_publish,
                "_git",
                side_effect=one_rejection,
            ):
                commit = publish_pages(
                    source_repo=source,
                    site=stable,
                    message="retry",
                    retries=2,
                )
            self.assertTrue(commit)
            self.assertIn(
                "ok",
                branch_file(remote, "gh-pages", "index.html"),
            )

    def test_materializes_exact_generated_branch_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, remote = init_remote(root)

            candidate = root / "candidate"
            item_a = configured_item("cases/a", "a")
            write_item(candidate, item_a, "a")
            main = root / "main-candidate"
            prepare_main(
                candidate_root=candidate,
                out=main,
                items=[item_a],
                source_commit="main-1",
            )
            published = publish_build_scope(
                source_repo=source,
                candidate=main,
                scope="main",
                message="main",
            )

            out = root / "materialized"
            fetched = materialize_generated_branch(
                source_repo=source,
                branch="build",
                out=out,
            )

            self.assertEqual(fetched, published)
            self.assertEqual(
                (out / "main/cases/a/result.txt").read_text(),
                "a",
            )
            self.assertFalse((out / ".git").exists())

    def test_missing_generated_branch_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _ = init_remote(root)
            with self.assertRaises(git_publish.GitPublishError):
                materialize_generated_branch(
                    source_repo=source,
                    branch="missing",
                    out=root / "out",
                )

    def test_generated_branches_preserve_named_sibling_scopes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, remote = init_remote(root)
            item = configured_item("cases/a", "a")

            def prepared(label: str, name: str | None) -> Path:
                candidate = root / f"candidate-{label}"
                write_item(candidate, item, label)
                out = root / f"prepared-{label}"
                if name is None:
                    prepare_main(
                        candidate_root=candidate,
                        out=out,
                        items=[item],
                        source_commit=label,
                    )
                else:
                    prepare_named(
                        candidate_root=candidate,
                        out=out,
                        items=[item],
                        source_commit=label,
                        name=name,
                    )
                return out

            publish_build_scope(
                source_repo=source,
                candidate=prepared("main", None),
                scope="main",
                message="main",
            )
            publish_build_scope(
                source_repo=source,
                candidate=prepared("dev-a-1", "dev_a"),
                scope="named",
                scope_name="dev_a",
                message="dev a",
            )
            publish_build_scope(
                source_repo=source,
                candidate=prepared("dev-b-1", "dev_b"),
                scope="named",
                scope_name="dev_b",
                message="dev b",
            )
            publish_build_scope(
                source_repo=source,
                candidate=prepared("dev-a-2", "dev_a"),
                scope="named",
                scope_name="dev_a",
                message="dev a update",
            )

            self.assertEqual(
                branch_file(remote, "build", "main/cases/a/result.txt"),
                "main",
            )
            self.assertEqual(
                branch_file(remote, "build", "dev_a/cases/a/result.txt"),
                "dev-a-2",
            )
            self.assertEqual(
                branch_file(remote, "build", "dev_b/cases/a/result.txt"),
                "dev-b-1",
            )

    def test_pages_named_subtrees_survive_each_other_and_stable_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, remote = init_remote(root)

            def site(label: str) -> Path:
                out = root / label
                build_site(
                    out=out,
                    site_title="Demo",
                    pages=[Page("index.html", "Home", f"<p>{label}</p>")],
                    provenance={"source": label},
                )
                return out

            publish_pages(
                source_repo=source,
                site=site("stable-1"),
                message="stable 1",
            )
            publish_pages(
                source_repo=source,
                site=site("dev-a-1"),
                name="dev_a",
                message="dev a",
            )
            publish_pages(
                source_repo=source,
                site=site("dev-b-1"),
                name="dev_b",
                message="dev b",
            )
            publish_pages(
                source_repo=source,
                site=site("dev-a-2"),
                name="dev_a",
                message="dev a update",
            )
            publish_pages(
                source_repo=source,
                site=site("stable-2"),
                preserve_subtrees=("dev_a", "dev_b"),
                message="stable 2",
            )

            self.assertIn(
                "stable-2",
                branch_file(remote, "gh-pages", "index.html"),
            )
            self.assertIn(
                "dev-a-2",
                branch_file(remote, "gh-pages", "dev_a/index.html"),
            )
            self.assertIn(
                "dev-b-1",
                branch_file(remote, "gh-pages", "dev_b/index.html"),
            )


if __name__ == "__main__":
    unittest.main()
