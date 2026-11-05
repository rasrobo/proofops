"""Tests for the plugin surface a catalogue user meets first.

The plugin's tools are the product for a Hermes user, and the engine's tests say nothing
about them. Two first-run failures are covered here because both are invisible from inside
`python3 -m proofops`:

1. A catalogue install has no `./plans`, so the default plans directory has to fall back to
   the plugin's own — otherwise the first call is an error message.
2. A plan may be named (`claw-way-deployment`) rather than pathed, which is what a model
   will do after listing plans.

    python3 -m unittest discover -s tests -v
"""

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _load_plugin():
    spec = importlib.util.spec_from_file_location("proofops_plugin_under_test",
                                                 REPO / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PLUGIN = _load_plugin()


class TestFirstRun(unittest.TestCase):
    def test_plans_default_to_the_plugin_directory_outside_a_repo(self):
        """A user in their own project directory must still see the shipped plans."""
        here = os.getcwd()
        with tempfile.TemporaryDirectory() as d:
            os.chdir(d)
            try:
                self.assertFalse(pathlib.Path("plans").exists())
                out = json.loads(PLUGIN._plans({}))
            finally:
                os.chdir(here)
        self.assertNotIn("error", out, out.get("error"))
        self.assertGreaterEqual(len(out["plans"]), 5)
        self.assertIn("does_not_prove", out["plans"][0])

    def test_a_missing_explicit_directory_is_still_an_error(self):
        out = json.loads(PLUGIN._plans({"plans_dir": "/nonexistent-plans-dir"}))
        self.assertIn("error", out)

    def test_a_plan_can_be_named_rather_than_pathed(self):
        p = PLUGIN._resolve_plan("claw-way-deployment")
        self.assertTrue(p.exists(), p)
        self.assertEqual(p.name, "claw-way-deployment.json")

    def test_an_unknown_plan_is_refused_not_crashed(self):
        out = json.loads(PLUGIN._run({"plan": "no-such-plan", "target": "local"}))
        self.assertTrue(out.get("refused") or out.get("error"), out)
        self.assertFalse(out.get("ran", False))


class TestVerifyTool(unittest.TestCase):
    def test_the_plugin_verifies_a_sealed_receipt_and_reports_the_limit(self):
        engine = PLUGIN._engine()
        receipt_mod = importlib.import_module(f"{PLUGIN._ENGINE_NAME}.receipt")
        rec = receipt_mod.build(
            {"name": "p", "target_kind": "local", "checks": [], "does_not_prove": ["x"],
             "_revision": "sha256:abc", "_path": "plans/p.json"},
            "local",
            [{"id": "c", "type": "t", "passed": True, "proves": "x",
              "started_at": "2026-01-01T00:00:00+00:00", "evidence": {}}])
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "r.json"
            p.write_text(json.dumps(rec))
            out = json.loads(PLUGIN._verify({"receipt": str(p)}))
        self.assertEqual(out["integrity"], "valid")
        self.assertTrue(any("honestly" in line for line in out["does_not_prove"]))
        self.assertTrue(engine)

    def test_the_verify_tool_never_takes_a_key(self):
        """Catalogue rule 11: a plugin does not read credential files. Signing is CLI-only."""
        schemas = {name: schema for name, schema, _fn in PLUGIN._TOOLS}
        props = schemas["proofops_verify"]["parameters"]["properties"]
        self.assertEqual(set(props), {"receipt"}, f"unexpected parameters: {set(props)}")
        self.assertNotIn("key", json.dumps(props).lower())

    def test_a_signed_receipt_reports_needs_key_without_reading_one(self):
        receipt_mod = importlib.import_module(f"{PLUGIN._ENGINE_NAME}.receipt")
        rec = receipt_mod.build(
            {"name": "p", "target_kind": "local", "checks": [], "does_not_prove": ["x"],
             "_revision": "sha256:abc", "_path": "plans/p.json"},
            "local",
            [{"id": "c", "type": "t", "passed": True, "proves": "x",
              "started_at": "2026-01-01T00:00:00+00:00", "evidence": {}}],
            key="k" * 32)
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "r.json"
            p.write_text(json.dumps(rec))
            out = json.loads(PLUGIN._verify({"receipt": str(p)}))
        self.assertEqual(out["integrity"], "needs-key")

    def test_the_plugin_reports_a_tampered_receipt(self):
        receipt_mod = importlib.import_module(f"{PLUGIN._ENGINE_NAME}.receipt")
        rec = receipt_mod.build(
            {"name": "p", "target_kind": "local", "checks": [], "does_not_prove": ["x"],
             "_revision": "sha256:abc", "_path": "plans/p.json"},
            "local",
            [{"id": "c", "type": "t", "passed": False, "proves": "x",
              "started_at": "2026-01-01T00:00:00+00:00", "evidence": {}}])
        rec["summary"]["verdict"] = "PASS"
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "r.json"
            p.write_text(json.dumps(rec))
            out = json.loads(PLUGIN._verify({"receipt": str(p)}))
        self.assertEqual(out["integrity"], "tampered")
        self.assertIn("that the file is unmodified", out["does_not_prove"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
