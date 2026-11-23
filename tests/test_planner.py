from pathlib import Path
import tempfile
import unittest

from cad_ci.config import load_repository
from cad_ci.repository.planner import affected_items, build_plan


class PlannerTests(unittest.TestCase):
    def make_repo(self, root: Path):
        (root / "cad-ci.yml").write_text("schema: 1\nitems: [lib, example, qa, qb]\n")
        configs = {
            "lib": "id: lib\nwatch: [src/**, lib/**]\nsteps: [{id: test, run: [python, -c, 'print(1)']}]\n",
            "example": "id: example\nneeds: [lib]\nwatch: [example/**]\nsteps: [{id: test, run: [python, -c, 'print(1)']}]\n",
            "qa": "id: qa\nneeds: [example]\nwatch: [qa/**]\nsteps: [{id: test, run: [python, -c, 'print(1)']}]\n",
            "qb": "id: qb\nneeds: [example]\nwatch: [qb/**]\nsteps: [{id: test, run: [python, -c, 'print(1)']}]\n",
        }
        for name, config in configs.items():
            folder = root / name
            folder.mkdir(parents=True)
            (folder / "ci.yml").write_text(config)

    def test_one_case_change_does_not_select_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.make_repo(repo)
            items = load_repository(repo)
            selected = affected_items(items, ("qa/model.txt",))
            self.assertEqual(selected, {"qa"})
            plan = build_plan(items, selected)
            self.assertEqual([x.item.id for x in plan], ["lib", "example", "qa"])
            self.assertEqual([x.reason for x in plan], ["dependency", "dependency", "affected"])

    def test_shared_library_change_selects_dependants(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.make_repo(repo)
            items = load_repository(repo)
            selected = affected_items(items, ("src/core.py",))
            self.assertEqual(selected, {"lib", "example", "qa", "qb"})


    def test_direct_fan_in_item_is_not_selected_by_dependency_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.make_repo(repo)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [lib, example, qa, qb, summary]\n"
            )
            summary = repo / "summary"
            summary.mkdir()
            (summary / "ci.yml").write_text(
                "id: summary\n"
                "needs: [qa, qb]\n"
                "watch: [summary/**]\n"
                "strategy: {affected: direct}\n"
                "steps: [{id: collect, run: [python, -c, 'print(1)']}]\n"
            )
            items = load_repository(repo)

            selected = affected_items(items, ("qa/model.txt",))
            self.assertEqual(selected, {"qa"})
            plan = build_plan(items, selected)
            self.assertEqual(
                [entry.item.id for entry in plan],
                ["lib", "example", "qa"],
            )

    def test_direct_fan_in_item_still_expands_dependencies_when_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.make_repo(repo)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\nitems: [lib, example, qa, qb, summary]\n"
            )
            summary = repo / "summary"
            summary.mkdir()
            (summary / "ci.yml").write_text(
                "id: summary\n"
                "needs: [qa, qb]\n"
                "watch: [summary/**]\n"
                "strategy: {affected: direct}\n"
                "steps: [{id: collect, run: [python, -c, 'print(1)']}]\n"
            )
            items = load_repository(repo)

            selected = affected_items(items, ("summary/report.py",))
            self.assertEqual(selected, {"summary"})
            plan = build_plan(items, selected)
            self.assertEqual(
                [entry.item.id for entry in plan],
                ["lib", "example", "qa", "qb", "summary"],
            )

    def test_non_processed_item_is_excluded_from_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.make_repo(repo)
            qa = repo / "qa" / "ci.yml"
            qa.write_text("process: false\n" + qa.read_text())
            items = load_repository(repo)
            self.assertNotIn("qa", affected_items(items, None))
            self.assertNotIn("qa", affected_items(items, ("qa/model.txt",)))
            self.assertNotIn("qa", affected_items(items, ("cad-ci.yml",)))

    def test_dependency_fanout_ignores_non_processed_dependant(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.make_repo(repo)
            qa = repo / "qa" / "ci.yml"
            qa.write_text("process: false\n" + qa.read_text())
            items = load_repository(repo)
            selected = affected_items(items, ("src/core.py",))
            self.assertEqual(selected, {"lib", "example", "qb"})

    def test_always_item_is_selected_without_path_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.make_repo(repo)
            path = repo / "lib" / "ci.yml"
            path.write_text(path.read_text().replace("watch: [src/**, lib/**]", "strategy: {affected: always}\nwatch: [src/**, lib/**]"))
            items = load_repository(repo)
            selected = affected_items(items, ("README.md",))
            self.assertEqual(selected, {"lib", "example", "qa", "qb"})


    def test_nested_template_sibling_change_selects_only_that_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\n"
                "items: [examples/*/*]\n"
                "templates:\n"
                "  reference:\n"
                "    watch: {item: ['**']}\n"
                "    steps: [{id: build, run: [python, model.py]}]\n",
                encoding="utf-8",
            )
            for name in ("build123d", "cadquery"):
                folder = repo / "examples" / "attach-angle" / name
                folder.mkdir(parents=True)
                (folder / "ci.yml").write_text(
                    "template: reference\n",
                    encoding="utf-8",
                )
                (folder / "model.py").write_text(
                    "print('ok')\n",
                    encoding="utf-8",
                )

            items = load_repository(repo)
            selected = affected_items(
                items,
                ("examples/attach-angle/build123d/model.py",),
            )
            self.assertEqual(
                selected,
                {"examples-attach-angle-build123d"},
            )


    def test_parent_reference_contract_selects_nested_siblings(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\n"
                "items: [examples/*/*]\n"
                "templates:\n"
                "  reference:\n"
                "    watch:\n"
                "      item: ['**', ../verification/reference_geometry.json]\n"
                "    steps: [{id: build, run: [python, model.py]}]\n",
                encoding="utf-8",
            )
            for name in ("build123d", "cadquery"):
                folder = repo / "examples" / "attach-angle" / name
                folder.mkdir(parents=True)
                (folder / "ci.yml").write_text(
                    "template: reference\n",
                    encoding="utf-8",
                )

            items = load_repository(repo)
            selected = affected_items(
                items,
                ("examples/attach-angle/verification/reference_geometry.json",),
            )
            self.assertEqual(
                selected,
                {
                    "examples-attach-angle-build123d",
                    "examples-attach-angle-cadquery",
                },
            )


    def test_shared_builder_change_selects_every_builder_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\n"
                "items: [a, b]\n"
                "builders: {shared: ci/builders/shared}\n",
                encoding="utf-8",
            )
            builder = repo / "ci" / "builders" / "shared"
            builder.mkdir(parents=True)
            (builder / "builder.yml").write_text(
                "schema: 1\n"
                "steps: [{id: build, run: [python, -c, 'print(1)']}]\n",
                encoding="utf-8",
            )
            for name in ("a", "b"):
                folder = repo / name
                folder.mkdir()
                (folder / "ci.yml").write_text(
                    f"id: {name}\nbuilder: shared\n",
                    encoding="utf-8",
                )

            items = load_repository(repo)
            selected = affected_items(
                items,
                ("ci/builders/shared/build.py",),
            )
            self.assertEqual(selected, {"a", "b"})

if __name__ == "__main__":
    unittest.main()
