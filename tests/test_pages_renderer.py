from pathlib import Path
import json
import sys
import tempfile
import unittest

from cad_ci.build_store import BuildStoreError
from cad_ci.model import PagesPublication, Step
from cad_ci.pages_renderer import render_pages_builder


SHA_A = "a" * 40
SHA_B = "b" * 40


class PagesRendererTests(unittest.TestCase):
    def publication(self, command, *, outputs=("site",), timeout=None):
        return PagesPublication(
            output="site",
            builder="pages-site",
            builder_path=Path("ci/builders/pages-site"),
            builder_step=Step(
                id="render",
                run=command,
                outputs=outputs,
                timeout_seconds=timeout,
            ),
        )

    def test_renderer_receives_exact_post_build_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            complete = root / "complete"
            complete.mkdir()
            output = root / "output"

            code = (
                "import json, os\n"
                "from pathlib import Path\n"
                "site = Path(os.environ['CAD_CI_OUTPUT']) / 'site'\n"
                "site.mkdir(parents=True)\n"
                "keys = ["
                "'CAD_CI_REPO','CAD_CI_OUTPUT','CAD_CI_BUILDER',"
                "'CAD_CI_BUILDER_PATH','CAD_CI_COMPLETE_SCOPE',"
                "'CAD_CI_BUILD_SCOPE','CAD_CI_SOURCE_SHA',"
                "'CAD_CI_SOURCE_REF','CAD_CI_BUILD_COMMIT','SITE_MODE'"
                "]\n"
                "(site / 'context.json').write_text("
                "json.dumps({key: os.environ[key] for key in keys}))\n"
            )
            pages = self.publication((sys.executable, "-c", code))

            site = render_pages_builder(
                repo=repo,
                publication=pages,
                complete_scope=complete,
                build_scope="dev-ci",
                source_sha=SHA_A,
                source_ref="dev-ci",
                build_commit=SHA_B,
                output_root=output,
                variables=(("SITE_MODE", "accepted"),),
            )

            self.assertEqual(site, (output / "site").resolve())
            context = json.loads(
                (site / "context.json").read_text(encoding="utf-8")
            )
            self.assertEqual(context["CAD_CI_REPO"], str(repo.resolve()))
            self.assertEqual(context["CAD_CI_OUTPUT"], str(output.resolve()))
            self.assertEqual(context["CAD_CI_BUILDER"], "pages-site")
            self.assertEqual(
                context["CAD_CI_BUILDER_PATH"],
                str((repo / "ci/builders/pages-site").resolve()),
            )
            self.assertEqual(
                context["CAD_CI_COMPLETE_SCOPE"],
                str(complete.resolve()),
            )
            self.assertEqual(context["CAD_CI_BUILD_SCOPE"], "dev-ci")
            self.assertEqual(context["CAD_CI_SOURCE_SHA"], SHA_A)
            self.assertEqual(context["CAD_CI_SOURCE_REF"], "dev-ci")
            self.assertEqual(context["CAD_CI_BUILD_COMMIT"], SHA_B)
            self.assertEqual(context["SITE_MODE"], "accepted")

    def test_renderer_rejects_nonzero_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            complete = root / "complete"
            complete.mkdir()

            pages = self.publication(
                (sys.executable, "-c", "raise SystemExit(3)")
            )
            with self.assertRaisesRegex(
                BuildStoreError,
                "failed with exit 3",
            ):
                render_pages_builder(
                    repo=repo,
                    publication=pages,
                    complete_scope=complete,
                    build_scope="main",
                    source_sha=SHA_A,
                    source_ref="main",
                    build_commit=SHA_B,
                    output_root=root / "output",
                )

    def test_renderer_rejects_missing_declared_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            complete = root / "complete"
            complete.mkdir()

            pages = self.publication(
                (sys.executable, "-c", "print('no site')")
            )
            with self.assertRaisesRegex(
                BuildStoreError,
                "invalid output",
            ):
                render_pages_builder(
                    repo=repo,
                    publication=pages,
                    complete_scope=complete,
                    build_scope="main",
                    source_sha=SHA_A,
                    source_ref="main",
                    build_commit=SHA_B,
                    output_root=root / "output",
                )


if __name__ == "__main__":
    unittest.main()
