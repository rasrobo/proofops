"""ProofOps's own tests.

A tool whose job is "do not trust a claim" should not itself be trusted on inspection.
These cover the properties the README asserts, including the ones that only matter when
they fail: that a weakened plan is detectable, that an undeclared origin is refused, and
that a command check cannot run without two independent opt-ins.

    python3 -m unittest discover -s tests -v
"""

import json
import pathlib
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from proofops import checks as checks_mod          # noqa: E402
from proofops import cli as cli_mod                # noqa: E402
from proofops import commands as commands_mod      # noqa: E402
from proofops import plan as plan_mod              # noqa: E402
from proofops import receipt as receipt_mod        # noqa: E402


# ---------------------------------------------------------------- fixture server
class _Handler(BaseHTTPRequestHandler):
    payload = {"status": "ok", "backend": "django", "database": "postgresql"}

    def do_GET(self):
        if self.path == "/health":
            body = json.dumps(self.payload).encode()
        else:
            body = b"<html>hello</html>"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class _Server:
    def __enter__(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"


def write_plan(tmp, **over):
    base = {
        "name": "test plan",
        "target_kind": "local-fixture",
        "allowed_origins": [],
        "checks": [{"id": "c1", "type": "http_status", "path": "/health",
                    "expect": 200, "proves": "answers"}],
        "does_not_prove": ["anything about correctness"],
    }
    base.update(over)
    p = pathlib.Path(tmp) / "plan.json"
    p.write_text(json.dumps(base))
    return p


# ---------------------------------------------------------------- plan validation
class TestPlanValidation(unittest.TestCase):
    def test_missing_does_not_prove_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_plan(d)
            doc = json.loads(p.read_text())
            del doc["does_not_prove"]
            p.write_text(json.dumps(doc))
            with self.assertRaises(plan_mod.PlanError) as e:
                plan_mod.load(p)
            self.assertIn("does_not_prove", str(e.exception))

    def test_check_without_proves_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_plan(d)
            doc = json.loads(p.read_text())
            del doc["checks"][0]["proves"]
            p.write_text(json.dumps(doc))
            with self.assertRaises(plan_mod.PlanError):
                plan_mod.load(p)

    def test_http_plan_needs_an_origin(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_plan(d)  # has an http check, allowed_origins empty
            with self.assertRaises(plan_mod.PlanError):
                plan_mod.load(p)

    def test_command_only_plan_may_have_no_origins(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_plan(d, checks=[{"id": "c1", "type": "command_exit",
                                       "command": "true", "proves": "runs"}],
                           allowed_commands=["true"])
            plan_mod.load(p)  # must not raise

    def test_undeclared_command_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_plan(d, checks=[{"id": "c1", "type": "command_exit",
                                       "command": "rm -rf /", "proves": "runs"}],
                           allowed_commands=["true"])
            with self.assertRaises(plan_mod.PlanError) as e:
                plan_mod.load(p)
            self.assertIn("allowed_commands", str(e.exception))

    def test_origin_allowlist_is_enforced(self):
        plan = {"allowed_origins": ["https://hub.example"]}
        plan_mod.check_origin(plan, "https://hub.example/health")   # allowed
        with self.assertRaises(plan_mod.PlanError):
            plan_mod.check_origin(plan, "https://evil.example/health")


# ---------------------------------------------------------------- plan revision
class TestRevision(unittest.TestCase):
    def test_revision_is_stable_across_key_order(self):
        a = {"name": "x", "allowed_origins": [], "checks": [], "does_not_prove": [],
             "target_kind": "t"}
        b = dict(reversed(list(a.items())))
        self.assertEqual(plan_mod.revision(a), plan_mod.revision(b))

    def test_weakening_a_plan_changes_its_revision(self):
        strong = {"name": "x", "allowed_origins": [], "target_kind": "t",
                  "does_not_prove": [],
                  "checks": [{"id": "c", "type": "http_status", "expect": 200}]}
        weak = json.loads(json.dumps(strong))
        weak["checks"][0]["expect"] = 500          # the assertion was weakened
        self.assertNotEqual(plan_mod.revision(strong), plan_mod.revision(weak))

    def test_loader_metadata_does_not_change_revision(self):
        p = {"name": "x", "allowed_origins": [], "target_kind": "t",
             "does_not_prove": [], "checks": []}
        before = plan_mod.revision(p)
        p["_path"] = "/tmp/whatever.json"
        p["_revision"] = "sha256:deadbeef"
        self.assertEqual(before, plan_mod.revision(p))


# ---------------------------------------------------------------- HTTP checks
class TestHttpChecks(unittest.TestCase):
    def test_status_matches(self):
        with _Server() as s:
            ok, ev = checks_mod.http_status({"path": "/health", "expect": 200}, s.base)
            self.assertTrue(ok)
            self.assertEqual(ev["observed_status"], 200)

    def test_status_mismatch_fails(self):
        with _Server() as s:
            ok, ev = checks_mod.http_status({"path": "/health", "expect": 201}, s.base)
            self.assertFalse(ok)
            self.assertEqual(ev["observed_status"], 200)

    def test_json_field_equals_is_exact(self):
        """'not_ok' must not satisfy equals 'ok' — the mistake 'contains' invites."""
        with _Server() as s:
            _Handler.payload = {"status": "not_ok"}
            try:
                ok, ev = checks_mod.http_json_field(
                    {"path": "/health", "field": "status", "equals": "ok"}, s.base)
                self.assertFalse(ok)
                self.assertEqual(ev["observed"], "not_ok")
            finally:
                _Handler.payload = {"status": "ok", "backend": "django",
                                    "database": "postgresql"}

    def test_json_field_nested_and_missing(self):
        with _Server() as s:
            ok, _ = checks_mod.http_json_field(
                {"path": "/health", "field": "database", "equals": "postgresql"}, s.base)
            self.assertTrue(ok)
            ok, ev = checks_mod.http_json_field(
                {"path": "/health", "field": "missing.field", "equals": "x"}, s.base)
            self.assertFalse(ok)
            self.assertIsNone(ev["observed"])

    def test_non_json_body_is_reported_not_crashed(self):
        with _Server() as s:
            ok, ev = checks_mod.http_json_field(
                {"path": "/", "field": "status", "equals": "ok"}, s.base)
            self.assertFalse(ok)
            self.assertFalse(ev["body_parsed_as_json"])

    def test_connection_failure_is_evidence_not_exception(self):
        ok, ev = checks_mod.http_status(
            {"path": "/health", "expect": 200}, "http://127.0.0.1:1")
        self.assertFalse(ok)
        self.assertTrue(ev["error"])


# ---------------------------------------------------------------- command gates
class TestCommandPolicy(unittest.TestCase):
    def test_denied_by_default(self):
        commands_mod.set_policy(commands_mod.CommandPolicy())
        ok, ev = commands_mod.command_exit({"command": "true"}, "local")
        # None, not False: nothing ran, so nothing may be recorded as having failed.
        self.assertIsNone(ok, "a refusal must not be recorded as a failed assertion")
        self.assertEqual(ev["status"], "not_run")
        self.assertIn("disabled", ev["refused"])

    def test_enabled_but_undeclared_is_refused(self):
        commands_mod.set_policy(commands_mod.CommandPolicy(enabled=True, allowed=("false",)))
        ok, ev = commands_mod.command_exit({"command": "true"}, "local")
        self.assertIsNone(ok)
        self.assertIn("allowed_commands", ev["refused"])

    def test_enabled_and_declared_runs(self):
        commands_mod.set_policy(commands_mod.CommandPolicy(enabled=True, allowed=("echo hi",)))
        ok, ev = commands_mod.command_exit({"command": "echo hi"}, "local")
        self.assertTrue(ok)
        self.assertIn("hi", ev["stdout_tail"])

    def test_exit_code_is_honoured(self):
        commands_mod.set_policy(commands_mod.CommandPolicy(enabled=True, allowed=("false",)))
        ok, ev = commands_mod.command_exit({"command": "false", "expect_exit": 0}, "local")
        self.assertFalse(ok)
        self.assertNotEqual(ev["observed_exit"], 0)

    def test_identical_commands_run_once_per_run(self):
        """Two checks asserting different things must not execute the command twice."""
        marker = pathlib.Path(tempfile.mkdtemp()) / "count"
        cmd = f"sh -c 'echo x >> {marker}'"
        commands_mod.set_policy(commands_mod.CommandPolicy(enabled=True, allowed=(cmd,)))
        commands_mod.command_exit({"command": cmd}, "local")
        ok, ev = commands_mod.command_exit({"command": cmd, "stdout_contains": ""}, "local")
        self.assertTrue(ok)
        self.assertTrue(ev.get("reused_from_cache"))
        self.assertEqual(len(marker.read_text().splitlines()), 1)

    def test_policy_reset_clears_the_cache(self):
        commands_mod.set_policy(commands_mod.CommandPolicy(enabled=True, allowed=("true",)))
        commands_mod.command_exit({"command": "true"}, "local")
        commands_mod.set_policy(commands_mod.CommandPolicy(enabled=True, allowed=("true",)))
        ok, ev = commands_mod.command_exit({"command": "true"}, "local")
        self.assertFalse(ev.get("reused_from_cache", False))


# ---------------------------------------------------------------- receipts
class TestReceipt(unittest.TestCase):
    def _plan(self):
        return {"name": "p", "target_kind": "local", "checks": [],
                "does_not_prove": ["nothing about data"], "_revision": "sha256:abc",
                "_path": "plans/p.json"}

    def test_limitations_are_copied_into_every_receipt(self):
        rec = receipt_mod.build(self._plan(), "local", [
            {"id": "c", "type": "t", "passed": True, "proves": "x",
             "started_at": "2026-01-01T00:00:00+00:00", "evidence": {}}])
        self.assertEqual(rec["does_not_prove"], ["nothing about data"])
        self.assertEqual(rec["summary"]["verdict"], "PASS")

    def test_one_failure_makes_the_verdict_fail(self):
        rec = receipt_mod.build(self._plan(), "local", [
            {"id": "a", "type": "t", "passed": True, "proves": "x",
             "started_at": "2026-01-01T00:00:00+00:00", "evidence": {}},
            {"id": "b", "type": "t", "passed": False, "proves": "y",
             "started_at": "2026-01-01T00:00:00+00:00", "evidence": {}}])
        self.assertEqual(rec["summary"]["verdict"], "FAIL")
        self.assertEqual(rec["summary"]["failed"], 1)

    def test_run_ids_are_unique(self):
        ids = {receipt_mod.new_run_id() for _ in range(50)}
        self.assertEqual(len(ids), 50)

    def test_receipt_embeds_the_plan_so_it_can_be_replayed(self):
        rec = receipt_mod.build(self._plan(), "local", [
            {"id": "c", "type": "t", "passed": True, "proves": "x",
             "started_at": "2026-01-01T00:00:00+00:00", "evidence": {}}])
        body = rec["plan_body"]
        self.assertEqual(body["name"], "p")
        self.assertIn("does_not_prove", body)
        self.assertNotIn("_path", body, "loader metadata must not leak into the receipt")

    def test_not_run_makes_the_verdict_incomplete_not_fail(self):
        """A check that was refused must not read as 'tested and broken'."""
        rec = receipt_mod.build(self._plan(), "local", [
            {"id": "a", "type": "t", "passed": True, "proves": "x",
             "started_at": "2026-01-01T00:00:00+00:00", "evidence": {}},
            {"id": "b", "type": "t", "passed": None, "proves": "y",
             "started_at": "2026-01-01T00:00:00+00:00",
             "evidence": {"status": "not_run", "refused": "commands are disabled"}}])
        self.assertEqual(rec["summary"]["verdict"], "INCOMPLETE")
        self.assertEqual(rec["summary"]["not_run"], 1)
        self.assertEqual(rec["summary"]["failed"], 0)
        self.assertIn("[NOT RUN]", receipt_mod.summarise(rec))
        self.assertNotIn("[FAIL]", receipt_mod.summarise(rec))

    def test_a_real_failure_outranks_an_incomplete_check(self):
        rec = receipt_mod.build(self._plan(), "local", [
            {"id": "a", "type": "t", "passed": False, "proves": "x",
             "started_at": "2026-01-01T00:00:00+00:00", "evidence": {}},
            {"id": "b", "type": "t", "passed": None, "proves": "y",
             "started_at": "2026-01-01T00:00:00+00:00", "evidence": {}}])
        self.assertEqual(rec["summary"]["verdict"], "FAIL")

    def test_a_failing_check_shows_the_mismatch_not_truncated_json(self):
        """A line that ends mid-token reads as broken output — show the mismatch instead."""
        rec = receipt_mod.build(self._plan(), "local", [
            {"id": "c", "type": "csv_stats", "passed": False, "proves": "rows complete",
             "started_at": "2026-01-01T00:00:00+00:00",
             "evidence": {"path": "data.csv", "mismatches": [
                 {"field": "nulls.Country", "expected": 0, "observed": 1}]}}])
        text = receipt_mod.summarise(rec)
        self.assertIn("nulls.Country", text)
        self.assertIn("expected 0", text)
        self.assertNotIn('"mismatches"', text)

    def test_receipt_records_the_plan_revision(self):
        rec = receipt_mod.build(self._plan(), "local", [
            {"id": "c", "type": "t", "passed": True, "proves": "x",
             "started_at": "2026-01-01T00:00:00+00:00", "evidence": {}}])
        self.assertEqual(rec["plan_revision"], "sha256:abc")


class TestCliExitCodes(unittest.TestCase):
    """The contract a script depends on. Before this existed, a refused command exited 1
    and wrote a FAIL receipt, so CI would report 'the deployment check failed' for a check
    the operator had deliberately not authorised."""

    def test_refused_command_exits_2_and_writes_no_fail(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as d:
            p = write_plan(
                d,
                checks=[{"id": "c", "type": "command_exit",
                         "command": "echo should-not-run", "proves": "runs"}],
                allowed_commands=["echo should-not-run"])
            out = pathlib.Path(d) / "receipts"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = cli_mod.main(["run", str(p), "--target", "local", "--out", str(out)])
            self.assertEqual(code, 2, "refused must not be reported as a failed check")
            self.assertIn("NOT RUN", buf.getvalue())
            rec = json.loads(next(out.glob("*.json")).read_text())
            self.assertEqual(rec["summary"]["verdict"], "INCOMPLETE")
            self.assertEqual(rec["summary"]["failed"], 0)
            self.assertEqual(rec["summary"]["not_run"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
