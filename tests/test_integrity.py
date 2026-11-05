"""Tests for receipt integrity, verifier provenance, and evidence extraction.

Three claims the product makes were not true of the artefact it produced:

1. The executive summary says a receipt is a *signed* record. It was plain JSON that any
   editor (or a careless agent) could rewrite after the fact — "PASS" with a typo fix.
2. A receipt named the ProofOps version as a hardcoded string, so it could not say *which
   build* of the inspector produced the evidence.
3. A failing command check buried the number that mattered inside a truncated stdout tail:
   a schema-drift receipt said FAIL without saying "39 drifts".

    python3 -m unittest discover -s tests -v
"""

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from proofops import cli as cli_mod                # noqa: E402
from proofops import commands as commands_mod     # noqa: E402
from proofops import integrity as integrity_mod   # noqa: E402
from proofops import plan as plan_mod             # noqa: E402
from proofops import receipt as receipt_mod       # noqa: E402


def _results(**over):
    base = {"id": "c", "type": "t", "passed": True, "proves": "x",
            "started_at": "2026-01-01T00:00:00+00:00", "evidence": {}}
    base.update(over)
    return [base]


def _plan():
    return {"name": "p", "target_kind": "local", "checks": [],
            "does_not_prove": ["nothing about data"], "_revision": "sha256:abc",
            "_path": "plans/p.json"}


class TestSealing(unittest.TestCase):
    def test_a_receipt_is_sealed_and_verifies(self):
        rec = receipt_mod.build(_plan(), "local", _results())
        self.assertIn("integrity", rec, "a receipt that can be edited silently is not evidence")
        verdict, detail = integrity_mod.verify(rec)
        self.assertEqual(verdict, "valid", detail)

    def test_editing_a_verdict_after_sealing_is_detected(self):
        rec = receipt_mod.build(_plan(), "local", _results(passed=False))
        rec["summary"]["verdict"] = "PASS"
        rec["checks"][0]["passed"] = True          # the classic edit: make the failure go away
        verdict, detail = integrity_mod.verify(rec)
        self.assertEqual(verdict, "tampered", detail)

    def test_editing_the_limitations_is_detected(self):
        """Removing `does_not_prove` makes the evidence look stronger than it is."""
        rec = receipt_mod.build(_plan(), "local", _results())
        rec["does_not_prove"] = []
        verdict, _ = integrity_mod.verify(rec)
        self.assertEqual(verdict, "tampered")

    def test_a_keyed_receipt_needs_the_key_to_verify(self):
        rec = receipt_mod.build(_plan(), "local", _results(), key="k" * 32)
        self.assertEqual(rec["integrity"]["alg"], "hmac-sha256")
        verdict, detail = integrity_mod.verify(rec)
        self.assertEqual(verdict, "needs-key", detail)
        verdict, detail = integrity_mod.verify(rec, key="k" * 32)
        self.assertEqual(verdict, "valid", detail)

    def test_a_wrong_key_is_a_tamper_not_a_pass(self):
        rec = receipt_mod.build(_plan(), "local", _results(), key="k" * 32)
        verdict, _ = integrity_mod.verify(rec, key="z" * 32)
        self.assertEqual(verdict, "tampered")

    def test_an_unsealed_receipt_is_reported_as_unsealed(self):
        rec = receipt_mod.build(_plan(), "local", _results())
        del rec["integrity"]
        verdict, detail = integrity_mod.verify(rec)
        self.assertEqual(verdict, "unsealed", detail)

    def test_verify_survives_a_json_round_trip(self):
        """A receipt is read back from disk by someone else — sealing must survive that."""
        rec = receipt_mod.build(_plan(), "local", _results())
        again = json.loads(json.dumps(rec))
        verdict, detail = integrity_mod.verify(again)
        self.assertEqual(verdict, "valid", detail)


class TestProvenance(unittest.TestCase):
    def test_receipt_names_the_build_that_produced_it(self):
        rec = receipt_mod.build(_plan(), "local", _results())
        env = rec["environment"]
        self.assertEqual(env["proofops"], receipt_mod.__dict__.get("__version__", env["proofops"]))
        self.assertNotEqual(env["proofops"], "", "the inspector must identify itself")
        self.assertIn("commit", env, "a receipt must say which build of the inspector ran")
        self.assertIn("host", env)

    def test_version_comes_from_the_package_not_a_literal(self):
        from proofops import __version__
        rec = receipt_mod.build(_plan(), "local", _results())
        self.assertEqual(rec["environment"]["proofops"], __version__)


class TestExtraction(unittest.TestCase):
    def test_a_command_check_can_extract_the_number_that_matters(self):
        """'FAIL' with no number is a receipt that makes you go and re-run the thing."""
        commands_mod.set_policy(commands_mod.CommandPolicy(
            enabled=True, allowed=("echo schema drift: 39",)))
        ok, ev = commands_mod.command_exit(
            {"command": "echo schema drift: 39", "expect_exit": 0,
             "extract": {"name": "drift_count", "regex": r"schema drift: (\d+)"}}, "local")
        self.assertTrue(ok)
        self.assertEqual(ev["extracted"], {"drift_count": "39"})

    def test_a_missing_extraction_is_recorded_and_does_not_invent_a_pass(self):
        commands_mod.set_policy(commands_mod.CommandPolicy(enabled=True, allowed=("echo hi",)))
        ok, ev = commands_mod.command_exit(
            {"command": "echo hi", "extract": {"name": "n", "regex": r"drift: (\d+)"}}, "local")
        self.assertTrue(ok, "extraction is evidence enrichment, not an assertion")
        self.assertIn("extracted", ev)
        self.assertIsNone(ev["extracted"]["n"])
        self.assertTrue(ev["extract_error"])

    def test_plan_rejects_an_extraction_without_a_regex(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "plan.json"
            p.write_text(json.dumps({
                "name": "p", "target_kind": "local", "allowed_origins": [],
                "allowed_commands": ["true"],
                "checks": [{"id": "c", "type": "command_exit", "command": "true",
                            "proves": "runs", "extract": {"name": "n"}}],
                "does_not_prove": ["x"]}))
            with self.assertRaises(plan_mod.PlanError) as e:
                plan_mod.load(p)
            self.assertIn("extract", str(e.exception))


class TestCliVerify(unittest.TestCase):
    def _write(self, d, key=None):
        rec = receipt_mod.build(_plan(), "local", _results(), key=key)
        path = pathlib.Path(d) / "r.json"
        path.write_text(json.dumps(rec, indent=2))
        return path

    def test_verify_exits_0_for_an_intact_receipt(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(cli_mod.main(["verify", str(p)]), 0)
            self.assertIn("valid", buf.getvalue().lower())

    def test_verify_exits_1_for_a_tampered_receipt(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d)
            doc = json.loads(p.read_text())
            doc["summary"]["verdict"] = "PASS" if doc["summary"]["verdict"] != "PASS" else "FAIL"
            p.write_text(json.dumps(doc))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli_mod.main(["verify", str(p)]), 1)

    def test_verify_exits_2_when_the_key_is_missing(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, key="k" * 32)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli_mod.main(["verify", str(p)]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
