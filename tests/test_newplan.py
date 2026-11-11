"""Tests for `proofops new` and the run-mode annotation.

The generator's whole value is that its expectations are TRUE of the directory as it is, so the
central test writes a starter plan and then runs it: a first-run plan that fails on the
directory it was generated from would be worse than no generator at all.

The second test is the one that matters for honesty: change the directory, and the same plan
must fail. A starter plan that stays green when the data changes is decoration.
"""

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from proofops import cli as cli_mod          # noqa: E402
from proofops import newplan                 # noqa: E402
from proofops import plan as plan_mod        # noqa: E402
from proofops import runner                  # noqa: E402
from test_pdf import make_pdf                # noqa: E402


def build_corpus(root: pathlib.Path) -> None:
    (root / "data.csv").write_text("id,name\n1,alpha\n2,beta\n3,gamma\n")
    (root / "export").mkdir()
    (root / "export" / "a.txt").write_text("a")
    (root / "export" / "b.txt").write_text("bb")
    (root / "report.pdf").write_bytes(make_pdf(["Invoice", "Terms"]))
    import sqlite3

    conn = sqlite3.connect(root / "dc.db")
    conn.execute("create table messages (id integer primary key)")
    conn.execute("insert into messages (id) values (66)")
    conn.commit()
    conn.close()


class TestGenerate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        build_corpus(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_finds_what_is_there_and_declares_the_root(self):
        plan = newplan.build(self.root)
        self.assertEqual(plan["allowed_paths"], [str(self.root.resolve())])
        kinds = {c["type"] for c in plan["checks"]}
        self.assertIn("csv_stats", kinds)
        self.assertIn("dir_manifest", kinds)
        self.assertIn("pdf_pages", kinds)
        self.assertIn("sqlite_query", kinds)
        self.assertTrue(plan["does_not_prove"])

    def test_the_generated_plan_loads_and_passes_on_the_directory_it_came_from(self):
        plan = newplan.build(self.root)
        path = self.root / "plan.json"
        path.write_text(json.dumps(plan, indent=2))
        plan_mod.load(path)  # must not raise: no absolute check paths, roots declared
        rec, _ = runner.execute(str(path), "local", out=str(self.root / "r"))
        self.assertEqual(rec["summary"]["verdict"], "PASS",
                         json.dumps([(c["id"], c["evidence"]) for c in rec["checks"]
                                     if c["passed"] is not True], indent=2)[:800])

    def test_the_same_plan_fails_when_the_directory_changes(self):
        plan = newplan.build(self.root)
        path = self.root / "plan.json"
        path.write_text(json.dumps(plan, indent=2))
        (self.root / "data.csv").write_text("id,name\n1,alpha\n")
        rec, _ = runner.execute(str(path), "local", out=str(self.root / "r"))
        self.assertEqual(rec["summary"]["verdict"], "FAIL")
        self.assertIn("csv-data", [c["id"] for c in rec["checks"] if c["passed"] is False])

    def test_an_empty_directory_is_refused_clearly(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError) as e:
                newplan.build(d)
            self.assertIn("nothing verifiable", str(e.exception))

    def test_the_plugin_lists_run_mode_for_every_plan(self):
        import importlib.util as u

        spec = u.spec_from_file_location(
            "plugin_under_test", pathlib.Path(__file__).resolve().parents[1] / "__init__.py")
        mod = u.module_from_spec(spec)
        spec.loader.exec_module(mod)
        plans = json.loads(mod._plans({}))["plans"]
        self.assertTrue(plans)
        for p in plans:
            self.assertIn(p["run_mode"], ("read_only", "needs_operator_approval"))
        self.assertTrue(any(p["run_mode"] == "needs_operator_approval" for p in plans),
                        "at least one shipped plan uses commands")


class TestCli(unittest.TestCase):
    def test_new_writes_a_plan_and_refuses_to_overwrite(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "data.csv").write_text("a,b\n1,2\n")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(cli_mod.main(["new", "--dir", str(root)]), 0)
            out = root / "proofops-plan.json"
            self.assertTrue(out.exists())
            self.assertIn("wrote", buf.getvalue())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli_mod.main(["new", "--dir", str(root)]), 2)

    def test_stdout_mode_prints_a_loadable_plan(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "data.csv").write_text("a,b\n1,2\n")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(cli_mod.main(["new", "--dir", str(d), "--stdout"]), 0)
            doc = json.loads(buf.getvalue())
            self.assertIn("checks", doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
