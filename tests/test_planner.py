from pathlib import Path
import tempfile
import unittest

from cad_ci.config import load_repository
from cad_ci.planner import affected_items, build_plan


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


    def test_nested_sibling_change_selects_only_that_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\n"
                "items: [examples/a/*]\n"
                "templates:\n"
                "  reference:\n"
                "    watch: {item: ['**/*.py']}\n"
                "    steps: [{id: build, run: [python, model.py]}]\n",
                encoding="utf-8",
            )
            model = repo / "examples" / "a"
            model.mkdir(parents=True)
            (model / "ci.yml").write_text(
                "children: {template: reference}\n",
                encoding="utf-8",
            )
            for name in ("build123d", "cadquery"):
                child = model / name
                child.mkdir()
                (child / "ci.yml").write_text("{}\n", encoding="utf-8")
                (child / "model.py").write_text("print('ok')\n", encoding="utf-8")

            items = load_repository(repo)
            selected = affected_items(
                items,
                ("examples/a/build123d/model.py",),
            )
            self.assertEqual(selected, {"examples-a-build123d"})

    def test_ancestor_children_change_selects_all_descendants(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "cad-ci.yml").write_text(
                "schema: 1\n"
                "items: [examples/a/*]\n"
                "templates:\n"
                "  reference:\n"
                "    steps: [{id: build, run: [python, model.py]}]\n",
                encoding="utf-8",
            )
            model = repo / "examples" / "a"
            model.mkdir(parents=True)
            (model / "ci.yml").write_text(
                "children: {template: reference}\n",
                encoding="utf-8",
            )
            for name in ("build123d", "cadquery"):
                child = model / name
                child.mkdir()
                (child / "ci.yml").write_text("{}\n", encoding="utf-8")

            items = load_repository(repo)
            selected = affected_items(
                items,
                ("examples/a/ci.yml",),
            )
            self.assertEqual(
                selected,
                {"examples-a-build123d", "examples-a-cadquery"},
            )


if __name__ == "__main__":
    unittest.main()
