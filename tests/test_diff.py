"""`proofops diff` — the question after a repair: better, or did I break something else?"""
import json
import tempfile
import unittest
from pathlib import Path

from proofops import diff


def receipt(checks, revision="sha256:aa", run_id="PO-1", verdict="FAIL"):
    return {"run_id": run_id, "plan": "p", "plan_revision": revision,
            "summary": {"verdict": verdict}, "checks": checks}


def check(cid, passed, observed="", type_="http_status"):
    ev = {} if passed is None else {"observed": observed}
    return {"id": cid, "type": type_, "passed": passed, "proves": "x", "evidence": ev}


class TestDiff(unittest.TestCase):
    def test_a_failure_that_now_passes_is_fixed(self):
        r = diff.compare(receipt([check("a", False, "degraded")], verdict="FAIL"),
                         receipt([check("a", True, "ok")], run_id="PO-2", verdict="PASS"))
        self.assertEqual(r["counts"], {"fixed": 1})
        self.assertEqual(r["regressed"], [])
        self.assertEqual(diff.exit_code(r), 0)

    def test_a_pass_that_now_fails_is_a_regression_and_exits_1(self):
        r = diff.compare(receipt([check("a", True, "ok")], verdict="PASS"),
                         receipt([check("a", False, "degraded")], run_id="PO-2"))
        self.assertEqual([x["id"] for x in r["regressed"]], ["a"])
        self.assertEqual(diff.exit_code(r), 1, "a regression is worse than nothing")
        self.assertIn("REGRESSED", diff.render(r))

    def test_not_run_is_its_own_state_not_a_failure(self):
        """Collapsing NOT RUN into fail would call a plan problem a service regression."""
        r = diff.compare(receipt([check("a", True, "ok")], verdict="PASS"),
                         receipt([check("a", None)], run_id="PO-2", verdict="INCOMPLETE"))
        self.assertEqual(r["counts"], {"no_longer_runs": 1})
        self.assertEqual(r["regressed"], [], "could-not-run is not a regression")
        self.assertEqual(diff.exit_code(r), 0)

    def test_a_different_plan_revision_is_refused_by_default(self):
        with self.assertRaises(diff.DiffError) as ctx:
            diff.compare(receipt([], revision="sha256:aa"), receipt([], revision="sha256:bb"))
        self.assertIn("different plan revisions", str(ctx.exception))

    def test_revision_change_can_be_allowed_on_request(self):
        r = diff.compare(receipt([], revision="sha256:aa"), receipt([], revision="sha256:bb"),
                         allow_revision_change=True)
        self.assertEqual(r["checks"], [])

    def test_added_and_removed_checks_are_named(self):
        r = diff.compare(receipt([check("gone", True, "ok")], verdict="PASS"),
                         receipt([check("new", False, "boom")], run_id="PO-2"))
        changes = {c["id"]: c["change"] for c in r["checks"]}
        self.assertEqual(changes, {"gone": "removed", "new": "added"})

    def test_identical_receipts_say_so(self):
        rec = receipt([check("a", True, "ok")], verdict="PASS")
        r = diff.compare(rec, dict(rec))
        self.assertIn("nothing changed", diff.render(r))
        self.assertEqual(diff.exit_code(r), 0)

    def test_the_render_always_states_what_it_does_not_prove(self):
        r = diff.compare(receipt([check("a", False, "x")]), receipt([check("a", True, "y")], run_id="PO-2"))
        self.assertIn("does NOT prove", diff.render(r))


class TestDiffCli(unittest.TestCase):
    def test_cli_refuses_a_missing_file_and_exits_2(self):
        from proofops import cli
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(cli.main(["diff", str(Path(td, "nope.json")), str(Path(td, "no.json"))]), 2)

    def test_cli_prints_json_on_request(self):
        from proofops import cli
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td, "a.json"), Path(td, "b.json")
            a.write_text(json.dumps(receipt([check("x", True, "ok")], verdict="PASS")))
            b.write_text(json.dumps(receipt([check("x", False, "gone")], run_id="PO-2")))
            code = cli.main(["diff", str(a), str(b), "--json"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
