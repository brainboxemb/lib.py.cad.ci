from pathlib import Path
import tempfile
import unittest

from cad_ci.config import ConfigError, load_repository


class ConfigTests(unittest.TestCase):
    def test_glob_discovers_item_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text("schema: 1\nitems: [qualification/*]\n")
            for name in ("a", "b"):
                folder = repo / "qualification" / name
                folder.mkdir(parents=True)
                (folder / "ci.yml").write_text(
                    f"id: {name}\nsteps:\n  - id: test\n    run: [python, -c, 'print(1)']\n"
                )
            items = load_repository(repo)
            self.assertEqual(set(items), {"a", "b"})
            self.assertEqual(items["a"].watch, ("qualification/a/**",))

    def test_loads_items_and_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text("schema: 1\nitems: [a, b]\n")
            for name, extra in (("a", ""), ("b", "needs: [a]\n")):
                folder = repo / name
                folder.mkdir()
                (folder / "ci.yml").write_text(
                    f"id: {name}\n{extra}watch: [{name}/**]\nsteps:\n  - id: test\n    run: [python, -c, 'print(1)']\n"
                )
            items = load_repository(repo)
            self.assertEqual(items["b"].needs, ("a",))


    def test_root_variables_are_validated_and_shared_by_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\n"
                "variables:\n"
                "  Z_MODE: two\n"
                "  MODEL_MODE: one\n"
                "items: [a]\n",
                encoding="utf-8",
            )
            folder = repo / "a"
            folder.mkdir()
            (folder / "ci.yml").write_text(
                "id: a\n"
                "steps: [{id: test, run: [python, -c, 'print(1)']}]\n",
                encoding="utf-8",
            )

            item = load_repository(repo)["a"]
            self.assertEqual(
                item.variables,
                (("MODEL_MODE", "one"), ("Z_MODE", "two")),
            )

    def test_rejects_invalid_repository_variables(self):
        cases = (
            ("variables: {lower_case: value}\n", "variable name"),
            ("variables: {GITHUB_TOKEN: value}\n", "reserved variable"),
            ("variables: {CAD_CI_OUTPUT: value}\n", "reserved variable"),
            ("variables: {COUNT: 3}\n", "must be a string"),
        )

        for variable_yaml, expected in cases:
            with self.subTest(variable_yaml=variable_yaml):
                with tempfile.TemporaryDirectory() as tmp:
                    repo = Path(tmp)
                    (repo / "cad-ci.yml").write_text(
                        "schema: 1\n"
                        + variable_yaml
                        + "items: [a]\n",
                        encoding="utf-8",
                    )
                    folder = repo / "a"
                    folder.mkdir()
                    (folder / "ci.yml").write_text(
                        "id: a\n"
                        "steps: [{id: test, run: [python, -c, 'print(1)']}]\n",
                        encoding="utf-8",
                    )

                    with self.assertRaisesRegex(ConfigError, expected):
                        load_repository(repo)

    def test_process_defaults_true_and_accepts_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text("schema: 1\nitems: [a, b]\n")
            for name, process in (("a", ""), ("b", "process: false\n")):
                folder = repo / name
                folder.mkdir()
                (folder / "ci.yml").write_text(
                    f"id: {name}\n{process}steps: [{{id: test, run: [python, -c, 'print(1)']}}]\n"
                )
            items = load_repository(repo)
            self.assertTrue(items["a"].process)
            self.assertFalse(items["b"].process)

    def test_rejects_non_boolean_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text("schema: 1\nitems: [a]\n")
            folder = repo / "a"
            folder.mkdir()
            (folder / "ci.yml").write_text(
                "id: a\nprocess: enabled\nsteps: [{id: test, run: [python, -c, 'print(1)']}]\n"
            )
            with self.assertRaisesRegex(ConfigError, "process must be true or false"):
                load_repository(repo)

    def test_processed_item_cannot_need_non_processed_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text("schema: 1\nitems: [a, b]\n")
            for name, extra in (("a", "process: false\n"), ("b", "needs: [a]\n")):
                folder = repo / name
                folder.mkdir()
                (folder / "ci.yml").write_text(
                    f"id: {name}\n{extra}steps: [{{id: test, run: [python, -c, 'print(1)']}}]\n"
                )
            with self.assertRaisesRegex(ConfigError, "processed item b needs non-processed item"):
                load_repository(repo)

    def test_accepts_direct_affected_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text("schema: 1\nitems: [summary]\n")
            folder = repo / "summary"
            folder.mkdir()
            (folder / "ci.yml").write_text(
                "id: summary\n"
                "strategy: {affected: direct}\n"
                "steps: [{id: collect, run: [python, -c, 'print(1)']}]\n"
            )
            items = load_repository(repo)
            self.assertEqual(items["summary"].affected, "direct")

    def test_root_timeout_and_step_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\n"
                "defaults: {timeout_seconds: 30}\n"
                "items: [a]\n"
            )
            folder = repo / "a"
            folder.mkdir()
            (folder / "ci.yml").write_text(
                "id: a\n"
                "steps:\n"
                "  - id: default\n"
                "    run: [python, -c, 'print(1)']\n"
                "  - id: override\n"
                "    timeout_seconds: 5\n"
                "    run: [python, -c, 'print(2)']\n"
            )

            item = load_repository(repo)["a"]
            self.assertEqual(item.steps[0].timeout_seconds, 30)
            self.assertEqual(item.steps[1].timeout_seconds, 5)

    def test_rejects_invalid_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\n"
                "defaults: {timeout_seconds: 0}\n"
                "items: [a]\n"
            )
            folder = repo / "a"
            folder.mkdir()
            (folder / "ci.yml").write_text(
                "id: a\n"
                "steps: [{id: test, run: [python, -c, 'print(1)']}]\n"
            )

            with self.assertRaisesRegex(
                ConfigError,
                "defaults.timeout_seconds must be a positive integer",
            ):
                load_repository(repo)

    def test_step_inputs_are_separate_from_watch(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [a]\n",
                encoding="utf-8",
            )
            folder = repo / "a"
            folder.mkdir()
            (folder / "ci.yml").write_text(
                "id: a\n"
                "watch: [a/**, shared/**]\n"
                "steps:\n"
                "  - id: build\n"
                "    inputs: [a/build.py, shared/data/**]\n"
                "    run: [python, build.py]\n"
                "  - id: verify\n"
                "    run: [python, verify.py]\n",
                encoding="utf-8",
            )

            item = load_repository(repo)["a"]
            self.assertEqual(
                item.steps[0].inputs,
                ("a/build.py", "shared/data/**"),
            )
            self.assertIsNone(item.steps[1].inputs)
            self.assertEqual(item.watch, ("a/**", "shared/**"))

    def test_rejects_generated_step_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [a]\n",
                encoding="utf-8",
            )
            folder = repo / "a"
            folder.mkdir()
            (folder / "ci.yml").write_text(
                "id: a\n"
                "steps:\n"
                "  - id: build\n"
                "    inputs: [build/generated.txt]\n"
                "    run: [python, -c, 'print(1)']\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ConfigError,
                "inputs must stay inside source paths",
            ):
                load_repository(repo)

    def test_rejects_reserved_evidence_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [a]\n",
                encoding="utf-8",
            )
            folder = repo / "a"
            folder.mkdir()
            (folder / "ci.yml").write_text(
                "id: a\n"
                "steps:\n"
                "  - id: build\n"
                "    run: [python, -c, 'print(1)']\n"
                "    outputs: [.cad-ci/result.json]\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ConfigError,
                "reserved .cad-ci namespace",
            ):
                load_repository(repo)

    def test_rejects_output_owned_by_two_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [a]\n",
                encoding="utf-8",
            )
            folder = repo / "a"
            folder.mkdir()
            (folder / "ci.yml").write_text(
                "id: a\n"
                "steps:\n"
                "  - id: build\n"
                "    run: [python, -c, 'print(1)']\n"
                "    outputs: [result.json]\n"
                "  - id: verify\n"
                "    run: [python, -c, 'print(2)']\n"
                "    outputs: [result.json]\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "step outputs overlap"):
                load_repository(repo)

    def test_rejects_parent_child_output_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [a]\n",
                encoding="utf-8",
            )
            folder = repo / "a"
            folder.mkdir()
            (folder / "ci.yml").write_text(
                "id: a\n"
                "steps:\n"
                "  - id: build\n"
                "    run: [python, -c, 'print(1)']\n"
                "    outputs: [results]\n"
                "  - id: verify\n"
                "    run: [python, -c, 'print(2)']\n"
                "    outputs: [results/verify.json]\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "step outputs overlap"):
                load_repository(repo)

    def test_rejects_dependency_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text("schema: 1\nitems: [a, b]\n")
            for name, need in (("a", "b"), ("b", "a")):
                folder = repo / name
                folder.mkdir()
                (folder / "ci.yml").write_text(
                    f"id: {name}\nneeds: [{need}]\nsteps:\n  - id: test\n    run: [python, -c, 'print(1)']\n"
                )
            with self.assertRaises(ConfigError):
                load_repository(repo)

    def test_rejects_empty_item_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text("schema: 1\nitems: [qualification/*]\n")
            with self.assertRaisesRegex(ConfigError, "matches no CI folders"):
                load_repository(repo)

    def test_rejects_output_outside_item_build_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text("schema: 1\nitems: [a]\n")
            folder = repo / "a"
            folder.mkdir()
            (folder / "ci.yml").write_text("id: a\nsteps: [{id: test, run: [python, -c, 'print(1)'], outputs: [../escape.txt]}]\n")
            with self.assertRaisesRegex(ConfigError, "output must stay"):
                load_repository(repo)


if __name__ == "__main__":
    unittest.main()
