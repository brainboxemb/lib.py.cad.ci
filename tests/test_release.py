from pathlib import Path
import tempfile
import unittest

from scripts.publish_release import release_version


class ReleaseTests(unittest.TestCase):
    def make_root(
        self,
        root: Path,
        version: str,
        package_version: str | None = None,
        changelog_version: str | None = None,
    ) -> None:
        package_version = package_version or version
        changelog_version = changelog_version or version
        (root / "VERSION").write_text(version + "\n", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            f'version = "{package_version}"\n',
            encoding="utf-8",
        )
        (root / "CHANGELOG.md").write_text(
            f"# Changelog\n\n## {changelog_version}\n",
            encoding="utf-8",
        )

    def test_release_version_checks_all_version_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_root(root, "0.2.0")
            self.assertEqual(release_version(root), "0.2.0")

    def test_invalid_version_is_not_releasable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_root(root, "0.2.0-dev")
            with self.assertRaisesRegex(ValueError, "not a release version"):
                release_version(root)

    def test_package_version_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_root(root, "0.2.0", package_version="0.2.1")
            with self.assertRaisesRegex(ValueError, "do not match"):
                release_version(root)

    def test_changelog_section_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_root(root, "0.2.0", changelog_version="0.1.3")
            with self.assertRaisesRegex(ValueError, "has no 0.2.0"):
                release_version(root)


if __name__ == "__main__":
    unittest.main()
