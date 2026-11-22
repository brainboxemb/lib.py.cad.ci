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


    def test_dependency_copy_expands_item_path_and_requires_direct_need(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [batch, examples/a]\n",
                encoding="utf-8",
            )
            batch = repo / "batch"
            batch.mkdir()
            (batch / "ci.yml").write_text(
                "id: batch\n"
                "steps:\n"
                "  - id: build\n"
                "    run: [python, -c, 'print(1)']\n"
                "    outputs: [items]\n",
                encoding="utf-8",
            )
            consumer = repo / "examples" / "a"
            consumer.mkdir(parents=True)
            (consumer / "ci.yml").write_text(
                "id: a\n"
                "needs: [batch]\n"
                "steps:\n"
                "  - id: copy\n"
                "    copy:\n"
                "      dependency: batch\n"
                "      source: items/{item_path}\n"
                "    outputs: [result.txt]\n",
                encoding="utf-8",
            )

            item = load_repository(repo)["a"]
            self.assertIsNone(item.steps[0].run)
            self.assertEqual(item.steps[0].copy.dependency, "batch")
            self.assertEqual(
                item.steps[0].copy.source,
                "items/examples/a",
            )
            self.assertEqual(item.steps[0].inputs, ())
            self.assertIsNone(item.steps[0].timeout_seconds)

    def test_rejects_invalid_dependency_copy_configuration(self):
        cases = (
            (
                "run: [python, -c, 'print(1)']\n"
                "    copy: {dependency: batch, source: items/a}\n"
                "    outputs: [result.txt]\n",
                "exactly one of run or copy",
            ),
            (
                "copy: {dependency: batch, source: items/a}\n",
                "requires at least one output",
            ),
            (
                "copy: {dependency: batch, source: items/a}\n"
                "    inputs: [consumer/**]\n"
                "    outputs: [result.txt]\n",
                "does not accept inputs",
            ),
            (
                "copy: {dependency: batch, source: 'items/{unknown}'}\n"
                "    outputs: [result.txt]\n",
                "unsupported substitution",
            ),
            (
                "copy: {dependency: batch, source: ../items/a}\n"
                "    outputs: [result.txt]\n",
                "stay inside dependency output",
            ),
        )
        for body, expected in cases:
            with self.subTest(expected=expected):
                with tempfile.TemporaryDirectory() as tmp:
                    repo = Path(tmp)
                    (repo / "cad-ci.yml").write_text(
                        "schema: 1\nitems: [batch, consumer]\n",
                        encoding="utf-8",
                    )
                    batch = repo / "batch"
                    batch.mkdir()
                    (batch / "ci.yml").write_text(
                        "id: batch\n"
                        "steps:\n"
                        "  - id: build\n"
                        "    run: [python, -c, 'print(1)']\n"
                        "    outputs: [items]\n",
                        encoding="utf-8",
                    )
                    consumer = repo / "consumer"
                    consumer.mkdir()
                    (consumer / "ci.yml").write_text(
                        "id: consumer\n"
                        "needs: [batch]\n"
                        "steps:\n"
                        "  - id: materialize\n"
                        f"    {body}",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(ConfigError, expected):
                        load_repository(repo)

    def test_rejects_copy_from_non_direct_or_undeclared_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [batch, consumer]\n",
                encoding="utf-8",
            )
            batch = repo / "batch"
            batch.mkdir()
            (batch / "ci.yml").write_text(
                "id: batch\n"
                "steps: [{id: build, run: [python, -c, 'print(1)'], outputs: [items]}]\n",
                encoding="utf-8",
            )
            consumer = repo / "consumer"
            consumer.mkdir()
            (consumer / "ci.yml").write_text(
                "id: consumer\n"
                "steps:\n"
                "  - id: materialize\n"
                "    copy: {dependency: batch, source: items/consumer}\n"
                "    outputs: [result.txt]\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "direct need"):
                load_repository(repo)

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [batch, consumer]\n",
                encoding="utf-8",
            )
            batch = repo / "batch"
            batch.mkdir()
            (batch / "ci.yml").write_text(
                "id: batch\n"
                "steps: [{id: build, run: [python, -c, 'print(1)'], outputs: [other]}]\n",
                encoding="utf-8",
            )
            consumer = repo / "consumer"
            consumer.mkdir()
            (consumer / "ci.yml").write_text(
                "id: consumer\n"
                "needs: [batch]\n"
                "steps:\n"
                "  - id: materialize\n"
                "    copy: {dependency: batch, source: items/consumer}\n"
                "    outputs: [result.txt]\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "outside dependency"):
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


    def test_item_scoped_paths_normalize_to_repository_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [examples/a]\n",
                encoding="utf-8",
            )
            folder = repo / "examples" / "a"
            folder.mkdir(parents=True)
            (folder / "ci.yml").write_text(
                "id: a\n"
                "watch:\n"
                "  item: [scpf/**, tests/**]\n"
                "  repo: [scripts/shared.py]\n"
                "steps:\n"
                "  - id: build\n"
                "    inputs:\n"
                "      item: [model.py]\n"
                "      repo: [scripts/shared.py]\n"
                "    run: [python, model.py]\n",
                encoding="utf-8",
            )

            item = load_repository(repo)["a"]
            self.assertEqual(
                item.watch,
                (
                    "examples/a/scpf/**",
                    "examples/a/tests/**",
                    "scripts/shared.py",
                ),
            )
            self.assertEqual(
                item.steps[0].inputs,
                (
                    "examples/a/model.py",
                    "scripts/shared.py",
                ),
            )

    def test_root_template_can_define_short_nested_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\n"
                "items: [examples/*/*]\n"
                "templates:\n"
                "  reference-build123d:\n"
                "    kind: reference\n"
                "    watch:\n"
                "      item: ['**']\n"
                "      repo: [verification/reference_validation.py]\n"
                "    strategy: {reuse: true}\n"
                "    steps:\n"
                "      - id: verify\n"
                "        inputs:\n"
                "          item: [model.py]\n"
                "          repo: [verification/reference_validation.py]\n"
                "        run: [python, model.py]\n"
                "        outputs: [reference]\n",
                encoding="utf-8",
            )
            child = repo / "examples" / "attach-angle" / "build123d"
            child.mkdir(parents=True)
            (child / "ci.yml").write_text(
                "template: reference-build123d\n",
                encoding="utf-8",
            )

            item = load_repository(repo)["examples-attach-angle-build123d"]
            self.assertEqual(item.kind, "reference")
            self.assertEqual(
                item.watch,
                (
                    "examples/attach-angle/build123d/**",
                    "verification/reference_validation.py",
                ),
            )
            self.assertEqual(
                item.steps[0].inputs,
                (
                    "examples/attach-angle/build123d/model.py",
                    "verification/reference_validation.py",
                ),
            )
            self.assertEqual(item.steps[0].outputs, ("reference",))

    def test_local_template_override_merges_mappings_and_replaces_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\n"
                "items: [nested/item]\n"
                "templates:\n"
                "  base:\n"
                "    watch:\n"
                "      item: ['**']\n"
                "      repo: [shared.py]\n"
                "    strategy: {reuse: true, affected: changed}\n"
                "    steps:\n"
                "      - id: base\n"
                "        run: [python, base.py]\n",
                encoding="utf-8",
            )
            folder = repo / "nested" / "item"
            folder.mkdir(parents=True)
            (folder / "ci.yml").write_text(
                "template: base\n"
                "watch:\n"
                "  item: [model.py]\n"
                "strategy:\n"
                "  reuse: false\n"
                "steps:\n"
                "  - id: local\n"
                "    run: [python, local.py]\n",
                encoding="utf-8",
            )

            item = load_repository(repo)["nested-item"]
            self.assertEqual(
                item.watch,
                ("nested/item/model.py", "shared.py"),
            )
            self.assertFalse(item.reuse)
            self.assertEqual(item.affected, "changed")
            self.assertEqual([step.id for step in item.steps], ["local"])

    def test_nested_implicit_ids_are_path_derived(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [examples/*/*]\n",
                encoding="utf-8",
            )
            for name in ("build123d", "cadquery"):
                folder = repo / "examples" / "attach-angle" / name
                folder.mkdir(parents=True)
                (folder / "ci.yml").write_text(
                    "steps: [{id: test, run: [python, -c, 'print(1)']}]\n",
                    encoding="utf-8",
                )

            items = load_repository(repo)
            self.assertEqual(
                set(items),
                {
                    "examples-attach-angle-build123d",
                    "examples-attach-angle-cadquery",
                },
            )

    def test_unknown_template_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [a]\n",
                encoding="utf-8",
            )
            folder = repo / "a"
            folder.mkdir()
            (folder / "ci.yml").write_text(
                "template: missing\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "unknown template"):
                load_repository(repo)

    def test_template_cannot_define_item_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\n"
                "items: [a]\n"
                "templates:\n"
                "  bad:\n"
                "    id: fixed\n"
                "    steps: [{id: test, run: [python, -c, 'print(1)']}]\n",
                encoding="utf-8",
            )
            folder = repo / "a"
            folder.mkdir()
            (folder / "ci.yml").write_text(
                "template: bad\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "unsupported field"):
                load_repository(repo)


    def test_item_scoped_parent_path_normalizes_inside_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [examples/a/build123d]\n",
                encoding="utf-8",
            )
            folder = repo / "examples" / "a" / "build123d"
            folder.mkdir(parents=True)
            (folder / "ci.yml").write_text(
                "watch:\n"
                "  item: [model.py, ../verification/reference_geometry.json]\n"
                "steps:\n"
                "  - id: build\n"
                "    inputs:\n"
                "      item: [../../shared.py, ../verification/reference_geometry.json]\n"
                "    run: [python, model.py]\n",
                encoding="utf-8",
            )

            item = load_repository(repo)["examples-a-build123d"]
            self.assertEqual(
                item.watch,
                (
                    "examples/a/build123d/model.py",
                    "examples/a/verification/reference_geometry.json",
                ),
            )
            self.assertEqual(
                item.steps[0].inputs,
                (
                    "examples/shared.py",
                    "examples/a/verification/reference_geometry.json",
                ),
            )

    def test_item_scoped_parent_path_cannot_escape_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [a]\n",
                encoding="utf-8",
            )
            folder = repo / "a"
            folder.mkdir()
            (folder / "ci.yml").write_text(
                "watch:\n"
                "  item: [../../escape.py]\n"
                "steps: [{id: build, run: [python, -c, 'print(1)']}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "must stay inside source paths"):
                load_repository(repo)

    def test_repository_scoped_parent_path_remains_invalid(self):
        cases = (
            "watch: [../shared.py]\n",
            "watch:\n  repo: [../shared.py]\n",
        )
        for watch in cases:
            with self.subTest(watch=watch):
                with tempfile.TemporaryDirectory() as tmp:
                    repo = Path(tmp)
                    (repo / "cad-ci.yml").write_text(
                        "schema: 1\nitems: [a]\n",
                        encoding="utf-8",
                    )
                    folder = repo / "a"
                    folder.mkdir()
                    (folder / "ci.yml").write_text(
                        watch
                        + "steps: [{id: build, run: [python, -c, 'print(1)']}]\n",
                        encoding="utf-8",
                    )

                    with self.assertRaisesRegex(
                        ConfigError,
                        "must stay inside source paths",
                    ):
                        load_repository(repo)

    def test_item_scoped_parent_path_cannot_enter_generated_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [examples/a]\n",
                encoding="utf-8",
            )
            folder = repo / "examples" / "a"
            folder.mkdir(parents=True)
            (folder / "ci.yml").write_text(
                "watch:\n"
                "  item: [../../build/generated.txt]\n"
                "steps: [{id: build, run: [python, -c, 'print(1)']}]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "must stay inside source paths"):
                load_repository(repo)


    def test_rejects_parent_output_overlapping_nested_item_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\n"
                "items: [cases/model, cases/model/reference]\n",
                encoding="utf-8",
            )

            parent = repo / "cases" / "model"
            parent.mkdir(parents=True)
            (parent / "ci.yml").write_text(
                "id: parent\n"
                "steps:\n"
                "  - id: build\n"
                "    run: [python, -c, 'print(1)']\n"
                "    outputs: [reference/result.txt]\n",
                encoding="utf-8",
            )

            child = parent / "reference"
            child.mkdir()
            (child / "ci.yml").write_text(
                "id: child\n"
                "steps:\n"
                "  - id: build\n"
                "    run: [python, -c, 'print(2)']\n"
                "    outputs: [result.txt]\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigError,
                "item output overlaps nested item root",
            ):
                load_repository(repo)


if __name__ == "__main__":
    unittest.main()
